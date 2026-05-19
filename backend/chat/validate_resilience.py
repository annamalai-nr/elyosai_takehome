import asyncio
import sys
import time


def _test_config_rejects_missing_field():
    """Config validation rejects missing required fields."""
    from backend.chat.load_config import _validate_endpoints

    cfg = {"elyos_api": {"endpoints": {"weather": {
        "path": "/weather", "timeout_s": 15, "max_concurrent": 4,
        "rate_limit_group": "elyos_api", "max_requests_per_window": 5, "window_s": 30,
        "max_throttle_retries": 5, "max_timeout_retries": 1,
    }}}}
    try:
        _validate_endpoints(cfg)
        return False, "should have rejected missing retry_jitter_s"
    except SystemExit:
        return True, "rejects missing field"


def _test_config_rejects_zero_concurrent():
    """Config validation rejects max_concurrent: 0."""
    from backend.chat.load_config import _validate_endpoints

    cfg = {"elyos_api": {"endpoints": {"weather": {
        "path": "/weather", "timeout_s": 15, "max_concurrent": 0,
        "rate_limit_group": "elyos_api", "max_requests_per_window": 5, "window_s": 30,
        "max_throttle_retries": 5, "max_timeout_retries": 1, "retry_jitter_s": 0.5,
    }}}}
    try:
        _validate_endpoints(cfg)
        return False, "should have rejected max_concurrent: 0"
    except SystemExit:
        return True, "rejects max_concurrent: 0"


def _test_config_rejects_empty_rate_group():
    """Config validation rejects empty rate_limit_group."""
    from backend.chat.load_config import _validate_endpoints

    cfg = {"elyos_api": {"endpoints": {"weather": {
        "path": "/weather", "timeout_s": 15, "max_concurrent": 4,
        "rate_limit_group": "", "max_requests_per_window": 5, "window_s": 30,
        "max_throttle_retries": 5, "max_timeout_retries": 1, "retry_jitter_s": 0.5,
    }}}}
    try:
        _validate_endpoints(cfg)
        return False, "should have rejected empty rate_limit_group"
    except SystemExit:
        return True, "rejects empty rate_limit_group"


def _test_budget_delays_over_capacity():
    """Shared budget pacing delays the N+1th request."""
    from backend.chat.agent import _wait_for_budget

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


def _test_shared_group_across_endpoints():
    """Weather and research sharing rate_limit_group consume the same budget."""
    from backend.chat.agent import _wait_for_budget

    state: dict = {}
    weather_cfg = {"rate_limit_group": "test_shared", "max_requests_per_window": 2, "window_s": 0.3}
    research_cfg = {"rate_limit_group": "test_shared", "max_requests_per_window": 2, "window_s": 0.3}

    async def _run():
        await _wait_for_budget(state, weather_cfg)
        await _wait_for_budget(state, weather_cfg)
        t0 = time.monotonic()
        await _wait_for_budget(state, research_cfg)
        elapsed = time.monotonic() - t0
        return elapsed

    elapsed = asyncio.run(_run())
    if elapsed < 0.05:
        return False, f"research should have been delayed by weather's budget use, elapsed={elapsed:.3f}s"
    return True, f"shared group enforced, research delayed {elapsed:.2f}s"


def _test_budget_persists_across_calls():
    """Rate budget state persists when the same state object is reused."""
    from backend.chat.agent import _wait_for_budget

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


def _test_concurrent_waiters_serialized():
    """Concurrent waiters are serialized by the per-group lock."""
    from backend.chat.agent import _wait_for_budget

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


def validate_resilience() -> None:
    tests = [
        _test_config_rejects_missing_field,
        _test_config_rejects_zero_concurrent,
        _test_config_rejects_empty_rate_group,
        _test_budget_delays_over_capacity,
        _test_shared_group_across_endpoints,
        _test_budget_persists_across_calls,
        _test_concurrent_waiters_serialized,
    ]
    for test in tests:
        passed, msg = test()
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {test.__doc__} — {msg}")
        if not passed:
            sys.exit(1)
    print(f"All {len(tests)} resilience validations passed.")


if __name__ == "__main__":
    validate_resilience()
