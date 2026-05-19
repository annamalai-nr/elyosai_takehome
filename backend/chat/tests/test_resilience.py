"""Resilience tests — config validation, budget pacing, and concurrency safety."""

import asyncio
import sys
import time

from backend.chat.agent import _wait_for_budget
from backend.chat.load_config import _validate_endpoints

_VALID_ENDPOINT = {
    "path": "/weather",
    "timeout_s": 15,
    "max_concurrent": 4,
    "rate_limit_group": "elyos_api",
    "max_requests_per_window": 5,
    "window_s": 30,
    "rate_limit_safety_s": 2,
    "max_throttle_retries": 5,
    "max_timeout_retries": 1,
    "retry_jitter_s": 0.5,
}


def _cfg_with(**overrides) -> dict:
    ep = {**_VALID_ENDPOINT, **overrides}
    return {"elyos_api": {"endpoints": {"weather": ep}}}


def _cfg_without(*keys) -> dict:
    ep = {k: v for k, v in _VALID_ENDPOINT.items() if k not in keys}
    return {"elyos_api": {"endpoints": {"weather": ep}}}


def _expect_rejection(cfg: dict) -> bool:
    try:
        _validate_endpoints(cfg)
        return False
    except SystemExit:
        return True


def test_config_rejects_missing_field():
    """Config rejects missing required fields."""
    if not _expect_rejection(_cfg_without("retry_jitter_s")):
        return False, "should have rejected missing retry_jitter_s"
    return True, "rejects missing field"


def test_config_rejects_zero_concurrent():
    """Config rejects max_concurrent: 0."""
    if not _expect_rejection(_cfg_with(max_concurrent=0)):
        return False, "should have rejected max_concurrent: 0"
    return True, "rejects max_concurrent: 0"


def test_config_rejects_empty_rate_group():
    """Config rejects empty rate_limit_group."""
    if not _expect_rejection(_cfg_with(rate_limit_group="")):
        return False, "should have rejected empty rate_limit_group"
    return True, "rejects empty rate_limit_group"


def test_budget_delays_over_capacity():
    """Shared budget pacing delays the N+1th request."""

    state: dict = {}
    ep_cfg = {"rate_limit_group": "test_delay", "max_requests_per_window": 2, "window_s": 0.3}

    async def _run():
        await _wait_for_budget(state, ep_cfg)
        await _wait_for_budget(state, ep_cfg)
        t0 = time.monotonic()
        await _wait_for_budget(state, ep_cfg)
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(_run())
    if elapsed < 0.05:
        return False, f"3rd request should have been delayed, but elapsed={elapsed:.3f}s"
    return True, f"3rd request delayed {elapsed:.2f}s"


def test_shared_group_across_endpoints():
    """Weather and research sharing rate_limit_group consume the same budget."""

    state: dict = {}
    shared_cfg = {"rate_limit_group": "test_shared", "max_requests_per_window": 2, "window_s": 0.3}

    async def _run():
        await _wait_for_budget(state, shared_cfg)
        await _wait_for_budget(state, shared_cfg)
        t0 = time.monotonic()
        # Third call uses the same group, simulating a different endpoint sharing the budget
        await _wait_for_budget(state, shared_cfg)
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(_run())
    if elapsed < 0.05:
        return False, f"research should have been delayed by weather's budget use, elapsed={elapsed:.3f}s"
    return True, f"shared group enforced, research delayed {elapsed:.2f}s"


def test_budget_persists_across_turns():
    """Rate budget state persists when the same state object is reused."""

    state: dict = {}
    ep_cfg = {"rate_limit_group": "test_persist", "max_requests_per_window": 2, "window_s": 0.3}

    async def _turn1():
        await _wait_for_budget(state, ep_cfg)
        await _wait_for_budget(state, ep_cfg)

    async def _turn2():
        t0 = time.monotonic()
        await _wait_for_budget(state, ep_cfg)
        return time.monotonic() - t0

    asyncio.run(_turn1())
    elapsed = asyncio.run(_turn2())
    if elapsed < 0.05:
        return False, f"turn 2 should see turn 1 budget, but elapsed={elapsed:.3f}s"
    return True, f"budget persisted across turns, delayed {elapsed:.2f}s"


def test_concurrent_waiters_are_serialized():
    """Concurrent waiters are serialized by the per-group lock."""

    state: dict = {}
    ep_cfg = {"rate_limit_group": "test_conc", "max_requests_per_window": 1, "window_s": 0.2}

    async def _run():
        start_times = []

        async def _acquire():
            await _wait_for_budget(state, ep_cfg)
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
    test_config_rejects_missing_field,
    test_config_rejects_zero_concurrent,
    test_config_rejects_empty_rate_group,
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
