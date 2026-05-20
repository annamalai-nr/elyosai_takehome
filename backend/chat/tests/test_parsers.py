"""Behavioral tests for weather/research parsers and the untrusted-data envelope."""

import json
import sys

from backend.chat.models import NormalisedWeather, ResearchResult
from backend.chat.parsers import envelope, normalise_weather, parse_research


def test_shape_a_weather():
    """Single-observation weather (Shape A) parses correctly."""
    a = normalise_weather(
        {"location": "London", "temperature_c": 14.0, "condition": "Partly cloudy", "humidity": 67},
        "London",
    )
    assert isinstance(a, NormalisedWeather), f"Shape A failed: {a}"
    assert a.returned_location == "London" and len(a.observations) == 1
    return True, "Shape A parsed"


def test_shape_b_weather():
    """Multi-observation weather (Shape B) parses correctly."""
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
    return True, "Shape B parsed"


def test_location_mismatch():
    """Fuzzy-matched location preserves requested vs returned."""
    m = normalise_weather(
        {"location": "Marseille", "temperature_c": 20.0, "condition": "Sunny", "humidity": 55},
        "Mars",
    )
    assert isinstance(m, NormalisedWeather), f"Fuzzy match failed: {m}"
    assert m.requested_location == "Mars" and m.returned_location == "Marseille"
    return True, "mismatch detected"


def test_fresh_research():
    """Fresh research parses with kind='fresh'."""
    rf = parse_research({"topic": "solar", "summary": "s", "sources": [], "generated_at": "2026-05-17"})
    assert isinstance(rf, ResearchResult) and rf.kind == "fresh", f"Fresh failed: {rf}"
    return True, "fresh parsed"


def test_cached_research():
    """Cached research preserves cache_age and generated_at."""
    rc = parse_research({
        "topic": "climate", "summary": "s", "sources": [],
        "generated_at": "2024-03-15", "cached": True, "cache_age_seconds": 99,
    })
    assert isinstance(rc, ResearchResult) and rc.kind == "cached", f"Cached failed: {rc}"
    assert rc.cache_age_seconds == 99 and rc.cache_age == "~1 day" and rc.generated_at == "2024-03-15"
    cached_env = json.loads(envelope("research_topic", rc))
    assert "stale_warning" not in cached_env["data"]
    return True, "cached parsed"


def test_truncated_research():
    """Truncated research preserves processed_topic."""
    rt = parse_research({
        "topic": "long", "summary": "s", "sources": [], "generated_at": "x",
        "truncated": True, "original_topic_length": 62, "processed_topic": "first 50",
    })
    assert isinstance(rt, ResearchResult) and rt.kind == "truncated", f"Truncated failed: {rt}"
    assert rt.processed_topic == "first 50"
    return True, "truncated parsed"


def test_timeout_research():
    """Empty response parses as timeout."""
    timeout_result = parse_research({})
    assert isinstance(timeout_result, ResearchResult) and timeout_result.kind == "timeout", f"Timeout failed: {timeout_result}"
    return True, "timeout parsed"


def test_error_passthrough():
    """Error dict passes through normalise_weather unchanged."""
    err = normalise_weather({"error": "http_404", "message": "not found"}, "X")
    assert isinstance(err, dict) and "error" in err, f"Error passthrough failed: {err}"
    return True, "error passed through"


def test_envelope_structure():
    """Envelope wraps with untrusted flag and source."""
    env = json.loads(envelope("get_weather", NormalisedWeather(
        requested_location="London",
        returned_location="London",
        observations=[{"temp_c": 14.0, "condition": "Partly cloudy", "humidity": 67}],
    )))
    assert env["untrusted"] is True and env["source"] == "elyos_api", f"Envelope failed: {env}"
    return True, "envelope correct"


TESTS = [
    test_shape_a_weather,
    test_shape_b_weather,
    test_location_mismatch,
    test_fresh_research,
    test_cached_research,
    test_truncated_research,
    test_timeout_research,
    test_error_passthrough,
    test_envelope_structure,
]


def run() -> None:
    for test in TESTS:
        passed, msg = test()
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {test.__doc__} — {msg}")
        if not passed:
            sys.exit(1)
    print(f"All {len(TESTS)} parser tests passed.")
