"""ReAct agent loop with bounded concurrency."""

import asyncio
import json
import logging

import httpx
from langsmith import traceable

from backend.chat.llm_client import stream_llm_turn
from backend.chat.models import ToolCall
from backend.chat.tools.dispatch import execute_tool_call

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS: int = 5

_TOOL_ENDPOINT = {"get_weather": "weather", "research_topic": "research"}


async def _execute_with_semaphore(
    sem: asyncio.Semaphore, client: httpx.AsyncClient, cfg: dict, tool_call: ToolCall, emit=None,
) -> dict:
    async with sem:
        return await execute_tool_call(client, cfg, tool_call, emit=emit)


@traceable(run_type="chain", name="chat_turn")
async def stream_turn(
    client: httpx.AsyncClient,
    cfg: dict,
    messages: list[dict],
    state: dict,
    emit=None,
) -> None:
    """ReAct loop: LLM turn → tool execution → observation → repeat."""
    endpoints = cfg["elyos_api"]["endpoints"]

    for _round in range(MAX_TOOL_ROUNDS):
        turn = await stream_llm_turn(cfg, messages, state, emit=emit)
        messages.append(turn.assistant_message)

        if not turn.tool_calls:
            state["partial"] = ""
            return

        if emit:
            for tc in turn.tool_calls:
                try:
                    args = json.loads(tc.arguments)
                except Exception:
                    args = {}
                await emit({"type": "tool_start", "name": tc.name, "args": args})

        log.debug("Round %d: executing %d tool call(s)", _round + 1, len(turn.tool_calls))
        sems: dict[str, asyncio.Semaphore] = {}
        pairs = [
            (_TOOL_ENDPOINT.get(tc.name, "weather"), tc)
            for tc in turn.tool_calls
        ]
        for ep, _ in pairs:
            if ep not in sems:
                sems[ep] = asyncio.Semaphore(endpoints[ep]["max_concurrent"])

        observations = await asyncio.gather(*[
            _execute_with_semaphore(sems[ep], client, cfg, tc, emit=emit)
            for ep, tc in pairs
        ])
        messages.extend(observations)

    log.warning("Max tool rounds (%d) reached", MAX_TOOL_ROUNDS)
