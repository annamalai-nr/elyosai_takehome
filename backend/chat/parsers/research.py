"""/research response parsing (fresh, cached, truncated, timeout)."""

import logging
from typing import Any

from backend.chat.models import ResearchResult

log = logging.getLogger(__name__)


def _humanize_seconds(seconds: int) -> str:
    days = max(seconds // 86400, 1)
    return f"~{days} day{'s' if days != 1 else ''}"


def parse_research(data: dict) -> ResearchResult | dict:
    """Parse a /research response into ResearchResult, or pass through error dicts."""
    if "error" in data:
        return data
    if not data:
        log.warning("Research returned empty response (timeout)")
        return ResearchResult(kind="timeout", message="Research timed out. Try a more specific topic or try again.")

    kind: str = "fresh"
    kwargs: dict[str, Any] = {
        "topic": data.get("topic", ""),
        "summary": data.get("summary", ""),
        "sources": data.get("sources", []),
    }

    if data.get("generated_at"):
        kwargs["generated_at"] = data["generated_at"]

    if data.get("cached"):
        kind = "cached"
        raw_age = data.get("cache_age_seconds")
        if raw_age is not None:
            age = int(raw_age)
            kwargs["cache_age_seconds"] = age
            kwargs["cache_age"] = _humanize_seconds(age)
    if data.get("truncated"):
        kind = "truncated"
        kwargs["processed_topic"] = data.get("processed_topic", "")
        kwargs["original_topic_length"] = data.get("original_topic_length")

    return ResearchResult(kind=kind, **kwargs)
