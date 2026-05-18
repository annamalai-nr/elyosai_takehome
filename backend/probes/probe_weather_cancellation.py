#!/usr/bin/env python3
"""
probe_weather_cancellation.py — Sidecar to probe_weather.py.

Probes how the /weather endpoint behaves under client-side mid-flight
cancellation. Weather is fast (~150 ms warm), so "mid-flight" is a
~50 ms window — testable via httpx async cancellation.

Three small experiments, ~8 API calls total, ~30–90 s wall time depending
on throttle state.

  A. Budget consumption — does a cancelled call consume a throttle slot?
     Procedure: use 4 slots with normal calls, issue a 5th with 50 ms timeout
     (cancels mid-flight), then probe with a 6th. If the probe throttles →
     cancelled call consumed the slot.

  B. Task cancel cleanliness — does asyncio.task.cancel() raise
     CancelledError cleanly, no zombie tasks or hanging connections?
     Procedure: start a request as a task, sleep 50 ms, task.cancel(),
     await task. Inspect the exception.

  C. Client reusability — after cancellation, is the underlying connection
     pool still usable, or does the next request fail?
     Procedure: immediately after Experiment B, fire one more normal call
     on the same httpx.AsyncClient and confirm 200.

Outputs:
  backend/outputs/probes/weather/weather_cancel_log.jsonl  — one line per action
  (no per-call .raw files — bodies for cancelled calls are absent or partial)

Usage:
  conda activate elyosai
  python backend/probes/probe_weather_cancellation.py
"""

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ─── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "backend" / "outputs" / "probes" / "weather"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = OUTPUTS_DIR / "weather_cancel_log.jsonl"

# ─── API constants ─────────────────────────────────────────────────────
BASE = "https://elyos-interview-907656039105.europe-west2.run.app"
ENDPOINT = "/weather"
THROTTLE_BUFFER_S = 1.0  # safety margin on top of retry_after_seconds


# ─── Helpers ──────────────────────────────────────────────────────────
def parse_throttle(body_bytes):
    """Return (is_throttled, retry_after_seconds) for a response body."""
    if not body_bytes:
        return False, 0
    try:
        j = json.loads(body_bytes)
        if isinstance(j, dict) and j.get("status") == "throttled":
            return True, int(j.get("retry_after_seconds", 30))
    except (json.JSONDecodeError, ValueError):
        pass
    return False, 0


def log(record):
    """Append one JSONL line."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def short(s, n=200):
    """Truncate string for live console output."""
    return s if len(s) <= n else s[:n] + "..."


# ─── Action primitives ────────────────────────────────────────────────
async def normal_call(client, api_key, label, ts):
    """A regular call. Returns dict with status, body, throttle flag."""
    t0 = time.monotonic()
    try:
        resp = await client.get(
            f"{BASE}{ENDPOINT}",
            params={"location": "London"},
            headers={"X-API-Key": api_key},
            timeout=15.0,
        )
        dt = time.monotonic() - t0
        body = resp.content
        throttled, retry_after = parse_throttle(body)
        record = {
            "ts": ts, "label": label, "kind": "normal",
            "status": resp.status_code,
            "latency_s": round(dt, 3),
            "body_bytes_len": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "is_throttled": throttled,
            "retry_after_seconds": retry_after if throttled else None,
            "body_preview": short(body.decode("utf-8", errors="replace"), 200),
        }
    except Exception as e:
        dt = time.monotonic() - t0
        record = {
            "ts": ts, "label": label, "kind": "normal",
            "status": None, "latency_s": round(dt, 3),
            "error": f"{type(e).__name__}: {e}",
        }
    log(record)
    return record


async def timeout_cancel(client, api_key, label, timeout_s, ts):
    """Issue a call with a very short timeout. Cancels mid-flight."""
    t0 = time.monotonic()
    try:
        resp = await client.get(
            f"{BASE}{ENDPOINT}",
            params={"location": "London"},
            headers={"X-API-Key": api_key},
            timeout=timeout_s,
        )
        dt = time.monotonic() - t0
        body = resp.content
        throttled, _ = parse_throttle(body)
        record = {
            "ts": ts, "label": label, "kind": "timeout_cancel",
            "status": resp.status_code,
            "latency_s": round(dt, 3),
            "body_bytes_len": len(body),
            "completed_before_timeout": True,
            "timeout_s": timeout_s,
            "is_throttled": throttled,
        }
    except (httpx.TimeoutException,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout) as e:
        dt = time.monotonic() - t0
        record = {
            "ts": ts, "label": label, "kind": "timeout_cancel",
            "status": None,
            "latency_s": round(dt, 3),
            "completed_before_timeout": False,
            "timeout_s": timeout_s,
            "exception_type": type(e).__name__,
            "exception_msg": str(e),
        }
    except Exception as e:
        dt = time.monotonic() - t0
        record = {
            "ts": ts, "label": label, "kind": "timeout_cancel",
            "status": None,
            "latency_s": round(dt, 3),
            "completed_before_timeout": False,
            "timeout_s": timeout_s,
            "exception_type": type(e).__name__,
            "exception_msg": str(e),
        }
    log(record)
    return record


async def task_cancel(client, api_key, label, cancel_after_ms, ts):
    """Start a request as an asyncio task, then cancel after N ms."""
    t0 = time.monotonic()
    task = asyncio.create_task(
        client.get(
            f"{BASE}{ENDPOINT}",
            params={"location": "London"},
            headers={"X-API-Key": api_key},
            timeout=15.0,
        )
    )
    await asyncio.sleep(cancel_after_ms / 1000.0)
    task.cancel()
    try:
        resp = await task
        dt = time.monotonic() - t0
        record = {
            "ts": ts, "label": label, "kind": "task_cancel",
            "status": resp.status_code,
            "latency_s": round(dt, 3),
            "completed_before_cancel": True,
            "cancel_after_ms": cancel_after_ms,
        }
    except asyncio.CancelledError:
        dt = time.monotonic() - t0
        record = {
            "ts": ts, "label": label, "kind": "task_cancel",
            "status": None,
            "latency_s": round(dt, 3),
            "completed_before_cancel": False,
            "cancel_after_ms": cancel_after_ms,
            "exception_type": "asyncio.CancelledError",
            "exception_clean": True,
        }
    except Exception as e:
        dt = time.monotonic() - t0
        record = {
            "ts": ts, "label": label, "kind": "task_cancel",
            "status": None,
            "latency_s": round(dt, 3),
            "completed_before_cancel": False,
            "cancel_after_ms": cancel_after_ms,
            "exception_type": type(e).__name__,
            "exception_msg": str(e),
            "exception_clean": False,
        }
    log(record)
    return record


async def wait_if_throttled(client, api_key, ts, max_waits=2):
    """If the API is currently throttled, sleep through the window."""
    for i in range(max_waits):
        r = await normal_call(client, api_key, f"state_check_{i}", ts)
        if not r.get("is_throttled"):
            return r
        wait = r.get("retry_after_seconds", 30) + THROTTLE_BUFFER_S
        print(f"  [state_check_{i}] throttled, waiting {wait:.0f}s...")
        await asyncio.sleep(wait)
    return r  # last attempt, may still be throttled


# ─── Experiments ──────────────────────────────────────────────────────
async def experiment_a(client, api_key, ts):
    """A: Does a cancelled call consume a throttle slot?"""
    print("\n─── Experiment A: Does cancellation consume a throttle slot? ───")

    print("  Pre-flight: ensure we're not currently throttled")
    state = await wait_if_throttled(client, api_key, ts)
    print(f"    state: status={state.get('status')} throttled={state.get('is_throttled')}")
    # state_check_0 just consumed 1 slot. So we have ~4 left.

    print("  Step 1: Use 3 more normal calls (now at ~4/5 of window)")
    for i in range(3):
        r = await normal_call(client, api_key, f"A_setup_{i+1}", ts)
        flag = "THROTTLED" if r.get("is_throttled") else f"{r.get('status')}"
        print(f"    A_setup_{i+1}: {flag} latency={r.get('latency_s')}s")
        if r.get("is_throttled"):
            print("    (unexpectedly throttled during setup — window count may differ)")

    print("  Step 2: Issue a 5th call with 50 ms timeout (cancels mid-flight)")
    r_cancel = await timeout_cancel(client, api_key, "A_cancelled_5th", timeout_s=0.05, ts=ts)
    print(f"    A_cancelled_5th: completed={r_cancel.get('completed_before_timeout')} "
          f"latency={r_cancel.get('latency_s')}s "
          f"exc={r_cancel.get('exception_type')}")

    print("  Step 3: Probe with a 6th call to see if budget was consumed")
    r_probe = await normal_call(client, api_key, "A_probe_after_cancel", ts)
    was_throttled = r_probe.get("is_throttled", False)
    print(f"    A_probe_after_cancel: throttled={was_throttled} status={r_probe.get('status')}")

    verdict = ("CONSUMED a throttle slot" if was_throttled
               else "DID NOT consume a throttle slot")
    print(f"  → Verdict: cancelled call {verdict}")

    log({"ts": ts, "label": "A_verdict", "kind": "verdict",
         "cancelled_consumed_throttle": was_throttled})
    return was_throttled


async def experiment_b(client, api_key, ts):
    """B: Does asyncio task.cancel() raise CancelledError cleanly?"""
    print("\n─── Experiment B: asyncio task.cancel() cleanliness ───")
    # Wait through throttle if Experiment A left us throttled.
    state = await wait_if_throttled(client, api_key, ts)
    if state.get("is_throttled"):
        print("    (still throttled after wait — task_cancel will run anyway)")
    print("  Starting request as task, cancelling after 50 ms")
    r = await task_cancel(client, api_key, "B_task_cancel_50ms", cancel_after_ms=50, ts=ts)
    print(f"    B_task_cancel_50ms: exc={r.get('exception_type')} "
          f"clean={r.get('exception_clean')} latency={r.get('latency_s')}s")
    return r


async def experiment_c(client, api_key, ts):
    """C: After cancellation, is the same httpx client still usable?"""
    print("\n─── Experiment C: Client reusability after cancel ───")
    r = await normal_call(client, api_key, "C_reuse_after_cancel", ts)
    if r.get("status") == 200 and not r.get("is_throttled"):
        print(f"    C_reuse_after_cancel: ✓ status=200, client pool intact")
    elif r.get("is_throttled"):
        print(f"    C_reuse_after_cancel: throttled — client pool intact (throttle is "
              f"unrelated to cancellation)")
    else:
        print(f"    C_reuse_after_cancel: ✗ status={r.get('status')} error={r.get('error')}")
    return r


# ─── Entrypoint ───────────────────────────────────────────────────────
async def main():
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("ELYOS_API_KEY")
    if not api_key and len(sys.argv) > 1:
        api_key = sys.argv[1]
    if not api_key:
        print("Error: ELYOS_API_KEY not set in .env or argv.", file=sys.stderr)
        sys.exit(2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Probing /weather cancellation behaviour")
    print(f"Endpoint:    {BASE}{ENDPOINT}")
    print(f"Log:         {LOG_FILE}")
    print(f"Run ts:      {ts}")

    t_start = time.monotonic()
    async with httpx.AsyncClient() as client:
        await experiment_a(client, api_key, ts)
        await experiment_b(client, api_key, ts)
        await experiment_c(client, api_key, ts)
    wall = time.monotonic() - t_start

    print(f"\nDone in {wall:.1f}s")
    print(f"Inspect:  cat {LOG_FILE} | jq")


if __name__ == "__main__":
    asyncio.run(main())
