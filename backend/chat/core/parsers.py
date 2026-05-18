import json
from typing import Any

from pydantic import BaseModel

from backend.chat.core.models import NormalisedWeather, ResearchResult, WeatherObservation


def _parse_observation(raw: dict) -> WeatherObservation:
    return WeatherObservation(temp_c=raw["temperature_c"], condition=raw["condition"], humidity=raw["humidity"])


def normalise_weather(data: dict, requested_location: str) -> NormalisedWeather | dict:
    """Parse raw weather API response into a NormalisedWeather or an error dict."""
    if "error" in data:
        return data

    returned_location = data.get("location", requested_location)

    if "temperature_c" in data:
        observations = [_parse_observation(data)]
    elif "conditions" in data:
        observations = [_parse_observation(o) for o in data["conditions"]]
    else:
        return {"error": "unknown_schema", "message": f"Unrecognised weather shape: {list(data.keys())}"}

    return NormalisedWeather(
        requested_location=requested_location,
        returned_location=returned_location,
        observations=observations,
        note=data.get("note"),
    )


def parse_research(data: dict) -> ResearchResult | dict:
    """Parse raw research API response into a ResearchResult or an error dict."""
    if "error" in data:
        return data
    if not data:
        return ResearchResult(kind="timeout", message="Research timed out. Try a more specific topic or try again.")

    kind: str = "fresh"
    kwargs: dict[str, Any] = {
        "topic": data.get("topic", ""),
        "summary": data.get("summary", ""),
        "sources": data.get("sources", []),
    }

    if data.get("cached"):
        kind = "cached"
        kwargs["cache_age_seconds"] = data.get("cache_age_seconds")
        kwargs["stale_warning"] = "This data is from early 2024 and may not reflect recent developments."
    if data.get("truncated"):
        kind = "truncated"
        kwargs["processed_topic"] = data.get("processed_topic", "")
        kwargs["original_topic_length"] = data.get("original_topic_length")

    return ResearchResult(kind=kind, **kwargs)


def truncate(s: str, max_len: int = 200) -> str:
    """Truncate a string to max_len, appending '...' if shortened."""
    return s if len(s) <= max_len else s[:max_len] + "..."


def envelope(tool_name: str, payload: BaseModel | dict) -> str:
    """Wrap tool output in a JSON envelope marking data as untrusted."""
    data: dict = payload.model_dump(exclude_none=True) if isinstance(payload, BaseModel) else payload
    for key in ("topic", "summary", "message"):
        if key in data and isinstance(data[key], str):
            data[key] = truncate(data[key])
    return json.dumps({"source": "elyos_api", "tool": tool_name, "untrusted": True, "data": data})
