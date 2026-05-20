"""Pydantic models and shared type aliases for the chat package."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


# Async callback used to forward events to the WebSocket UI.
# CLI mode passes emit=None; functions that accept emit fall back to
# printing user-facing status to stdout when it is None.
Emit = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# LLM turn models
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """One LLM-requested tool call. `arguments` arrives as a raw JSON string."""

    id: str
    name: str
    arguments: str


class LLMTurn(BaseModel):
    """Result of one streamed LLM completion: text content plus any tool calls."""

    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @property
    def assistant_message(self) -> dict:
        if not self.tool_calls:
            return {"role": "assistant", "content": self.content}

        return {
            "role": "assistant",
            "content": self.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in self.tool_calls
            ],
        }


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class WeatherObservation(BaseModel):
    """One reading: temperature, condition, and humidity."""

    temp_c: float
    condition: str
    humidity: float


class NormalisedWeather(BaseModel):
    """Weather payload with the user's requested location and what the API resolved to.

    `observations` is a list because the API sometimes returns multiple
    conflicting readings for the same city (Shape B). The parser surfaces
    them individually rather than collapsing into a single value.
    """

    requested_location: str
    returned_location: str
    observations: list[WeatherObservation]
    note: str | None = Field(
        default=None,
        description="Free-text note the API attaches to multi-observation responses.",
    )


class ResearchResult(BaseModel):
    """Parsed /research response.

    `kind` distinguishes four states:
    - "fresh"     — normal current response with `summary` + `sources`.
    - "cached"    — server returned cached data; `cache_age_seconds` /
                    `cache_age` / `generated_at` describe staleness.
    - "truncated" — server shortened the topic; `processed_topic` is what
                    it actually used and `original_topic_length` records
                    the truncation point.
    - "timeout"   — empty `{}` response from the server; `message` holds a
                    user-facing suggestion to retry.
    """

    kind: Literal["fresh", "cached", "truncated", "timeout"]
    topic: str = ""
    summary: str = ""
    sources: list[Any] = []
    generated_at: str | None = None
    cache_age_seconds: int | None = None
    cache_age: str | None = None
    processed_topic: str | None = None
    original_topic_length: int | None = None
    message: str | None = None
