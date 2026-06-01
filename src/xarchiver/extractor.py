"""Fetch URLs and extract article text via trafilatura."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
import trafilatura
from trafilatura.settings import use_config

from .db import ArticleData

logger = logging.getLogger(__name__)

_trafilatura_config = use_config()
_trafilatura_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_article(tweet_id: str, url: str) -> ArticleData:
    """Fetch `url` and return an ArticleData with extracted text (or error info)."""
    try:
        resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=15)
        fetch_status = resp.status_code
        if resp.status_code != 200:
            return ArticleData(
                tweet_id=tweet_id,
                url=url,
                fetch_status=fetch_status,
                fetch_error=f"HTTP {fetch_status}",
            )
        html = resp.text
        canonical = str(resp.url)
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return ArticleData(
            tweet_id=tweet_id,
            url=url,
            fetch_status=0,
            fetch_error=str(exc),
        )

    try:
        metadata = trafilatura.extract_metadata(filecontent=html, default_url=canonical)
        body = trafilatura.extract(
            html,
            url=canonical,
            include_comments=False,
            include_tables=True,
            output_format="txt",
            config=_trafilatura_config,
        )
    except Exception as exc:
        logger.warning("Trafilatura failed for %s: %s", url, exc)
        return ArticleData(
            tweet_id=tweet_id,
            url=url,
            canonical_url=canonical,
            fetch_status=200,
            fetch_error=f"extraction error: {exc}",
        )

    return ArticleData(
        tweet_id=tweet_id,
        url=url,
        canonical_url=canonical,
        title=metadata.title if metadata else None,
        author=metadata.author if metadata else None,
        publish_date=str(metadata.date) if metadata and metadata.date else None,
        body_text=body,
        fetch_status=200,
    )
