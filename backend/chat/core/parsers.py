import json
from typing import Any

from pydantic import BaseModel

from backend.chat.core.models import NormalisedWeather, ResearchResult, WeatherObservation


def _humanize_seconds(seconds: int) -> str:
    days = seconds // 86400
    if days >= 365:
        years = days // 365
        return f"~{years} year{'s' if years != 1 else ''}"
    if days >= 30:
        months = days // 30
        return f"~{months} month{'s' if months != 1 else ''}"
    if days >= 1:
        return f"~{days} day{'s' if days != 1 else ''}"
    hours = seconds // 3600
    if hours >= 1:
        return f"~{hours} hour{'s' if hours != 1 else ''}"
    return f"{seconds} seconds"


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

    if data.get("generated_at"):
        kwargs["generated_at"] = data["generated_at"]

    if data.get("cached"):
        kind = "cached"
        raw_age = data.get("cache_age_seconds")
        if raw_age is not None:
            kwargs["cache_age_seconds"] = int(raw_age)
            kwargs["cache_age"] = _humanize_seconds(int(raw_age))
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
