"""Publish extracted ideas to Notion via REST API (for Docker / automated use)."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

_BASE = "https://api.notion.com/v1"
_VERSION = "2022-06-28"
_CHUNK = 1900  # Notion rich_text hard limit per element


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

def _rt(text: str) -> list[dict]:
    """Split text into ≤1900-char rich_text elements."""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    return [{"type": "text", "text": {"content": text[i: i + _CHUNK]}}
            for i in range(0, len(text), _CHUNK)]


def _callout(text: str, emoji: str = "💡") -> dict:
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": _rt(text), "icon": {"type": "emoji", "emoji": emoji}}}


def _heading(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rt(text)}}


def _quote(text: str) -> dict:
    return {"object": "block", "type": "quote",
            "quote": {"rich_text": _rt(text[:2000])}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _rt(text)}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


# ---------------------------------------------------------------------------
# Property + block construction
# ---------------------------------------------------------------------------

def _make_properties(
    summary: str,
    author: str,
    category: str,
    tags: list[str],
    relevance: float,
    key_concepts: list[str],
    tweet_id: str,
    tweet_url: str | None,
    article_url: str | None,
    article_title: str | None,
    bookmarked_at: str | None,
    status: str = "New",
) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Name": {"title": _rt(summary[:200])},
        "Author": {"rich_text": _rt(author)},
        "Category": {"select": {"name": category}},
        "Tags": {"multi_select": [{"name": t[:100]} for t in tags[:10]]},
        "Relevance": {"number": round(relevance, 2)},
        "Status": {"select": {"name": status}},
        "Key Concepts": {"rich_text": _rt(", ".join(key_concepts))},
        "Tweet ID": {"rich_text": _rt(tweet_id)},
    }
    if tweet_url:
        props["Tweet URL"] = {"url": tweet_url}
    if article_url:
        props["Article URL"] = {"url": article_url}
    if article_title:
        props["Article Title"] = {"rich_text": _rt(article_title[:200])}
    if bookmarked_at:
        props["Bookmarked"] = {"date": {"start": bookmarked_at[:10]}}
    return props


def _make_blocks(
    summary: str,
    key_concepts: list[str],
    tweet_text: str,
    article_title: str | None = None,
    article_body: str | None = None,
) -> list[dict]:
    blocks: list[dict] = [
        _callout(summary),
        _divider(),
        _heading("Key Concepts"),
        *[_bullet(c) for c in key_concepts],
        _divider(),
        _heading("Original Tweet"),
        _quote(tweet_text),
    ]
    if article_body:
        blocks += [
            _divider(),
            _heading(f"Article{': ' + article_title if article_title else ''}"),
            _paragraph(article_body[:3000]),
        ]
    return blocks


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_settings().notion_api_token}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def find_page_by_tweet_id(tweet_id: str) -> str | None:
    """Query Notion for an existing page matching this tweet ID."""
    cfg = get_settings()
    resp = httpx.post(
        f"{_BASE}/databases/{cfg.notion_database_id}/query",
        headers=_headers(),
        json={"filter": {"property": "Tweet ID", "rich_text": {"equals": tweet_id}},
              "page_size": 1},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


def _create_page(props: dict, blocks: list[dict]) -> str:
    cfg = get_settings()
    resp = httpx.post(
        f"{_BASE}/pages",
        headers=_headers(),
        json={"parent": {"database_id": cfg.notion_database_id},
              "properties": props,
              "children": blocks[:100]},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _update_page(page_id: str, props: dict) -> None:
    resp = httpx.patch(
        f"{_BASE}/pages/{page_id}",
        headers=_headers(),
        json={"properties": props},
        timeout=15,
    )
    resp.raise_for_status()


def _append_reeval_note(page_id: str, new_summary: str) -> None:
    """Append a timestamped re-evaluation note to the page."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks = [
        _divider(),
        _callout(f"Re-evaluated {ts}\n\n{new_summary}", "🔄"),
    ]
    httpx.patch(
        f"{_BASE}/blocks/{page_id}/children",
        headers=_headers(),
        json={"children": blocks},
        timeout=15,
    ).raise_for_status()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def publish_idea(
    tweet_id: str,
    author: str,
    summary: str,
    key_concepts: list[str],
    category: str,
    tags: list[str],
    relevance: float,
    tweet_text: str,
    tweet_url: str | None = None,
    article_title: str | None = None,
    article_body: str | None = None,
    article_url: str | None = None,
    bookmarked_at: str | None = None,
    existing_page_id: str | None = None,
    is_reeval: bool = False,
) -> str:
    """Create or update a Notion page. Returns the Notion page ID."""
    cfg = get_settings()
    if not cfg.notion_api_token or not cfg.notion_database_id:
        raise RuntimeError("NOTION_API_TOKEN and NOTION_DATABASE_ID must be set in .env")

    props = _make_properties(
        summary=summary, author=author, category=category, tags=tags,
        relevance=relevance, key_concepts=key_concepts, tweet_id=tweet_id,
        tweet_url=tweet_url, article_url=article_url, article_title=article_title,
        bookmarked_at=bookmarked_at,
        status="Re-evaluate" if is_reeval else "New",
    )

    page_id = existing_page_id or find_page_by_tweet_id(tweet_id)

    if page_id:
        _update_page(page_id, props)
        if is_reeval:
            _append_reeval_note(page_id, summary)
        logger.debug("Updated Notion page %s for tweet %s", page_id, tweet_id)
    else:
        blocks = _make_blocks(
            summary=summary, key_concepts=key_concepts, tweet_text=tweet_text,
            article_title=article_title, article_body=article_body,
        )
        page_id = _create_page(props, blocks)
        time.sleep(0.35)  # stay under Notion's ~3 req/s limit
        logger.debug("Created Notion page %s for tweet %s", page_id, tweet_id)

    return page_id
