#!/usr/bin/env python3
"""
probe_research_cancellation.py — Sidecar to probe_research.py.

Probes how the /research endpoint behaves under client-side mid-flight
cancellation. /research takes 3–8 s, giving a real mid-flight window
(~2 s in) — the chat app's Ctrl+C handling must work cleanly here.

Three small experiments, ~6 API calls, ~30–90 s wall time depending on
throttle state. See research_probe_plan.html §12 for full rationale.

  A. Budget consumption — does a cancelled call consume a throttle slot?
     Procedure: confirm we're not throttled, use 3 more slots with normal
     calls (now at ~4/5 of window), issue a 5th with 100 ms timeout (too
     short to complete a 3–8 s call — forces mid-flight cancel), then
     probe with a 6th. If the probe throttles → cancelled call consumed
     the slot. Especially interesting here because the server may have
     started expensive "AI processing" before the cancel arrived.

  B. Task cancel cleanliness — start /research as an asyncio task, sleep
     2000 ms (well into the 3–8 s server work), task.cancel(), inspect.
     Verifies CancelledError is raised cleanly, no zombie tasks or
     hanging connections.

  C. Client reusability after cancellation — immediately after Experiment
     B (same httpx.AsyncClient instance), fire one more normal call to
     confirm the connection pool is intact.

Outputs:
  backend/outputs/probes/research/research_cancel_log.jsonl

Usage:
  conda activate elyosai
  python backend/probes/probe_research_cancellation.py
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
OUTPUTS_DIR = PROJECT_ROOT / "backend" / "outputs" / "probes" / "research"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = OUTPUTS_DIR / "research_cancel_log.jsonl"

# ─── API constants ─────────────────────────────────────────────────────
BASE = "https://elyos-interview-907656039105.europe-west2.run.app"
ENDPOINT = "/research"
THROTTLE_BUFFER_S = 1.0
REQUEST_TIMEOUT_S = 30.0
CANCEL_AFTER_MS = 2000   # mid-flight cancel point for Experiment B (server is 3–8 s)
TIMEOUT_CANCEL_S = 0.1   # 100 ms — too short to complete a /research call


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
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def short(s, n=200):
    return s if len(s) <= n else s[:n] + "..."


# ─── Action primitives ────────────────────────────────────────────────
async def normal_call(client, api_key, label, ts):
    """A regular call. Returns dict with status, throttle flag, etc."""
    t0 = time.monotonic()
    try:
        resp = await client.get(
            f"{BASE}{ENDPOINT}",
            params={"topic": "solar energy"},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT_S,
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
            params={"topic": "quantum computing"},
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
    """Start a /research request as an asyncio task, cancel after N ms (mid-flight)."""
    t0 = time.monotonic()
    task = asyncio.create_task(
        client.get(
            f"{BASE}{ENDPOINT}",
            params={"topic": "quantum computing"},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT_S,
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
    """If currently throttled, sleep through the window."""
    for i in range(max_waits):
        r = await normal_call(client, api_key, f"state_check_{i}", ts)
        if not r.get("is_throttled"):
            return r
        wait = r.get("retry_after_seconds", 30) + THROTTLE_BUFFER_S
        print(f"  [state_check_{i}] throttled, waiting {wait:.0f}s...")
        await asyncio.sleep(wait)
    return r


# ─── Experiments ──────────────────────────────────────────────────────
async def experiment_a(client, api_key, ts):
    """A: Does a cancelled call consume a throttle slot?"""
    print("\n─── Experiment A: Does cancellation consume a throttle slot? ───")

    print("  Pre-flight: ensure we're not currently throttled")
    state = await wait_if_throttled(client, api_key, ts)
    print(f"    state: status={state.get('status')} throttled={state.get('is_throttled')}")
    # state_check_0 consumed 1 slot. ~4 left in this window.

    print("  Step 1: Use 3 more normal calls (now at ~4/5 of window)")
    for i in range(3):
        r = await normal_call(client, api_key, f"A_setup_{i+1}", ts)
        flag = "THROTTLED" if r.get("is_throttled") else f"{r.get('status')}"
        print(f"    A_setup_{i+1}: {flag} latency={r.get('latency_s')}s")

    print(f"  Step 2: Issue a call with {int(TIMEOUT_CANCEL_S*1000)} ms timeout (forces mid-flight cancel)")
    r_cancel = await timeout_cancel(client, api_key, "A_cancelled_5th",
                                     timeout_s=TIMEOUT_CANCEL_S, ts=ts)
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
    """B: Asyncio task.cancel() cleanliness, mid-flight (~2 s in)."""
    print("\n─── Experiment B: asyncio task.cancel() cleanliness (mid-flight) ───")
    state = await wait_if_throttled(client, api_key, ts)
    if state.get("is_throttled"):
        print("    (still throttled after wait — task_cancel will run anyway)")
    print(f"  Starting /research request as task, cancelling after {CANCEL_AFTER_MS} ms")
    r = await task_cancel(client, api_key, "B_task_cancel_2s",
                          cancel_after_ms=CANCEL_AFTER_MS, ts=ts)
    print(f"    B_task_cancel_2s: exc={r.get('exception_type')} "
          f"clean={r.get('exception_clean')} latency={r.get('latency_s')}s")
    return r


async def experiment_c(client, api_key, ts):
    """C: Is the same httpx client still usable after cancellation?"""
    print("\n─── Experiment C: Client reusability after cancel ───")
    r = await normal_call(client, api_key, "C_reuse_after_cancel", ts)
    if r.get("status") == 200 and not r.get("is_throttled"):
        print(f"    C_reuse_after_cancel: ✓ status=200, client pool intact "
              f"(latency {r.get('latency_s')}s)")
    elif r.get("is_throttled"):
        print(f"    C_reuse_after_cancel: throttled — client pool intact (throttle is "
              f"unrelated to cancellation)")
    else:
        print(f"    C_reuse_after_cancel: ✗ status={r.get('status')} "
              f"error={r.get('error')}")
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
    print(f"Probing /research cancellation behaviour")
    print(f"Endpoint:    {BASE}{ENDPOINT}")
    print(f"Log:         {LOG_FILE}")
    print(f"Run ts:      {ts}")
    print(f"Settings:    timeout_cancel={TIMEOUT_CANCEL_S}s  task_cancel_after={CANCEL_AFTER_MS}ms")

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
