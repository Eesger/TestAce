"""Generate sentence embeddings for tweets and articles."""
from __future__ import annotations

import logging
import sqlite3
from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np

from .config import get_settings
from .db import EmbeddingRecord

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_CHUNK_TOKENS = 400  # conservative chunk size in tokens


class Embedder:
    @cached_property
    def model(self) -> "SentenceTransformer":
        from sentence_transformers import SentenceTransformer
        model_name = get_settings().embed_model
        logger.info("Loading embedding model %s ...", model_name)
        return SentenceTransformer(model_name)

    def embed_text(self, text: str) -> np.ndarray:
        vec = self.model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return vec[0].astype(np.float32)

    def embed_tweets(self, rows: list[sqlite3.Row]) -> list[EmbeddingRecord]:
        model_name = get_settings().embed_model
        records: list[EmbeddingRecord] = []
        for row in rows:
            text = f"{row['text']} {' '.join(eval(row['hashtags'] or '[]'))}"
            vec = self.embed_text(text)
            records.append(
                EmbeddingRecord(
                    source_type="tweet",
                    source_id=row["tweet_id"],
                    chunk_index=0,
                    model_name=model_name,
                    embedding=vec.tobytes(),
                    embedding_dim=len(vec),
                )
            )
        return records

    def embed_articles(self, rows: list[sqlite3.Row]) -> list[EmbeddingRecord]:
        model_name = get_settings().embed_model
        records: list[EmbeddingRecord] = []
        for row in rows:
            body = row["body_text"] or ""
            title = row["title"] or ""
            chunks = self._chunk_text(f"{title}\n\n{body}")
            for idx, chunk in enumerate(chunks):
                vec = self.embed_text(chunk)
                records.append(
                    EmbeddingRecord(
                        source_type="article",
                        source_id=str(row["id"]),
                        chunk_index=idx,
                        model_name=model_name,
                        embedding=vec.tobytes(),
                        embedding_dim=len(vec),
                    )
                )
        return records

    def _chunk_text(self, text: str, chunk_size: int = _CHUNK_TOKENS) -> list[str]:
        words = text.split()
        if len(words) <= chunk_size:
            return [text]
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunks.append(" ".join(words[i : i + chunk_size]))
        return chunks


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
