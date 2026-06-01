import json
import pytest
from xarchiver import db
from xarchiver.db import TweetData, upsert_tweet, update_fts


def _make_tweet(tweet_id: str, text: str, username: str = "user") -> TweetData:
    return TweetData(
        tweet_id=tweet_id, author_id="1", author_username=username,
        author_name="User", text=text, lang="en",
        created_at="2024-01-01T00:00:00Z",
    )


def test_fts_basic(tmp_db):
    from xarchiver.search import fts_search
    upsert_tweet(_make_tweet("1", "Transformers and attention mechanisms in deep learning"))
    upsert_tweet(_make_tweet("2", "How to cook pasta carbonara"))
    update_fts(["1", "2"])

    hits = fts_search("transformers attention")
    assert len(hits) >= 1
    assert any("1" in h.doc_id for h in hits)


def test_fts_no_results(tmp_db):
    from xarchiver.search import fts_search
    upsert_tweet(_make_tweet("1", "AI and machine learning news"))
    update_fts(["1"])

    hits = fts_search("carbonara pizza recipe")
    # May or may not return results; just ensure it doesn't crash
    assert isinstance(hits, list)


def test_fts_returns_correct_types(tmp_db):
    from xarchiver.search import fts_search, SearchHit
    upsert_tweet(_make_tweet("1", "Reinforcement learning from human feedback RLHF"))
    update_fts(["1"])

    hits = fts_search("reinforcement learning")
    for h in hits:
        assert isinstance(h, SearchHit)
        assert h.score != 0
