import asyncio
import logging

import httpx
from langsmith import traceable

from backend.chat.llm_client import stream_llm_turn
from backend.chat.tools import execute_tool_call

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS: int = 5

_TOOL_ENDPOINT = {"get_weather": "weather", "research_topic": "research"}


async def _bounded_execute(sem: asyncio.Semaphore, client: httpx.AsyncClient, cfg: dict, tool_call) -> dict:
    async with sem:
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

        # Bounded concurrency per endpoint to stay within API throttle budgets.
        sems: dict[str, asyncio.Semaphore] = {}
        for tc in turn.tool_calls:
            ep = _TOOL_ENDPOINT.get(tc.name, "weather")
            if ep not in sems:
                sems[ep] = asyncio.Semaphore(endpoints[ep]["max_concurrent"])

        observations = await asyncio.gather(*[
            _bounded_execute(sems[_TOOL_ENDPOINT.get(tc.name, "weather")], client, cfg, tc)
            for tc in turn.tool_calls
        ])
        for obs in observations:
            messages.append(obs)

    log.warning("Max tool rounds (%d) reached", MAX_TOOL_ROUNDS)
