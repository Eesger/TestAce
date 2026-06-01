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

logger = logging.getLogger(__name__)

_ARTICLE_WORKERS = 5


@dataclass
class SyncResult:
    new_tweets: int = 0
    new_articles: int = 0
    new_embeddings: int = 0
    errors: list[str] = field(default_factory=list)


def run_sync(full: bool = False) -> SyncResult:
    """
    full=False: stop pagination when an already-stored tweet is encountered.
    full=True: page through all bookmarks regardless.
    """
    cfg = get_settings()
    if not cfg.twitter_user_id:
        raise RuntimeError("TWITTER_USER_ID not set. Run `xarchiver auth` first.")

    db.init_db()
    result = SyncResult()

    stored_next_token, _ = db.get_sync_state(cfg.twitter_user_id)
    next_token: str | None = None if full else None  # always start from newest
    new_tweet_ids: list[str] = []

    logger.info("Starting sync (full=%s)", full)
    while True:
        fetch_result = fetch_bookmarks(cfg.twitter_user_id, next_token)
        if not fetch_result.tweets:
            break

        stop = False
        for tweet in fetch_result.tweets:
            if not full and db.tweet_exists(tweet.tweet_id):
                logger.debug("Reached known tweet %s, stopping pagination", tweet.tweet_id)
                stop = True
                break
            db.upsert_tweet(tweet)
            new_tweet_ids.append(tweet.tweet_id)
            result.new_tweets += 1

            # Register article URLs immediately so they appear in get_unarticled_urls()
            for url_obj in tweet.urls:
                expanded = url_obj.get("expanded_url", "") or url_obj.get("url", "")
                if expanded and should_extract_article(expanded):
                    db.upsert_article(
                        db.ArticleData(tweet_id=tweet.tweet_id, url=expanded, fetch_status=0)
                    )

        if stop or not fetch_result.next_token:
            break
        next_token = fetch_result.next_token

    db.set_sync_state(cfg.twitter_user_id, fetch_result.next_token if 'fetch_result' in dir() else None)
    logger.info("Fetched %d new tweets", result.new_tweets)

    # Extract articles concurrently
    pending = db.get_unarticled_urls()
    logger.info("Extracting %d article URLs", len(pending))
    if pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=_ARTICLE_WORKERS) as pool:
            futures = {
                pool.submit(extract_article, row["tweet_id"], row["url"]): row
                for row in pending
            }
            for fut in concurrent.futures.as_completed(futures):
                try:
                    article = fut.result()
                    db.upsert_article(article)
                    if article.body_text:
                        result.new_articles += 1
                except Exception as exc:
                    result.errors.append(str(exc))
                    logger.error("Article extraction error: %s", exc)

    # Embed tweets
    embedder = get_embedder()
    unembedded_tweets = db.get_unembedded_tweets(cfg.embed_model)
    if unembedded_tweets:
        logger.info("Embedding %d tweets", len(unembedded_tweets))
        tweet_recs = embedder.embed_tweets(unembedded_tweets)
        for rec in tweet_recs:
            db.upsert_embedding(rec)
            result.new_embeddings += 1

    # Embed articles
    unembedded_articles = db.get_unembedded_articles(cfg.embed_model)
    if unembedded_articles:
        logger.info("Embedding %d articles", len(unembedded_articles))
        article_recs = embedder.embed_articles(unembedded_articles)
        for rec in article_recs:
            db.upsert_embedding(rec)
            result.new_embeddings += 1

    # Update FTS index
    if new_tweet_ids:
        db.update_fts(new_tweet_ids)

    logger.info(
        "Sync complete: %d tweets, %d articles, %d embeddings",
        result.new_tweets, result.new_articles, result.new_embeddings,
    )
    return result
