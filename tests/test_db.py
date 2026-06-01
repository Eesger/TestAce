from xarchiver.db import TweetData, ArticleData, upsert_tweet, upsert_article, tweet_exists, get_stats


def _sample_tweet(tweet_id="1") -> TweetData:
    return TweetData(
        tweet_id=tweet_id,
        author_id="42",
        author_username="testuser",
        author_name="Test User",
        text="This is a test tweet about AI #LLM",
        lang="en",
        created_at="2024-01-15T10:00:00Z",
        hashtags=["LLM"],
        urls=[{"url": "https://t.co/x", "expanded_url": "https://example.com/article", "title": "Test"}],
    )


def test_upsert_and_exists(tmp_db):
    tweet = _sample_tweet()
    assert not tweet_exists(tweet.tweet_id)
    upsert_tweet(tweet)
    assert tweet_exists(tweet.tweet_id)


def test_upsert_idempotent(tmp_db):
    tweet = _sample_tweet()
    upsert_tweet(tweet)
    upsert_tweet(tweet)  # second upsert should not raise
    stats = get_stats()
    assert stats["tweets"] == 1


def test_article_upsert(tmp_db):
    tweet = _sample_tweet()
    upsert_tweet(tweet)
    art = ArticleData(
        tweet_id=tweet.tweet_id,
        url="https://example.com/article",
        title="Test Article",
        body_text="Full article text here.",
        fetch_status=200,
    )
    art_id = upsert_article(art)
    assert art_id > 0
    stats = get_stats()
    assert stats["articles"] == 1
    assert stats["articles_with_text"] == 1


def test_stats_empty(tmp_db):
    stats = get_stats()
    assert stats["tweets"] == 0
    assert stats["embeddings"] == 0
    assert stats["last_sync"] == "never"
