"""Orchestrate: fetch bookmarks → extract articles → embed → index."""
from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass, field

from .config import get_settings
from . import db
from .twitter import fetch_bookmarks, should_extract_article
from .extractor import extract_article
from .embedder import get_embedder
from .ideas import extract_idea

logger = logging.getLogger(__name__)

_ARTICLE_WORKERS = 5


@dataclass
class SyncResult:
    new_tweets: int = 0
    new_articles: int = 0
    new_embeddings: int = 0
    new_ideas: int = 0
    errors: list[str] = field(default_factory=list)


def run_sync(full: bool = False) -> SyncResult:
    cfg = get_settings()
    db.init_db()

    if cfg.sync_source == "birdclaw":
        return _sync_from_birdclaw(cfg, full)
    else:
        return _sync_from_xapi(cfg, full)


def _sync_from_birdclaw(cfg, full: bool) -> SyncResult:
    from .birdclaw_reader import read_bookmarks

    result = SyncResult()
    known_ids: set[str] = set() if full else _get_known_ids()

    logger.info("Reading bookmarks from Birdclaw (full=%s)", full)
    try:
        tweets = read_bookmarks(cfg.birdclaw_home or None, known_ids)
    except RuntimeError as exc:
        result.errors.append(str(exc))
        logger.error("%s", exc)
        return result

    new_tweet_ids: list[str] = []
    for tweet in tweets:
        db.upsert_tweet(tweet)
        new_tweet_ids.append(tweet.tweet_id)
        result.new_tweets += 1
        for url_obj in tweet.urls:
            expanded = url_obj.get("expanded_url", "") or url_obj.get("url", "")
            if expanded and should_extract_article(expanded):
                db.upsert_article(db.ArticleData(tweet_id=tweet.tweet_id, url=expanded, fetch_status=0))

    db.set_sync_state("birdclaw", None)
    logger.info("Loaded %d new tweets from Birdclaw", result.new_tweets)
    return _process_pipeline(result, new_tweet_ids)


def _sync_from_xapi(cfg, full: bool) -> SyncResult:
    if not cfg.twitter_user_id:
        raise RuntimeError("TWITTER_USER_ID not set. Run `xarchiver auth` first.")

    result = SyncResult()
    next_token: str | None = None
    new_tweet_ids: list[str] = []

    logger.info("Fetching bookmarks from X API (full=%s)", full)
    fetch_result = None
    while True:
        fetch_result = fetch_bookmarks(cfg.twitter_user_id, next_token)
        if not fetch_result.tweets:
            break

        stop = False
        for tweet in fetch_result.tweets:
            if not full and db.tweet_exists(tweet.tweet_id):
                stop = True
                break
            db.upsert_tweet(tweet)
            new_tweet_ids.append(tweet.tweet_id)
            result.new_tweets += 1
            for url_obj in tweet.urls:
                expanded = url_obj.get("expanded_url", "") or url_obj.get("url", "")
                if expanded and should_extract_article(expanded):
                    db.upsert_article(db.ArticleData(tweet_id=tweet.tweet_id, url=expanded, fetch_status=0))

        if stop or not fetch_result.next_token:
            break
        next_token = fetch_result.next_token

    db.set_sync_state(cfg.twitter_user_id, fetch_result.next_token if fetch_result else None)
    logger.info("Fetched %d new tweets from X API", result.new_tweets)
    return _process_pipeline(result, new_tweet_ids)


def _get_known_ids() -> set[str]:
    conn = db.get_conn()
    rows = conn.execute("SELECT tweet_id FROM tweets").fetchall()
    return {r["tweet_id"] for r in rows}


def _process_pipeline(result: SyncResult, new_tweet_ids: list[str]) -> SyncResult:
    """Shared post-fetch pipeline: articles → embeddings → FTS → ideas → Notion."""
    cfg = get_settings()

    # Extract articles
    pending = db.get_unarticled_urls()
    if pending:
        logger.info("Extracting %d article URLs", len(pending))
        with concurrent.futures.ThreadPoolExecutor(max_workers=_ARTICLE_WORKERS) as pool:
            futures = {pool.submit(extract_article, r["tweet_id"], r["url"]): r for r in pending}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    article = fut.result()
                    db.upsert_article(article)
                    if article.body_text:
                        result.new_articles += 1
                except Exception as exc:
                    result.errors.append(str(exc))
                    logger.error("Article extraction error: %s", exc)

    # Embed
    embedder = get_embedder()
    unembedded_tweets = db.get_unembedded_tweets(cfg.embed_model)
    if unembedded_tweets:
        logger.info("Embedding %d tweets", len(unembedded_tweets))
        for rec in embedder.embed_tweets(unembedded_tweets):
            db.upsert_embedding(rec)
            result.new_embeddings += 1

    unembedded_articles = db.get_unembedded_articles(cfg.embed_model)
    if unembedded_articles:
        logger.info("Embedding %d articles", len(unembedded_articles))
        for rec in embedder.embed_articles(unembedded_articles):
            db.upsert_embedding(rec)
            result.new_embeddings += 1

    if new_tweet_ids:
        db.update_fts(new_tweet_ids)

    # Extract ideas
    if cfg.anthropic_api_key:
        todo = db.get_tweets_without_ideas()
        if todo:
            logger.info("Extracting ideas for %d tweets", len(todo))
        for row in todo:
            article = db.get_best_article_for_tweet(row["tweet_id"])
            idea = extract_idea(
                tweet_id=row["tweet_id"],
                tweet_text=row["text"],
                author=row["author_username"],
                article_id=article["id"] if article else None,
                article_title=article["title"] if article else None,
                article_body=article["body_text"] if article else None,
            )
            if idea:
                db.upsert_idea(db.IdeaData(
                    tweet_id=idea.tweet_id, article_id=idea.article_id,
                    summary=idea.summary, key_concepts=idea.key_concepts,
                    category=idea.category, tags=idea.tags,
                    relevance_score=idea.relevance_score,
                ))
                result.new_ideas += 1

    # Publish to Notion
    if cfg.notion_api_token and cfg.notion_database_id:
        import json as _json
        from .notion_publisher import publish_idea
        pending_notion = db.get_unpublished_ideas()
        if pending_notion:
            logger.info("Publishing %d ideas to Notion", len(pending_notion))
        for row in pending_notion:
            try:
                page_id = publish_idea(
                    tweet_id=row["tweet_id"],
                    author=row["author"],
                    summary=row["summary"],
                    key_concepts=_json.loads(row["key_concepts"] or "[]"),
                    category=row["category"],
                    tags=_json.loads(row["tags"] or "[]"),
                    relevance=row["relevance_score"],
                    tweet_text=row["tweet_text"],
                    tweet_url=f"https://twitter.com/{row['author']}/status/{row['tweet_id']}",
                    article_title=row["article_title"],
                    article_body=row["article_body"],
                    article_url=row["article_url"],
                    bookmarked_at=row["tweet_created_at"],
                )
                db.set_notion_page_id(row["tweet_id"], page_id)
            except Exception as exc:
                result.errors.append(f"Notion: {exc}")
                logger.error("Notion publish error: %s", exc)

    logger.info(
        "Pipeline done: %d tweets, %d articles, %d embeddings, %d ideas",
        result.new_tweets, result.new_articles, result.new_embeddings, result.new_ideas,
    )
    return result
