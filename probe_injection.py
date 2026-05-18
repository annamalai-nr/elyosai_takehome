#!/usr/bin/env python3
"""
probe_injection.py — Minimum-footprint check for prompt-injection content
in the Elyos take-home /weather and /research endpoints.

Makes 2 API calls total by default: one to /weather and one to /research,
using innocuous, expected inputs ("London" and "climate change"). For each
response:
  - saves the full HTTP response (status + headers + body) to a .raw file
  - prints the body for visual inspection
  - runs broad heuristic flags (not just "banana" / "ignore")
  - prints a SHA-256 hash so you can later re-run and diff for static content

Dependencies: python-dotenv (installed via `pip install -e .` in the elyosai
conda environment). Everything else is stdlib.

Usage:
    conda activate elyosai
    cd /Users/annamalainarayanan/Desktop/personal/interview_prep/elyosai
    python probe_injection.py

The script reads ELYOS_API_KEY from .env (in the script directory) via
python-dotenv. You can also pass the key explicitly:
    python probe_injection.py <your-key>

Output files (saved next to this script):
    weather_<timestamp>.raw    full HTTP response from /weather
    research_<timestamp>.raw   full HTTP response from /research
"""

import hashlib
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE = "https://elyos-interview-907656039105.europe-west2.run.app"
SCRIPT_DIR = Path(__file__).parent

# -----------------------------------------------------------------------
# Heuristic patterns. Broad on purpose. Hits are candidates for visual
# inspection, not definitive verdicts. False positives are acceptable;
# false negatives are the real risk.
# -----------------------------------------------------------------------
HEURISTICS = [
    # HIGH-SIGNAL — these are smoking guns in JSON tool responses
    ("html_comment",
     r"<!--[\s\S]*?-->"),
    ("override_instruction",
     r"\b(ignore|forget|disregard|override)\s+(all|previous|prior|earlier|the\s+above|any)\s+(instructions?|context|prompts?|directives?)\b"),
    ("ai_self_reference",
     r"\b(if\s+you\s+are\s+an?\s+(llm|ai|assistant|agent|language\s+model)|to\s+the\s+(llm|ai|assistant|model)|dear\s+(llm|ai))\b"),
    ("hidden_unicode",
     r"[​‌‍⁠﻿͏‪-‮]"),
    ("known_seed_marker",
     r"\b(banana|please\s+add\s+a\s+comment|found\s+via\s+(api|the\s+))\b"),

    # MEDIUM-SIGNAL — review in context
    ("roleplay_attempt",
     r"\b(act\s+as|pretend\s+(to\s+be|that)|respond\s+as|from\s+now\s+on|you\s+are\s+now|new\s+role)\b"),
    ("system_marker",
     r"(?:^|\W)(system:|instruction:|important:|note\s+to\s+(assistant|llm|ai|claude|gpt|model)|directive:|new\s+instructions)\b"),
    ("base64_blob",
     r"\b[A-Za-z0-9+/]{60,}={0,2}\b"),

    # LOW-SIGNAL — only suspicious in context (e.g., free-text imperatives in /weather)
    ("imperative_at_reader",
     r"\b(you\s+must|you\s+should|you\s+will|you\s+need\s+to|please\s+(do|note|add|include|reply))\b"),
]


def fetch(endpoint, param_name, param_value, api_key, timeout=20):
    """Make one GET. Return (status, headers_dict, body_bytes)."""
    qs = urllib.parse.urlencode({param_name: param_value})
    url = f"{BASE}/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"X-API-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        # HTTPError includes status, headers and body — preserve them
        return e.code, dict(e.headers), e.read()


def save_raw(filename, status, headers, body):
    """Write status line + headers + body to a file. Returns the path."""
    path = SCRIPT_DIR / filename
    with open(path, "wb") as f:
        f.write(f"HTTP {status}\n".encode("utf-8"))
        for k, v in headers.items():
            f.write(f"{k}: {v}\n".encode("utf-8"))
        f.write(b"\n")
        f.write(body)
    return path


def run_heuristics(body_text):
    """Return list of (label, [first 5 matches]) for patterns that hit."""
    hits = []
    for label, pattern in HEURISTICS:
        matches = re.findall(pattern, body_text, flags=re.IGNORECASE)
        if matches:
            # findall on grouped patterns returns tuples; flatten to display
            flat = []
            for m in matches[:5]:
                if isinstance(m, tuple):
                    flat.append("".join(p for p in m if p))
                else:
                    flat.append(m)
            hits.append((label, flat))
    return hits


def hash_body(body_bytes):
    return hashlib.sha256(body_bytes).hexdigest()


def analyse(label, endpoint, param, value, api_key):
    """Probe one endpoint, save and analyse the response."""
    print()
    print("=" * 72)
    print(f"  {label}: GET /{endpoint}?{param}={value}")
    print("=" * 72)

    try:
        status, headers, body = fetch(endpoint, param, value, api_key)
    except Exception as e:
        print(f"  FETCH FAILED: {type(e).__name__}: {e}")
        return None

    body_text = body.decode("utf-8", errors="replace")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = save_raw(f"{endpoint}_{ts}.raw", status, headers, body)
    body_sha = hash_body(body)

    print(f"\n  Status:    {status}")
    print(f"  Size:      {len(body)} bytes")
    print(f"  SHA-256:   {body_sha}")
    print(f"  Saved:     {raw_path}")
    print(f"  Headers seen: {', '.join(headers.keys())}")

    print("\n  --- Body (for visual inspection) ---")
    if len(body_text) <= 4000:
        print(body_text)
    else:
        print(body_text[:2000])
        print(f"\n  [... {len(body_text) - 4000} chars truncated; full body in saved file ...]\n")
        print(body_text[-2000:])

    print("\n  --- Heuristic flags ---")
    hits = run_heuristics(body_text)
    if hits:
        for name, matches in hits:
            print(f"    [{name}]")
            for m in matches:
                preview = m if len(m) <= 120 else m[:117] + "..."
                print(f"        -> {preview!r}")
    else:
        print("    (no heuristic patterns matched)")

    return body_sha


def main():
    # Load .env from the script's directory if present. python-dotenv silently
    # no-ops if the file is missing, so passing-key-as-arg still works.
    load_dotenv(SCRIPT_DIR / ".env")

    api_key = os.environ.get("ELYOS_API_KEY")
    if not api_key and len(sys.argv) > 1:
        api_key = sys.argv[1]

    if not api_key:
        print("Error: API key not provided.", file=sys.stderr)
        print("Usage:", file=sys.stderr)
        print("  export ELYOS_API_KEY=<your-key>", file=sys.stderr)
        print("  python probe_injection.py", file=sys.stderr)
        print("OR:", file=sys.stderr)
        print("  python probe_injection.py <your-key>", file=sys.stderr)
        sys.exit(2)

    print("Probing Elyos /weather and /research for injection content")
    print("2 API calls total — one per documented endpoint")
    print(f"Saving raw responses to: {SCRIPT_DIR}")

    weather_sha = analyse("WEATHER", "weather", "location", "London", api_key)
    research_sha = analyse("RESEARCH", "research", "topic", "climate change", api_key)

    print()
    print("=" * 72)
    print("  Summary")
    print("=" * 72)
    print(f"  Weather  body SHA-256: {weather_sha}")
    print(f"  Research body SHA-256: {research_sha}")
    print()
    print("  A single response per endpoint can prove injection is present if one appears.")
    print("  It cannot prove injections are absent from other inputs.")
    print("  Visual inspection of the printed bodies above is the gold standard.")
    print("  Heuristic flags are candidates, not verdicts.")
    print()


if __name__ == "__main__":
    main()
