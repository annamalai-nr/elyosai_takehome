import json

from backend.chat.core.models import NormalisedWeather, ResearchResult
from backend.chat.core.parsers import envelope, normalise_weather, parse_research


def validate():
    ok = 0

    a = normalise_weather({"location": "London", "temperature_c": 14.0, "condition": "Partly cloudy", "humidity": 67}, "London")
    assert isinstance(a, NormalisedWeather) and a.returned_location == "London" and len(a.observations) == 1, f"Shape A failed: {a}"
    ok += 1

    b = normalise_weather(
        {"location": "Paris", "conditions": [
            {"temperature_c": 13.2, "condition": "Overcast", "humidity": 88},
            {"temperature_c": 12.2, "condition": "light rain", "humidity": 100}],
         "note": "Multiple conditions reported"}, "Paris")
    assert isinstance(b, NormalisedWeather) and len(b.observations) == 2 and b.note is not None, f"Shape B failed: {b}"
    ok += 1

    m = normalise_weather({"location": "Marseille", "temperature_c": 20.0, "condition": "Sunny", "humidity": 55}, "Mars")
    assert isinstance(m, NormalisedWeather) and m.requested_location == "Mars" and m.returned_location == "Marseille", f"Fuzzy match failed: {m}"
    ok += 1

    rf = parse_research({"topic": "solar", "summary": "s", "sources": [], "generated_at": "2026-05-17"})
    assert isinstance(rf, ResearchResult) and rf.kind == "fresh", f"Fresh failed: {rf}"
    ok += 1

    rc = parse_research({"topic": "climate", "summary": "s", "sources": [], "generated_at": "2024-03-15", "cached": True, "cache_age_seconds": 99})
    assert isinstance(rc, ResearchResult) and rc.kind == "cached" and rc.stale_warning is not None, f"Cached failed: {rc}"
    ok += 1

    rt = parse_research({"topic": "long", "summary": "s", "sources": [], "generated_at": "x", "truncated": True, "original_topic_length": 62, "processed_topic": "first 50"})
    assert isinstance(rt, ResearchResult) and rt.kind == "truncated" and rt.processed_topic == "first 50", f"Truncated failed: {rt}"
    ok += 1

    re = parse_research({})
    assert isinstance(re, ResearchResult) and re.kind == "timeout", f"Timeout failed: {re}"
    ok += 1

    err = normalise_weather({"error": "http_404", "message": "not found"}, "X")
    assert isinstance(err, dict) and "error" in err, f"Error passthrough failed: {err}"
    ok += 1

    env = json.loads(envelope("get_weather", NormalisedWeather(
        requested_location="London", returned_location="London",
        observations=[{"temp_c": 14.0, "condition": "Partly cloudy", "humidity": 67}])))
    assert env["untrusted"] is True and env["source"] == "elyos_api", f"Envelope failed: {env}"
    ok += 1

    print(f"All {ok} validations passed.")


if __name__ == "__main__":
    validate()
