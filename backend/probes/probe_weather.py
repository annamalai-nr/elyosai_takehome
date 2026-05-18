#!/usr/bin/env python3
"""
probe_weather.py — Thorough probe of the Elyos /weather endpoint.

Six tiers, ordered by signal-per-call. ~32 total API calls.
Throttle-aware: retries up to 3 times per call when rate-limited.

Usage:
  conda activate elyosai
  python backend/probes/probe_weather.py
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────────────
MAX_THROTTLE_RETRIES = 3

# ─── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "backend" / "outputs" / "probes" / "weather"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = OUTPUTS_DIR / "weather_probe_log.jsonl"

# ─── API constants ─────────────────────────────────────────────────────
BASE = "https://elyos-interview-907656039105.europe-west2.run.app"
ENDPOINT = "/weather"

# ─── Heuristic patterns ───────────────────────────────────────────────
HEURISTICS = [
    ("html_comment",         r"<!--[\s\S]*?-->"),
    ("override_instruction",
     r"\b(ignore|forget|disregard|override)\s+(all|previous|prior|earlier|the\s+above|any)\s+(instructions?|context|prompts?|directives?)\b"),
    ("ai_self_reference",
     r"\b(if\s+you\s+are\s+an?\s+(llm|ai|assistant|agent|language\s+model)|to\s+the\s+(llm|ai|assistant|model)|dear\s+(llm|ai))\b"),
    ("known_seed_marker",
     r"\b(banana|please\s+add\s+a\s+comment|found\s+via\s+(api|the\s+))\b"),
    ("hidden_unicode",       r"[​‌‍⁠﻿͏‪-‮]"),
    ("roleplay_attempt",
     r"\b(act\s+as|pretend\s+(to\s+be|that)|respond\s+as|from\s+now\s+on|you\s+are\s+now|new\s+role)\b"),
    ("system_marker",
     r"(?:^|\W)(system:|instruction:|important:|note\s+to\s+(assistant|llm|ai|claude|gpt|model)|directive:|new\s+instructions)\b"),
    ("imperative_at_reader",
     r"\b(you\s+must|you\s+should|you\s+will|you\s+need\s+to|please\s+(do|note|add|include|reply))\b"),
]


# ─── HTTP helpers ──────────────────────────────────────────────────────
def fetch(label, params, method="GET", headers=None, timeout=15):
    """Make one HTTP request. Return a dict capturing everything we want logged."""
    qs = urllib.parse.urlencode(params, doseq=True) if params else ""
    url = f"{BASE}{ENDPOINT}" + (f"?{qs}" if qs else "")
    req_headers = dict(headers) if headers else {}
    req = urllib.request.Request(url, headers=req_headers, method=method)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
            resp_headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        status = e.code
        resp_headers = dict(e.headers)
    except Exception as e:
        return {
            "label": label, "method": method, "url": url,
            "status": None, "latency_s": round(time.monotonic() - t0, 3),
            "error": f"{type(e).__name__}: {e}",
            "request_headers": req_headers,
        }
    dt = time.monotonic() - t0
    return {
        "label": label, "method": method, "url": url,
        "status": status, "latency_s": round(dt, 3),
        "response_headers": resp_headers,
        "body_bytes_len": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body": body,
        "request_headers": req_headers,
    }


def is_throttled(result):
    """Check if response is a throttle (HTTP 200 with status=throttled in body)."""
    if result.get("status") != 200 or not result.get("body"):
        return False, 0
    try:
        data = json.loads(result["body"])
        if isinstance(data, dict) and data.get("status") == "throttled":
            return True, data.get("retry_after_seconds", 30)
    except (json.JSONDecodeError, ValueError):
        pass
    return False, 0


def save_raw(result, ts, suffix=""):
    """Write status + headers + body to a .raw file. Returns path or None."""
    if not result.get("body"):
        return None
    filename = f"weather_{ts}_{result['label']}{suffix}.raw"
    path = OUTPUTS_DIR / filename
    with open(path, "wb") as f:
        f.write(f"HTTP {result['status']}\n".encode("utf-8"))
        for k, v in (result.get("response_headers") or {}).items():
            f.write(f"{k}: {v}\n".encode("utf-8"))
        f.write(b"\n")
        f.write(result["body"])
    return path


def run_heuristics(body_bytes):
    """Return list of heuristic labels that matched anywhere in the body."""
    if not body_bytes:
        return []
    try:
        text = body_bytes.decode("utf-8", errors="replace")
    except Exception:
        return []
    hits = []
    for label, pattern in HEURISTICS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(label)
    return hits


def log_jsonl(record):
    """Append one line to the JSONL log. Strip the raw body bytes."""
    clean = {k: v for k, v in record.items() if k != "body"}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(clean, default=str) + "\n")


def execute_one(label, params, method, custom_headers, api_key, ts):
    """fetch with throttle-aware retry loop. Returns the final result dict."""
    if custom_headers is None:
        headers = {"X-API-Key": api_key}
    else:
        headers = dict(custom_headers)

    throttle_retries = 0
    cumulative_throttle_wait_s = 0.0
    first_throttled_body_saved = False

    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        result = fetch(label, params, method=method, headers=headers)
        throttled, wait_seconds = is_throttled(result)

        if not throttled:
            break

        if not first_throttled_body_saved:
            save_raw(result, ts, suffix=".throttled_first")
            first_throttled_body_saved = True

        throttle_retries += 1
        if throttle_retries >= MAX_THROTTLE_RETRIES:
            result["gave_up_after_throttle"] = True
            break

        sleep_time = wait_seconds + 1
        print(f"  [{label:30s}] throttled (retry {throttle_retries}/{MAX_THROTTLE_RETRIES}), waiting {wait_seconds}s...")
        time.sleep(sleep_time)
        cumulative_throttle_wait_s += sleep_time

    save_raw(result, ts)
    result["heuristic_hits"] = run_heuristics(result.get("body", b""))
    result["throttle_retries"] = throttle_retries
    result["cumulative_throttle_wait_s"] = cumulative_throttle_wait_s
    log_jsonl(result)
    return result


def print_row(result):
    """Compact one-line summary printed live during the run."""
    status = result.get("status", "ERR")
    latency = result.get("latency_s", 0)
    size = result.get("body_bytes_len", 0) or 0
    sha = (result.get("body_sha256") or "")[:8] or "--------"
    hits = ",".join(result.get("heuristic_hits", [])) or "-"
    label = result.get("label", "?")
    retries = result.get("throttle_retries", 0)
    gave_up = " GAVE_UP" if result.get("gave_up_after_throttle") else ""
    retry_info = f" R{retries}" if retries > 0 else ""
    print(f"  [{label:30s}] {str(status):>4} {latency:6.2f}s {size:>5}B sha={sha} flags={hits}{retry_info}{gave_up}")


# ─── Tier definitions ─────────────────────────────────────────────────
TIER_1_CITIES = [
    "London", "Paris", "Tokyo", "Mumbai",
    "New York", "Sydney", "Cairo", "Reykjavik",
]

TIER_3_EDGES = [
    ("t3_empty",          {"location": ""}),
    ("t3_upper",          {"location": "LONDON"}),
    ("t3_lower",          {"location": "london"}),
    ("t3_padded",         {"location": "  London  "}),
    ("t3_atlantis",       {"location": "Atlantis"}),
    ("t3_mars",           {"location": "Mars"}),
    ("t3_springfield",    {"location": "Springfield"}),
    ("t3_unicode_kyoto",  {"location": "京都"}),
    ("t3_very_long",      {"location": "x" * 5000}),
    ("t3_comma_uk",       {"location": "London, UK"}),
]

TIER_4_PROTOCOL = [
    ("t4_extra_param",    {"location": "London", "foo": "bar"},                "GET",     None),
    ("t4_wrong_param",    {"city": "London"},                                  "GET",     None),
    ("t4_dup_param",      [("location", "London"), ("location", "Paris")],     "GET",     None),
    ("t4_no_params",      {},                                                  "GET",     None),
    ("t4_options",        {},                                                  "OPTIONS", None),
]


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("ELYOS_API_KEY")
    if not api_key and len(sys.argv) > 1:
        api_key = sys.argv[1]
    if not api_key:
        print("Error: ELYOS_API_KEY not set in .env or passed as argument.", file=sys.stderr)
        sys.exit(2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    wall_start = time.monotonic()
    print(f"Probing {BASE}{ENDPOINT}")
    print(f"Output dir: {OUTPUTS_DIR}")
    print(f"Log file:   {LOG_FILE}")
    print(f"Run timestamp: {ts}")
    print(f"Max throttle retries per call: {MAX_THROTTLE_RETRIES}")
    print()

    # ── TIER 1: Schema diversity ──────────────────────────────────────
    print("─── Tier 1: Schema diversity (8 cities) ─────────────────────────")
    for city in TIER_1_CITIES:
        result = execute_one(
            label=f"t1_{city.replace(' ', '_')}",
            params={"location": city},
            method="GET",
            custom_headers=None,
            api_key=api_key,
            ts=ts,
        )
        print_row(result)

    # ── TIER 2: Cache test ────────────────────────────────────────────
    print("\n─── Tier 2: Cache test (repeat London) ──────────────────────────")
    result = execute_one(
        label="t2_london_repeat",
        params={"location": "London"},
        method="GET",
        custom_headers=None,
        api_key=api_key,
        ts=ts,
    )
    print_row(result)

    # ── TIER 3: Input edges ──────────────────────────────────────────
    print("\n─── Tier 3: Input edges (10 calls) ──────────────────────────────")
    for label, params in TIER_3_EDGES:
        result = execute_one(label, params, "GET", None, api_key, ts)
        print_row(result)

    # ── TIER 4: Protocol edges ───────────────────────────────────────
    print("\n─── Tier 4: Protocol edges (5 calls) ────────────────────────────")
    for label, params, method, custom_headers in TIER_4_PROTOCOL:
        result = execute_one(label, params, method, custom_headers, api_key, ts)
        print_row(result)

    # ── TIER 5: Auth edges ───────────────────────────────────────────
    print("\n─── Tier 5: Auth edges (3 calls) ────────────────────────────────")
    auth_cases = [
        ("t5_no_key",        {"location": "London"}, "GET", {}),
        ("t5_wrong_key",     {"location": "London"}, "GET", {"X-API-Key": "wrong-key-12345"}),
        ("t5_lowercase_hdr", {"location": "London"}, "GET", {"x-api-key": api_key}),
    ]
    for label, params, method, custom_headers in auth_cases:
        result = execute_one(label, params, method, custom_headers, api_key, ts)
        print_row(result)

    # ── TIER 6: Concurrency ──────────────────────────────────────────
    print("\n─── Tier 6: Concurrency (5 parallel London) ─────────────────────")
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [
            ex.submit(execute_one,
                      f"t6_concurrent_{i}",
                      {"location": "London"}, "GET", None, api_key, ts)
            for i in range(5)
        ]
        results = [f.result() for f in futures]
    wall = time.monotonic() - t0
    seq = sum(r.get("latency_s", 0) for r in results)
    for r in results:
        print_row(r)
    print(f"  wall time: {wall:.2f}s   sequential-equivalent: {seq:.2f}s")

    # ── Summary ──────────────────────────────────────────────────────
    total_wall = time.monotonic() - wall_start
    print()
    print("=" * 72)
    print("  Run complete")
    print("=" * 72)
    print(f"  Total wall-clock time: {total_wall:.1f}s")
    print(f"  Raw responses: {OUTPUTS_DIR}")
    print(f"  JSONL log:     {LOG_FILE}")
    print()


if __name__ == "__main__":
    main()
