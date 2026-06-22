"""Read bookmarks from a local Birdclaw SQLite database."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from .db import TweetData

logger = logging.getLogger(__name__)

# Possible paths where Birdclaw stores its data
_BIRDCLAW_CANDIDATES = [
    Path.home() / ".birdclaw",
    Path(os.environ.get("BIRDCLAW_HOME", "~/.birdclaw")).expanduser(),
]


def find_birdclaw_home() -> Path | None:
    for p in _BIRDCLAW_CANDIDATES:
        if p.exists():
            return p
    return None


def inspect_schema(db_path: Path) -> dict[str, list[str]]:
    """Return {table: [columns]} so we can adapt to schema changes."""
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    schema: dict[str, list[str]] = {}
    for (name,) in tables:
        cols = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
        schema[name] = [c[1] for c in cols]
    conn.close()
    return schema


def find_db(birdclaw_home: Path) -> Path | None:
    for candidate in [
        birdclaw_home / "db.sqlite",
        birdclaw_home / "birdclaw.db",
        birdclaw_home / "data" / "db.sqlite",
        birdclaw_home / "data" / "birdclaw.db",
    ]:
        if candidate.exists():
            return candidate
    # Recursive search one level deep
    for p in birdclaw_home.glob("*.sqlite"):
        return p
    for p in birdclaw_home.glob("**/*.sqlite"):
        return p
    return None


def _parse_tweet_row(row: sqlite3.Row, schema_cols: list[str]) -> TweetData | None:
    """Map a Birdclaw tweet row to our TweetData — handles schema variations."""
    def get(*keys: str, default: str = "") -> str:
        for k in keys:
            if k in schema_cols:
                v = row[k]
                if v is not None:
                    return str(v)
        return default

    tweet_id = get("id", "tweet_id", "id_str")
    if not tweet_id:
        return None

    text = get("full_text", "text", "content")
    author_username = get("author_username", "screen_name", "username", "author_screen_name")
    author_name = get("author_name", "name", "display_name")
    author_id = get("author_id", "user_id")
    created_at = get("created_at", "timestamp", "created")
    lang = get("lang", "language", default="")

    # Try to parse JSON fields
    urls: list[dict] = []
    hashtags: list[str] = []
    raw: dict = {}

    for col in ("entities", "raw", "raw_json", "data"):
        if col in schema_cols and row[col]:
            try:
                raw = json.loads(row[col]) if isinstance(row[col], str) else {}
                ents = raw.get("entities", {})
                urls = [
                    {"url": u.get("url", ""), "expanded_url": u.get("expanded_url", ""), "title": u.get("title", "")}
                    for u in ents.get("urls", [])
                ]
                hashtags = [h.get("tag", h.get("text", "")) for h in ents.get("hashtags", [])]
            except Exception:
                pass
            break

    return TweetData(
        tweet_id=tweet_id,
        author_id=author_id or tweet_id,
        author_username=author_username or "unknown",
        author_name=author_name or author_username or "unknown",
        text=text,
        lang=lang or None,
        created_at=created_at,
        hashtags=hashtags,
        urls=urls,
        raw_json=raw,
    )


def _read_from_sqlite(db_path: Path, known_ids: set[str]) -> list[TweetData]:
    """Read bookmarks from Birdclaw SQLite, adapting to whatever schema is present."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    schema = inspect_schema(db_path)

    logger.debug("Birdclaw tables: %s", list(schema.keys()))

    results: list[TweetData] = []

    # Strategy 1: look for a bookmarks table or view
    bookmark_tables = [t for t in schema if "bookmark" in t.lower()]
    tweet_tables = [t for t in schema if "tweet" in t.lower()]

    if bookmark_tables:
        # Direct bookmark table — may already have tweet data joined
        table = bookmark_tables[0]
        cols = schema[table]
        rows = conn.execute(f"SELECT * FROM '{table}'").fetchall()
        for row in rows:
            tweet = _parse_tweet_row(row, cols)
            if tweet and tweet.tweet_id not in known_ids:
                results.append(tweet)

    elif tweet_tables:
        # No bookmark table — look for a bookmark flag or join with collections
        t_table = tweet_tables[0]
        t_cols = schema[t_table]

        # Check for is_bookmarked / bookmarked flag
        bookmark_col = next((c for c in t_cols if "bookmark" in c.lower()), None)
        if bookmark_col:
            rows = conn.execute(
                f"SELECT * FROM '{t_table}' WHERE {bookmark_col}=1 OR {bookmark_col}='true'"
            ).fetchall()
        else:
            # Try joining with a collections table
            coll_tables = [t for t in schema if "collection" in t.lower() or "edge" in t.lower()]
            if coll_tables:
                c_table = coll_tables[0]
                c_cols = schema[c_table]
                id_col = next((c for c in c_cols if "tweet" in c.lower() or c == "id"), "tweet_id")
                try:
                    rows = conn.execute(
                        f"""
                        SELECT t.* FROM '{t_table}' t
                        JOIN '{c_table}' c ON c.{id_col} = t.id
                        WHERE LOWER(c.type) LIKE '%bookmark%'
                           OR LOWER(c.collection) LIKE '%bookmark%'
                        """
                    ).fetchall()
                except Exception:
                    rows = []
            else:
                logger.warning("Could not identify bookmark query in Birdclaw schema. "
                               "Run `xarchiver inspect-birdclaw` for details.")
                rows = []

        for row in rows:
            tweet = _parse_tweet_row(row, t_cols)
            if tweet and tweet.tweet_id not in known_ids:
                results.append(tweet)

    conn.close()
    return results


def _read_from_jsonl(jsonl_path: Path, known_ids: set[str]) -> list[TweetData]:
    """Read from Birdclaw's bookmarks.jsonl export."""
    results: list[TweetData] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Handle wrapper objects (audit entries vs tweet objects)
            tweet_obj = obj.get("tweet", obj.get("data", obj))
            tweet_id = str(tweet_obj.get("id", tweet_obj.get("id_str", tweet_obj.get("tweet_id", ""))))
            if not tweet_id or tweet_id in known_ids:
                continue

            user = tweet_obj.get("user", tweet_obj.get("author", {}))
            entities = tweet_obj.get("entities", {})
            urls = [
                {"url": u.get("url", ""), "expanded_url": u.get("expanded_url", ""), "title": u.get("title", "")}
                for u in entities.get("urls", [])
            ]
            hashtags = [h.get("tag", h.get("text", "")) for h in entities.get("hashtags", [])]

            results.append(TweetData(
                tweet_id=tweet_id,
                author_id=str(user.get("id", user.get("id_str", tweet_id))),
                author_username=user.get("screen_name", user.get("username", "unknown")),
                author_name=user.get("name", "unknown"),
                text=tweet_obj.get("full_text", tweet_obj.get("text", "")),
                lang=tweet_obj.get("lang"),
                created_at=tweet_obj.get("created_at", ""),
                hashtags=hashtags,
                urls=urls,
                raw_json=tweet_obj,
            ))
    return results


def read_bookmarks(birdclaw_home: str | None, known_ids: set[str]) -> list[TweetData]:
    """
    Read new bookmarks from Birdclaw. Returns only items not in known_ids.
    Tries JSONL first (cleaner), then SQLite.
    """
    home = Path(birdclaw_home).expanduser() if birdclaw_home else find_birdclaw_home()
    if not home or not home.exists():
        raise RuntimeError(
            f"Birdclaw home not found. Set BIRDCLAW_HOME in .env or run `birdclaw init`.\n"
            f"Searched: {[str(p) for p in _BIRDCLAW_CANDIDATES]}"
        )

    logger.info("Reading bookmarks from Birdclaw at %s", home)

    # Try JSONL first
    for jsonl_path in [
        home / "data" / "collections" / "bookmarks.jsonl",
        home / "collections" / "bookmarks.jsonl",
        home / "bookmarks.jsonl",
        *home.glob("**/*bookmarks*.jsonl"),
    ]:
        if jsonl_path.exists():
            logger.info("Reading from JSONL: %s", jsonl_path)
            return _read_from_jsonl(jsonl_path, known_ids)

    # Fall back to SQLite
    db_path = find_db(home)
    if not db_path:
        raise RuntimeError(
            f"No Birdclaw database found in {home}. "
            "Run `birdclaw init` and `birdclaw jobs sync-bookmarks` first."
        )

    logger.info("Reading from SQLite: %s", db_path)
    return _read_from_sqlite(db_path, known_ids)


def print_schema_report(birdclaw_home: str | None = None) -> None:
    """Print a diagnostic report of the Birdclaw database structure."""
    home = Path(birdclaw_home).expanduser() if birdclaw_home else find_birdclaw_home()
    if not home:
        print("Birdclaw home not found.")
        return

    print(f"\nBirdclaw home: {home}")

    # Check JSONL files
    jsonl_files = list(home.glob("**/*.jsonl"))
    print(f"\nJSONL files found ({len(jsonl_files)}):")
    for f in jsonl_files:
        size = f.stat().st_size
        print(f"  {f}  ({size:,} bytes)")

    db_path = find_db(home)
    if not db_path:
        print("\nNo SQLite database found.")
        return

    print(f"\nSQLite database: {db_path}")
    schema = inspect_schema(db_path)
    print(f"Tables ({len(schema)}):")
    for table, cols in schema.items():
        conn = sqlite3.connect(db_path)
        count = conn.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
        conn.close()
        print(f"  {table} ({count:,} rows): {', '.join(cols[:8])}{'...' if len(cols) > 8 else ''}")
