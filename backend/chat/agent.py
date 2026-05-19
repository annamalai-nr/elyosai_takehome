"""ReAct agent loop with bounded concurrency."""

import asyncio
import logging

import httpx
from langsmith import traceable

from backend.chat.llm_client import stream_llm_turn
from backend.chat.tools.pacing import bounded_execute

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS: int = 5

_TOOL_ENDPOINT = {"get_weather": "weather", "research_topic": "research"}


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
            bounded_execute(sems[ep], client, cfg, state, endpoints[ep], tc)
            for ep, tc in zip(ep_per_tc, turn.tool_calls)
        ])
        messages.extend(observations)

    log.warning("Max tool rounds (%d) reached", MAX_TOOL_ROUNDS)
