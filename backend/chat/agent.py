"""ReAct agent loop with bounded concurrency and proactive budget pacing."""

import asyncio
import collections
import logging
import time

import httpx
from langsmith import traceable

from backend.chat.llm_client import stream_llm_turn
from backend.chat.tools import execute_tool_call

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS: int = 5

_TOOL_ENDPOINT = {"get_weather": "weather", "research_topic": "research"}


async def _wait_for_budget(state: dict, endpoint_cfg: dict) -> None:
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


async def _bounded_execute(
    sem: asyncio.Semaphore, client: httpx.AsyncClient, cfg: dict, state: dict,
    endpoint_cfg: dict, tool_call,
) -> dict:
    async with sem:
        await _wait_for_budget(state, endpoint_cfg)
        return await execute_tool_call(client, cfg, tool_call)


@traceable(run_type="chain", name="chat_turn")
async def stream_turn(
    client: httpx.AsyncClient,
    cfg: dict,
    messages: list[dict],
    state: dict,
) -> None:
    """ReAct loop: LLM turn → tool execution → observation → repeat."""
    endpoints = cfg["elyos_api"]["endpoints"]

    for _round in range(MAX_TOOL_ROUNDS):
        turn = await stream_llm_turn(cfg, messages, state)
        messages.append(turn.assistant_message)

        if not turn.tool_calls:
            state["partial"] = ""
            return

        log.debug("Round %d: executing %d tool call(s)", _round + 1, len(turn.tool_calls))
        sems: dict[str, asyncio.Semaphore] = {}
        ep_per_tc: list[str] = []
        for tc in turn.tool_calls:
            ep = _TOOL_ENDPOINT.get(tc.name, "weather")
            ep_per_tc.append(ep)
            if ep not in sems:
                sems[ep] = asyncio.Semaphore(endpoints[ep]["max_concurrent"])

        observations = await asyncio.gather(*[
            _bounded_execute(sems[ep], client, cfg, state, endpoints[ep], tc)
            for ep, tc in zip(ep_per_tc, turn.tool_calls)
        ])
        messages.extend(observations)

    log.warning("Max tool rounds (%d) reached", MAX_TOOL_ROUNDS)
