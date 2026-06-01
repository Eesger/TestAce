from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)

_local = threading.local()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        cfg = get_settings()
        os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
        conn = sqlite3.connect(cfg.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


DDL = """
CREATE TABLE IF NOT EXISTS tweets (
    tweet_id        TEXT PRIMARY KEY,
    author_id       TEXT NOT NULL,
    author_username TEXT NOT NULL,
    author_name     TEXT NOT NULL,
    text            TEXT NOT NULL,
    lang            TEXT,
    created_at      TEXT NOT NULL,
    bookmarked_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    hashtags        TEXT,
    media_keys      TEXT,
    media_urls      TEXT,
    urls            TEXT,
    raw_json        TEXT NOT NULL,
    synced_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id        TEXT NOT NULL REFERENCES tweets(tweet_id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    canonical_url   TEXT,
    title           TEXT,
    author          TEXT,
    publish_date    TEXT,
    body_text       TEXT,
    fetch_status    INTEGER NOT NULL DEFAULT 0,
    fetch_error     TEXT,
    fetched_at      TEXT,
    UNIQUE(tweet_id, url)
);

CREATE TABLE IF NOT EXISTS embeddings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type     TEXT NOT NULL CHECK(source_type IN ('tweet','article')),
    source_id       TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    model_name      TEXT NOT NULL,
    embedding       BLOB NOT NULL,
    embedding_dim   INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(source_type, source_id, chunk_index, model_name)
);

CREATE TABLE IF NOT EXISTS sync_state (
    user_id         TEXT PRIMARY KEY,
    next_token      TEXT,
    last_sync_at    TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    doc_id,
    title,
    body,
    author,
    hashtags,
    tokenize = 'porter unicode61'
);
"""


def init_db() -> None:
    conn = get_conn()
    for statement in DDL.split(";"):
        s = statement.strip()
        if s:
            conn.execute(s)
    conn.commit()
    logger.debug("Database initialised at %s", get_settings().db_path)


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

@dataclass
class TweetData:
    tweet_id: str
    author_id: str
    author_username: str
    author_name: str
    text: str
    lang: str | None
    created_at: str
    hashtags: list[str] = field(default_factory=list)
    media_keys: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    urls: list[dict[str, str]] = field(default_factory=list)
    raw_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArticleData:
    tweet_id: str
    url: str
    canonical_url: str | None = None
    title: str | None = None
    author: str | None = None
    publish_date: str | None = None
    body_text: str | None = None
    fetch_status: int = 0
    fetch_error: str | None = None


@dataclass
class EmbeddingRecord:
    source_type: str  # 'tweet' or 'article'
    source_id: str
    chunk_index: int
    model_name: str
    embedding: bytes   # float32 tobytes()
    embedding_dim: int


def upsert_tweet(tweet: TweetData) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO tweets
            (tweet_id, author_id, author_username, author_name, text, lang,
             created_at, hashtags, media_keys, media_urls, urls, raw_json, synced_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(tweet_id) DO UPDATE SET
            author_username = excluded.author_username,
            author_name     = excluded.author_name,
            text            = excluded.text,
            synced_at       = excluded.synced_at
        """,
        (
            tweet.tweet_id, tweet.author_id, tweet.author_username, tweet.author_name,
            tweet.text, tweet.lang, tweet.created_at,
            json.dumps(tweet.hashtags), json.dumps(tweet.media_keys),
            json.dumps(tweet.media_urls), json.dumps(tweet.urls),
            json.dumps(tweet.raw_json), _now_iso(),
        ),
    )
    conn.commit()


def upsert_article(article: ArticleData) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO articles
            (tweet_id, url, canonical_url, title, author, publish_date,
             body_text, fetch_status, fetch_error, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(tweet_id, url) DO UPDATE SET
            canonical_url = excluded.canonical_url,
            title         = excluded.title,
            author        = excluded.author,
            publish_date  = excluded.publish_date,
            body_text     = excluded.body_text,
            fetch_status  = excluded.fetch_status,
            fetch_error   = excluded.fetch_error,
            fetched_at    = excluded.fetched_at
        """,
        (
            article.tweet_id, article.url, article.canonical_url,
            article.title, article.author, article.publish_date,
            article.body_text, article.fetch_status, article.fetch_error,
            _now_iso() if article.fetch_status != 0 else None,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM articles WHERE tweet_id=? AND url=?", (article.tweet_id, article.url)
    ).fetchone()
    return row["id"]


def upsert_embedding(rec: EmbeddingRecord) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO embeddings
            (source_type, source_id, chunk_index, model_name, embedding, embedding_dim)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(source_type, source_id, chunk_index, model_name)
        DO UPDATE SET embedding=excluded.embedding
        """,
        (rec.source_type, rec.source_id, rec.chunk_index, rec.model_name,
         rec.embedding, rec.embedding_dim),
    )
    conn.commit()


def tweet_exists(tweet_id: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM tweets WHERE tweet_id=?", (tweet_id,)).fetchone()
    return row is not None


def get_unembedded_tweets(model_name: str) -> list[sqlite3.Row]:
    conn = get_conn()
    return conn.execute(
        """
        SELECT t.tweet_id, t.text, t.author_username, t.hashtags
        FROM tweets t
        WHERE NOT EXISTS (
            SELECT 1 FROM embeddings e
            WHERE e.source_type='tweet' AND e.source_id=t.tweet_id AND e.model_name=?
        )
        """,
        (model_name,),
    ).fetchall()


def get_unarticled_urls() -> list[sqlite3.Row]:
    conn = get_conn()
    return conn.execute(
        """
        SELECT tweet_id, url FROM articles
        WHERE fetch_status=0
        """
    ).fetchall()


def get_unembedded_articles(model_name: str) -> list[sqlite3.Row]:
    conn = get_conn()
    return conn.execute(
        """
        SELECT a.id, a.tweet_id, a.title, a.body_text, a.author
        FROM articles a
        WHERE a.body_text IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM embeddings e
              WHERE e.source_type='article' AND e.source_id=CAST(a.id AS TEXT)
                AND e.model_name=?
          )
        """,
        (model_name,),
    ).fetchall()


def update_fts(tweet_ids: list[str]) -> None:
    if not tweet_ids:
        return
    conn = get_conn()
    for tweet_id in tweet_ids:
        row = conn.execute(
            "SELECT tweet_id, text, author_username, hashtags FROM tweets WHERE tweet_id=?",
            (tweet_id,),
        ).fetchone()
        if not row:
            continue
        doc_id = f"tweet:{tweet_id}"
        hashtags_text = " ".join(json.loads(row["hashtags"] or "[]"))
        conn.execute("DELETE FROM search_index WHERE doc_id=?", (doc_id,))
        conn.execute(
            "INSERT INTO search_index(doc_id, title, body, author, hashtags) VALUES (?,?,?,?,?)",
            (doc_id, "", row["text"], row["author_username"], hashtags_text),
        )

        articles = conn.execute(
            "SELECT id, title, body_text, author FROM articles WHERE tweet_id=? AND body_text IS NOT NULL",
            (tweet_id,),
        ).fetchall()
        for art in articles:
            adoc_id = f"article:{art['id']}"
            conn.execute("DELETE FROM search_index WHERE doc_id=?", (adoc_id,))
            conn.execute(
                "INSERT INTO search_index(doc_id, title, body, author, hashtags) VALUES (?,?,?,?,?)",
                (adoc_id, art["title"] or "", art["body_text"] or "", art["author"] or "", ""),
            )
    conn.commit()


def get_sync_state(user_id: str) -> tuple[str | None, str | None]:
    conn = get_conn()
    row = conn.execute(
        "SELECT next_token, last_sync_at FROM sync_state WHERE user_id=?", (user_id,)
    ).fetchone()
    if row:
        return row["next_token"], row["last_sync_at"]
    return None, None


def set_sync_state(user_id: str, next_token: str | None) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO sync_state(user_id, next_token, last_sync_at)
        VALUES (?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET next_token=excluded.next_token, last_sync_at=excluded.last_sync_at
        """,
        (user_id, next_token, _now_iso()),
    )
    conn.commit()


def get_stats() -> dict[str, Any]:
    conn = get_conn()
    tweets = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
    articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    articles_with_text = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE body_text IS NOT NULL"
    ).fetchone()[0]
    embeddings = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    last_sync = conn.execute(
        "SELECT MAX(last_sync_at) FROM sync_state"
    ).fetchone()[0]
    db_path = get_settings().db_path
    db_size_mb = os.path.getsize(db_path) / 1024 / 1024 if os.path.exists(db_path) else 0
    return {
        "tweets": tweets,
        "articles": articles,
        "articles_with_text": articles_with_text,
        "embeddings": embeddings,
        "last_sync": last_sync or "never",
        "db_size_mb": round(db_size_mb, 2),
    }


def get_all_embeddings(model_name: str, batch_size: int = 1000) -> list[tuple[str, str, bytes]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT source_type, source_id, embedding FROM embeddings WHERE model_name=?",
        (model_name,),
    ).fetchall()
    return [(r["source_type"], r["source_id"], r["embedding"]) for r in rows]


def get_tweet_by_id(tweet_id: str) -> sqlite3.Row | None:
    return get_conn().execute("SELECT * FROM tweets WHERE tweet_id=?", (tweet_id,)).fetchone()


def get_article_by_id(article_id: str) -> sqlite3.Row | None:
    return get_conn().execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
