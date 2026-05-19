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


async def wait_for_budget(state: dict, rate_cfg: dict) -> None:
    """Proactive shared-budget pacing. Sleeps if the API's sliding window
    is at capacity. Concurrency-safe via lock."""
    window = rate_cfg["window_s"]
    max_req = rate_cfg["max_requests_per_window"]

    budgets = state.setdefault("rate_budgets", {})
    locks = state.setdefault("rate_budget_locks", {})
    q = budgets.setdefault("api", collections.deque())
    if "api" not in locks:
        locks["api"] = asyncio.Lock()
    lock = locks["api"]

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
            log.info("Rate budget full, waiting %.1fs", wait)
            print(f"\r  Rate budget full, pacing for {int(wait)}s...", flush=True)
            await asyncio.sleep(wait)


async def bounded_execute(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    cfg: dict,
    state: dict,
    tool_call: "ToolCall",
) -> dict:
    async with sem:
        await wait_for_budget(state, cfg["elyos_api"]["rate_limit"])
        return await execute_tool_call(client, cfg, tool_call)
