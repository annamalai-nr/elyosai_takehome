"""Resilience tests — budget pacing and concurrency safety."""

import asyncio
import sys
import time

from backend.chat.tools.pacing import wait_for_budget


def test_budget_delays_over_capacity():
    """Shared budget pacing delays the N+1th request."""

    state: dict = {}
    rate_cfg = {"max_requests_per_window": 2, "window_s": 0.3}

    async def _run():
        await wait_for_budget(state, rate_cfg)
        await wait_for_budget(state, rate_cfg)
        t0 = time.monotonic()
        await wait_for_budget(state, rate_cfg)
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(_run())
    if elapsed < 0.05:
        return False, f"3rd request should have been delayed, but elapsed={elapsed:.3f}s"
    return True, f"3rd request delayed {elapsed:.2f}s"


def test_shared_group_across_endpoints():
    """Weather and research draw from the same API-level budget."""

    state: dict = {}
    rate_cfg = {"max_requests_per_window": 2, "window_s": 0.3}

    async def _run():
        await wait_for_budget(state, rate_cfg)
        await wait_for_budget(state, rate_cfg)
        t0 = time.monotonic()
        await wait_for_budget(state, rate_cfg)
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(_run())
    if elapsed < 0.05:
        return False, f"research should have been delayed by weather's budget use, elapsed={elapsed:.3f}s"
    return True, f"shared group enforced, research delayed {elapsed:.2f}s"


def test_budget_persists_across_turns():
    """Rate budget state persists when the same state object is reused."""

    state: dict = {}
    rate_cfg = {"max_requests_per_window": 2, "window_s": 0.3}

    async def _turn1():
        await wait_for_budget(state, rate_cfg)
        await wait_for_budget(state, rate_cfg)

    async def _turn2():
        t0 = time.monotonic()
        await wait_for_budget(state, rate_cfg)
        return time.monotonic() - t0

    asyncio.run(_turn1())
    elapsed = asyncio.run(_turn2())
    if elapsed < 0.05:
        return False, f"turn 2 should see turn 1 budget, but elapsed={elapsed:.3f}s"
    return True, f"budget persisted across turns, delayed {elapsed:.2f}s"


def test_concurrent_waiters_are_serialized():
    """Concurrent waiters are serialized by the lock."""

    state: dict = {}
    rate_cfg = {"max_requests_per_window": 1, "window_s": 0.2}

    async def _run():
        start_times = []

        async def _acquire():
            await wait_for_budget(state, rate_cfg)
            start_times.append(time.monotonic())

        await asyncio.gather(_acquire(), _acquire(), _acquire())
        return start_times

    times = asyncio.run(_run())
    gaps = [times[i] - times[0] for i in range(len(times))]
    if gaps[1] < 0.1:
        return False, f"2nd waiter started too early: gap={gaps[1]:.3f}s (expected ~0.2s)"
    if gaps[2] < 0.3:
        return False, f"3rd waiter started too early: gap={gaps[2]:.3f}s (expected ~0.4s)"
    return True, f"gaps: {gaps[1]:.2f}s, {gaps[2]:.2f}s"


TESTS = [
    test_budget_delays_over_capacity,
    test_shared_group_across_endpoints,
    test_budget_persists_across_turns,
    test_concurrent_waiters_are_serialized,
]


def run() -> None:
    for test in TESTS:
        passed, msg = test()
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {test.__doc__} — {msg}")
        if not passed:
            sys.exit(1)
    print(f"All {len(TESTS)} resilience tests passed.")
