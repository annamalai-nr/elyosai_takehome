import json
from typing import Any

from pydantic import BaseModel

from backend.chat.core.models import NormalisedWeather, ResearchResult, WeatherObservation


def normalise_weather(data: dict, requested_location: str) -> NormalisedWeather | dict:
    """Parse raw weather API response into a NormalisedWeather or an error dict."""
    if "error" in data:
        return data
    result_kwargs: dict[str, Any] = {
        "requested_location": requested_location,
        "returned_location": data.get("location", requested_location),
    }
    if "temperature_c" in data:
        result_kwargs["observations"] = [
            WeatherObservation(temp_c=data["temperature_c"], condition=data["condition"], humidity=data["humidity"])
        ]
    elif "conditions" in data:
        result_kwargs["observations"] = [
            WeatherObservation(temp_c=o["temperature_c"], condition=o["condition"], humidity=o["humidity"])
            for o in data["conditions"]
        ]
        if data.get("note"):
            result_kwargs["note"] = data["note"]
    else:
        return {"error": "unknown_schema", "message": f"Unrecognised weather shape: {list(data.keys())}"}
    return NormalisedWeather(**result_kwargs)


def parse_research(data: dict) -> ResearchResult | dict:
    """Parse raw research API response into a ResearchResult or an error dict."""
    if "error" in data:
        return data
    if not data:
        return ResearchResult(kind="timeout", message="Research timed out. Try a more specific topic or try again.")
    result_kwargs: dict[str, Any] = {
        "kind": "fresh",
        "topic": data.get("topic", ""),
        "summary": data.get("summary", ""),
        "sources": data.get("sources", []),
    }
    if data.get("cached"):
        result_kwargs["kind"] = "cached"
        result_kwargs["cache_age_seconds"] = data.get("cache_age_seconds")
        result_kwargs["stale_warning"] = "This data is from early 2024 and may not reflect recent developments."
    if data.get("truncated"):
        result_kwargs["kind"] = "truncated"
        result_kwargs["processed_topic"] = data.get("processed_topic", "")
        result_kwargs["original_topic_length"] = data.get("original_topic_length")
    return ResearchResult(**result_kwargs)


def truncate(s: str, max_len: int = 200) -> str:
    """Truncate a string to max_len, appending '...' if shortened."""
    return s if len(s) <= max_len else s[:max_len] + "..."


def envelope(tool_name: str, data: BaseModel | dict) -> str:
    """Wrap tool output in a JSON envelope marking data as untrusted."""
    if isinstance(data, BaseModel):
        data = data.model_dump(exclude_none=True)
    if isinstance(data, dict):
        for key in ("topic", "summary", "message"):
            if key in data and isinstance(data[key], str):
                data[key] = truncate(data[key])
    return json.dumps({"source": "elyos_api", "tool": tool_name, "untrusted": True, "data": data})
