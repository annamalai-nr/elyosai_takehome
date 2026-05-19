"""Pydantic models for LLM turns, weather, and research results."""

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LLM turn models
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class LLMTurn(BaseModel):
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
    temp_c: float
    condition: str
    humidity: float


class NormalisedWeather(BaseModel):
    requested_location: str
    returned_location: str
    observations: list[WeatherObservation]
    note: str | None = None


class ResearchResult(BaseModel):
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
