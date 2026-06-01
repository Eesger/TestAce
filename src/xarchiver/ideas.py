"""Extract core ideas from bookmarked content using the Claude API."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic

from .config import get_settings

logger = logging.getLogger(__name__)

_CLIENT: Anthropic | None = None

_SYSTEM = """\
You are an AI research analyst reviewing bookmarked tweets and articles about AI development.
Extract the single most important, reusable insight from each bookmark.

Rules:
- Be concrete: name the specific technique, model, or architectural decision — not just the topic
- Focus on what is novel or actionable for building AI systems
- If the content is too thin to yield a real insight, set relevance_score below 0.3
- Return ONLY valid JSON — no markdown fences, no extra text"""

_PROMPT = """\
Tweet by @{author}:
{tweet_text}

{article_section}

Return JSON only:
{{
  "summary": "2-3 sentences capturing the core insight and why it matters for AI development",
  "key_concepts": ["name each specific technique, model, or concept — be precise"],
  "category": "one of: architecture|training|inference|rag|agents|tooling|evaluation|dataset|research|other",
  "tags": ["3-5 short lowercase tags for cross-referencing ideas"],
  "relevance_score": 0.0
}}"""


@dataclass
class IdeaResult:
    tweet_id: str
    article_id: int | None
    summary: str
    key_concepts: list[str]
    category: str
    tags: list[str]
    relevance_score: float


def _get_client() -> Anthropic:
    global _CLIENT
    if _CLIENT is None:
        cfg = get_settings()
        if not cfg.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env — idea extraction requires it.")
        _CLIENT = Anthropic(api_key=cfg.anthropic_api_key)
    return _CLIENT


def extract_idea(
    tweet_id: str,
    tweet_text: str,
    author: str,
    article_id: int | None = None,
    article_title: str | None = None,
    article_body: str | None = None,
) -> IdeaResult | None:
    if len(tweet_text.strip()) < 20:
        return None

    if article_title or article_body:
        preview = (article_body or "")[:3000]
        article_section = f"Linked article — {article_title or 'untitled'}:\n{preview}"
    else:
        article_section = "(no linked article — analyse the tweet only)"

    prompt = _PROMPT.format(
        author=author,
        tweet_text=tweet_text,
        article_section=article_section,
    )

    try:
        msg = _get_client().messages.create(
            model=get_settings().idea_model,
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        data = json.loads(raw)
        return IdeaResult(
            tweet_id=tweet_id,
            article_id=article_id,
            summary=data.get("summary", ""),
            key_concepts=data.get("key_concepts", []),
            category=data.get("category", "other"),
            tags=data.get("tags", []),
            relevance_score=float(data.get("relevance_score", 0.5)),
        )
    except Exception as exc:
        logger.warning("Idea extraction failed for tweet %s: %s", tweet_id, exc)
        return None
