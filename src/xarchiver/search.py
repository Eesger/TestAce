"""FTS5 keyword search, semantic vector search, and hybrid RRF fusion."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .config import get_settings
from . import db
from .embedder import get_embedder

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    doc_id: str      # "tweet:<id>" or "article:<id>"
    score: float
    title: str
    snippet: str
    author: str
    created_at: str | None = None
    url: str | None = None


def fts_search(query: str, limit: int = 20) -> list[SearchHit]:
    db.init_db()
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT doc_id,
               snippet(search_index, 2, '[', ']', '...', 20) AS snippet,
               title, author,
               rank
        FROM search_index
        WHERE search_index MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()

    hits: list[SearchHit] = []
    for r in rows:
        hit = _enrich(r["doc_id"], r["snippet"], r["title"], r["author"], -r["rank"])
        hits.append(hit)
    return hits


def semantic_search(query: str, limit: int = 20, threshold: float = 0.30) -> list[SearchHit]:
    db.init_db()
    cfg = get_settings()
    embedder = get_embedder()
    qvec = embedder.embed_text(query)

    all_embs = db.get_all_embeddings(cfg.embed_model)
    if not all_embs:
        return []

    source_types = [r[0] for r in all_embs]
    source_ids = [r[1] for r in all_embs]
    matrix = np.array(
        [np.frombuffer(r[2], dtype=np.float32) for r in all_embs]
    )

    scores = matrix @ qvec  # cosine similarity (vectors are pre-normalised)

    top_idx = np.argsort(-scores)[:limit * 3]  # oversample to deduplicate chunks
    seen: dict[str, float] = {}
    for i in top_idx:
        score = float(scores[i])
        if score < threshold:
            break
        key = f"{source_types[i]}:{source_ids[i]}"
        if key not in seen or score > seen[key]:
            seen[key] = score

    ranked = sorted(seen.items(), key=lambda x: -x[1])[:limit]
    hits: list[SearchHit] = []
    for doc_id, score in ranked:
        hit = _enrich(doc_id, "", "", "", score)
        hits.append(hit)
    return hits


def hybrid_search(query: str, limit: int = 20) -> list[SearchHit]:
    """Reciprocal Rank Fusion of FTS and semantic results."""
    k = 60  # RRF constant

    fts_hits = fts_search(query, limit=limit * 2)
    sem_hits = semantic_search(query, limit=limit * 2)

    scores: dict[str, float] = {}
    for rank, hit in enumerate(fts_hits):
        scores[hit.doc_id] = scores.get(hit.doc_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, hit in enumerate(sem_hits):
        scores[hit.doc_id] = scores.get(hit.doc_id, 0.0) + 1.0 / (k + rank + 1)

    # Merge hit metadata (prefer FTS snippets)
    meta: dict[str, SearchHit] = {h.doc_id: h for h in sem_hits}
    meta.update({h.doc_id: h for h in fts_hits})

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]
    result: list[SearchHit] = []
    for doc_id, score in ranked:
        hit = meta.get(doc_id) or _enrich(doc_id, "", "", "", score)
        hit.score = score
        result.append(hit)
    return result


def _enrich(doc_id: str, snippet: str, title: str, author: str, score: float) -> SearchHit:
    created_at = None
    url = None

    if doc_id.startswith("tweet:"):
        tweet_id = doc_id[6:]
        row = db.get_tweet_by_id(tweet_id)
        if row:
            snippet = snippet or row["text"][:200]
            author = author or row["author_username"]
            created_at = row["created_at"]
    elif doc_id.startswith("article:"):
        art_id = doc_id[8:]
        row = db.get_article_by_id(art_id)
        if row:
            title = title or row["title"] or ""
            snippet = snippet or (row["body_text"] or "")[:200]
            author = author or row["author"] or ""
            url = row["url"]

    return SearchHit(
        doc_id=doc_id,
        score=score,
        title=title,
        snippet=snippet,
        author=author,
        created_at=created_at,
        url=url,
    )
