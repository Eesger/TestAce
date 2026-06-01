# X Bookmark Archiver

Automatically syncs your X.com bookmarks, extracts full text from linked articles, stores everything in a local SQLite database, and lets you search it with both keyword (FTS5) and semantic (vector) search.

```
┌─────────────────────────────────────────────────────────┐
│  X.com Bookmarks API  →  xarchiver sync                 │
│        ↓                                                │
│  Tweet text + metadata  →  SQLite (tweets table)        │
│        ↓                                                │
│  Linked URLs  →  trafilatura  →  articles table         │
│        ↓                                                │
│  sentence-transformers  →  embeddings table + FTS5      │
│        ↓                                                │
│  xarchiver search "query"  →  hybrid results            │
└─────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python --version` |
| X Developer App | [developer.twitter.com](https://developer.twitter.com) |
| OAuth 2.0 enabled | Enable in your App settings |
| Scopes | `tweet.read` `users.read` `bookmark.read` `offline.access` |
| Redirect URI | Add `http://127.0.0.1:8080/callback` in the App settings |

---

## Installation

```bash
# Clone and install (editable for development)
pip install -e ".[dev]"

# Copy and fill in your credentials
cp .env.example .env
```

Edit `.env` — only `TWITTER_CLIENT_ID` and `TWITTER_CLIENT_SECRET` are needed before the auth step.

---

## First-time OAuth Setup

```bash
xarchiver auth
```

This will:
1. Open your browser to the X.com authorization page
2. Listen on `localhost:8080` for the callback
3. Exchange the code for tokens and write them to `.env`
4. Fetch and store your numeric user ID automatically

---

## Usage

### Sync bookmarks
```bash
xarchiver sync           # incremental — only fetches new bookmarks
xarchiver sync --full    # re-pages through all bookmarks
```

### Search your knowledge base
```bash
xarchiver search "attention mechanism transformers"
xarchiver search "RAG retrieval augmented generation" --mode semantic
xarchiver search "LLM fine-tuning" --mode fts --limit 5
```

**Search modes:**
- `hybrid` *(default)* — combines keyword and semantic results via Reciprocal Rank Fusion
- `fts` — SQLite FTS5 with Porter stemmer; best for exact terms
- `semantic` — cosine similarity on sentence embeddings; best for conceptual queries

### Database statistics
```bash
xarchiver stats
```

---

## Automated sync

### Docker Compose (recommended)
```bash
docker compose up -d
```

The scheduler starts immediately and re-runs every `SYNC_INTERVAL_MINUTES` (default 60).

### Cron (native)
```cron
0 * * * * cd /path/to/x-bookmark-archiver && xarchiver sync >> ~/.xarchiver.log 2>&1
```

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TWITTER_CLIENT_ID` | — | OAuth 2.0 App client ID |
| `TWITTER_CLIENT_SECRET` | — | OAuth 2.0 App client secret |
| `TWITTER_ACCESS_TOKEN` | *(auto)* | Set by `xarchiver auth` |
| `TWITTER_REFRESH_TOKEN` | *(auto)* | Set by `xarchiver auth` |
| `TWITTER_TOKEN_EXPIRES_AT` | *(auto)* | Unix timestamp |
| `TWITTER_USER_ID` | *(auto)* | Numeric X user ID |
| `DB_PATH` | `./data/bookmarks.db` | SQLite file location |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | Any `sentence-transformers` model |
| `SYNC_INTERVAL_MINUTES` | `60` | Scheduler interval |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Database Schema

```
tweets          — full tweet text, author, hashtags, media URLs, raw JSON
articles        — extracted article body, title, author, publish date
embeddings      — float32 vectors (BLOB), one row per tweet or article chunk
sync_state      — pagination cursor per user for incremental syncs
search_index    — FTS5 virtual table (Porter stemmer)
```

---

## Extending

**Swap the embedding model** — change `EMBED_MODEL` in `.env`. On next `sync`, new embeddings are generated alongside the old ones (keyed by model name). Delete old rows manually if you want to reclaim space:
```sql
DELETE FROM embeddings WHERE model_name != 'new-model-name';
```

**Scale beyond ~100k items** — swap the cosine-similarity loop in `search.py` for [`sqlite-vec`](https://github.com/asg017/sqlite-vec), a SQLite extension for approximate nearest-neighbour search. The schema `embeddings` table is already compatible.

**Add a web UI** — the `search.py` functions return plain `SearchHit` dataclasses and can be called directly from any web framework (FastAPI, Flask, etc.).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No access token` | Run `xarchiver auth` |
| `401 Unauthorized` on sync | Token expired or revoked — run `xarchiver auth` again |
| `429 Too Many Requests` | Built-in backoff handles this; wait and retry |
| Articles have no text | trafilatura couldn't extract — paywalled or JS-rendered pages are common failures |
| Empty semantic results | Lower `--threshold` in `search.py` or run `xarchiver sync` to build embeddings first |
