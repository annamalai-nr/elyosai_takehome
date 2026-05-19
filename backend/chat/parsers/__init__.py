"""Response parsers and untrusted-data JSON envelope."""

import json

from pydantic import BaseModel

from backend.chat.parsers.research import parse_research
from backend.chat.parsers.weather import normalise_weather


def _truncate(s: str, max_len: int = 200) -> str:
    return s if len(s) <= max_len else s[:max_len] + "..."


def envelope(tool_name: str, payload: BaseModel | dict) -> str:
    """Wrap a parsed tool result in an untrusted-data JSON envelope for the LLM."""
    data: dict = payload.model_dump(exclude_none=True) if isinstance(payload, BaseModel) else payload
    for key in ("topic", "summary", "message"):
        if key in data and isinstance(data[key], str):
            data[key] = _truncate(data[key])
    return json.dumps({"source": "elyos_api", "tool": tool_name, "untrusted": True, "data": data})


__all__ = ["envelope", "normalise_weather", "parse_research"]
