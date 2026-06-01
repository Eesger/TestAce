"""Twitter API v2 bookmarks client."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .auth import get_bearer_header
from .config import get_settings
from .db import TweetData

logger = logging.getLogger(__name__)

BOOKMARKS_URL = "https://api.twitter.com/2/users/{user_id}/bookmarks"

# URL patterns to skip article extraction (not real article pages)
_SKIP_ARTICLE_DOMAINS = {
    "twitter.com", "x.com", "t.co",
    "youtube.com", "youtu.be",
    "pbs.twimg.com", "pic.twitter.com",
    "instagram.com", "tiktok.com",
}


@dataclass
class FetchResult:
    tweets: list[TweetData]
    next_token: str | None


def fetch_bookmarks(user_id: str, next_token: str | None = None) -> FetchResult:
    """Fetch one page of bookmarks (max 100)."""
    params: dict[str, str] = {
        "max_results": "100",
        "expansions": "author_id,attachments.media_keys",
        "tweet.fields": "text,created_at,entities,lang,attachments",
        "user.fields": "username,name",
        "media.fields": "url,preview_image_url,type",
    }
    if next_token:
        params["pagination_token"] = next_token

    url = BOOKMARKS_URL.format(user_id=user_id)
    data = _request_with_backoff(url, params)

    tweets = _parse_response(data)
    meta = data.get("meta", {})
    return FetchResult(tweets=tweets, next_token=meta.get("next_token"))


def _request_with_backoff(url: str, params: dict[str, str]) -> dict[str, Any]:
    headers = get_bearer_header()
    delay = 2
    for attempt in range(4):
        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 429:
                reset = int(resp.headers.get("x-rate-limit-reset", time.time() + 60))
                wait = max(reset - time.time(), delay)
                logger.warning("Rate limited; waiting %.0fs", wait)
                time.sleep(wait)
                delay *= 2
                headers = get_bearer_header()  # may have refreshed
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if attempt == 3:
                raise
            logger.warning("HTTP %d on attempt %d; retrying in %ds", exc.response.status_code, attempt + 1, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("All retry attempts exhausted")


def _parse_response(data: dict[str, Any]) -> list[TweetData]:
    tweets_raw = data.get("data", [])
    if not tweets_raw:
        return []

    includes = data.get("includes", {})
    users_by_id: dict[str, dict] = {u["id"]: u for u in includes.get("users", [])}
    media_by_key: dict[str, dict] = {m["media_key"]: m for m in includes.get("media", [])}

    results: list[TweetData] = []
    for t in tweets_raw:
        author = users_by_id.get(t.get("author_id", ""), {})
        entities = t.get("entities", {})

        hashtags = [h["tag"] for h in entities.get("hashtags", [])]
        urls = [
            {
                "url": u.get("url", ""),
                "expanded_url": u.get("expanded_url", ""),
                "title": u.get("title", ""),
            }
            for u in entities.get("urls", [])
            if not _is_twitter_media_url(u.get("expanded_url", ""))
        ]

        attachments = t.get("attachments", {})
        mk_list = attachments.get("media_keys", [])
        media_urls = []
        for mk in mk_list:
            m = media_by_key.get(mk, {})
            url_val = m.get("url") or m.get("preview_image_url") or ""
            if url_val:
                media_urls.append(url_val)

        results.append(
            TweetData(
                tweet_id=t["id"],
                author_id=t.get("author_id", ""),
                author_username=author.get("username", "unknown"),
                author_name=author.get("name", ""),
                text=t.get("text", ""),
                lang=t.get("lang"),
                created_at=t.get("created_at", ""),
                hashtags=hashtags,
                media_keys=mk_list,
                media_urls=media_urls,
                urls=urls,
                raw_json=t,
            )
        )
    return results


def _is_twitter_media_url(url: str) -> bool:
    if not url:
        return True
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lstrip("www.")
    return any(url.startswith("https://pbs.twimg") or domain == d for d in _SKIP_ARTICLE_DOMAINS)


def should_extract_article(url: str) -> bool:
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lstrip("www.")
    return not any(domain == d or domain.endswith("." + d) for d in _SKIP_ARTICLE_DOMAINS)
