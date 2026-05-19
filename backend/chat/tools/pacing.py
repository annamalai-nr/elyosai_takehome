"""Proactive rate-limit pacing and bounded tool execution."""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING

import httpx

from backend.chat.tools.dispatch import execute_tool_call

if TYPE_CHECKING:
    from backend.chat.models import ToolCall

log = logging.getLogger(__name__)


async def wait_for_budget(state: dict, endpoint_cfg: dict) -> None:
    """Proactive shared-budget pacing. Sleeps if the rate-limit group's
    sliding window is at capacity. Concurrency-safe via per-group lock.
    Approximate — reactive retry_after_seconds from the server remains
    the authoritative pacing signal."""
    group = endpoint_cfg["rate_limit_group"]
    window = endpoint_cfg["window_s"] + endpoint_cfg.get("rate_limit_safety_s", 0)
    max_req = endpoint_cfg["max_requests_per_window"]

    budgets = state.setdefault("rate_budgets", {})
    locks = state.setdefault("rate_budget_locks", {})
    q = budgets.setdefault(group, collections.deque())
    if group not in locks:
        locks[group] = asyncio.Lock()
    lock = locks[group]

    while True:
        async with lock:
            now = time.monotonic()
            while q and (now - q[0]) > window:
                q.popleft()
            if len(q) < max_req:
                q.append(time.monotonic())
                return
            wait = window - (now - q[0])

        if wait > 0:
            log.info("Rate budget full for group %s, waiting %.1fs", group, wait)
            print(f"\r  Rate budget full, pacing for {int(wait)}s...", flush=True)
            await asyncio.sleep(wait)


async def bounded_execute(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    cfg: dict,
    state: dict,
    endpoint_cfg: dict,
    tool_call: "ToolCall",
) -> dict:
    async with sem:
        await wait_for_budget(state, endpoint_cfg)
        return await execute_tool_call(client, cfg, tool_call)
