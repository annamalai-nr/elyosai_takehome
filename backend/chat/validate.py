import json

from backend.chat.models import NormalisedWeather, ResearchResult
from backend.chat.parsers import envelope, normalise_weather, parse_research


def validate() -> None:
    ok = 0

    # Single-observation weather (Shape A)
    a = normalise_weather(
        {"location": "London", "temperature_c": 14.0, "condition": "Partly cloudy", "humidity": 67},
        "London",
    )
    assert isinstance(a, NormalisedWeather), f"Shape A failed: {a}"
    assert a.returned_location == "London" and len(a.observations) == 1
    ok += 1

    # Multi-observation weather (Shape B)
    b = normalise_weather(
        {
            "location": "Paris",
            "conditions": [
                {"temperature_c": 13.2, "condition": "Overcast", "humidity": 88},
                {"temperature_c": 12.2, "condition": "light rain", "humidity": 100},
            ],
            "note": "Multiple conditions reported",
        },
        "Paris",
    )
    assert isinstance(b, NormalisedWeather), f"Shape B failed: {b}"
    assert len(b.observations) == 2 and b.note is not None
    ok += 1

    # Location mismatch detection
    m = normalise_weather(
        {"location": "Marseille", "temperature_c": 20.0, "condition": "Sunny", "humidity": 55},
        "Mars",
    )
    assert isinstance(m, NormalisedWeather), f"Fuzzy match failed: {m}"
    assert m.requested_location == "Mars" and m.returned_location == "Marseille"
    ok += 1

    # Fresh research
    rf = parse_research({"topic": "solar", "summary": "s", "sources": [], "generated_at": "2026-05-17"})
    assert isinstance(rf, ResearchResult) and rf.kind == "fresh", f"Fresh failed: {rf}"
    ok += 1

    # Cached research
    rc = parse_research({
        "topic": "climate", "summary": "s", "sources": [],
        "generated_at": "2024-03-15", "cached": True, "cache_age_seconds": 99,
    })
    assert isinstance(rc, ResearchResult) and rc.kind == "cached", f"Cached failed: {rc}"
    assert rc.cache_age_seconds == 99 and rc.cache_age == "99 seconds" and rc.generated_at == "2024-03-15"
    cached_env = json.loads(envelope("research_topic", rc))
    assert "stale_warning" not in cached_env["data"]
    ok += 1

    # Truncated research
    rt = parse_research({
        "topic": "long", "summary": "s", "sources": [], "generated_at": "x",
        "truncated": True, "original_topic_length": 62, "processed_topic": "first 50",
    })
    assert isinstance(rt, ResearchResult) and rt.kind == "truncated", f"Truncated failed: {rt}"
    assert rt.processed_topic == "first 50"
    ok += 1

    # Timeout (empty response)
    timeout_result = parse_research({})
    assert isinstance(timeout_result, ResearchResult) and timeout_result.kind == "timeout", f"Timeout failed: {timeout_result}"
    ok += 1

    # Error passthrough
    err = normalise_weather({"error": "http_404", "message": "not found"}, "X")
    assert isinstance(err, dict) and "error" in err, f"Error passthrough failed: {err}"
    ok += 1

    # Envelope structure
    env = json.loads(envelope("get_weather", NormalisedWeather(
        requested_location="London",
        returned_location="London",
        observations=[{"temp_c": 14.0, "condition": "Partly cloudy", "humidity": 67}],
    )))
    assert env["untrusted"] is True and env["source"] == "elyos_api", f"Envelope failed: {env}"
    ok += 1

    print(f"All {ok} validations passed.")


if __name__ == "__main__":
    validate()
