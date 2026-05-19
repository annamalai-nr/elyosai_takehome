import logging

import httpx
from langsmith import traceable

from backend.chat.llm_client import stream_llm_turn
from backend.chat.tools import execute_tool_call

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS: int = 5


@traceable(run_type="chain", name="chat_turn")
async def stream_turn(
    client: httpx.AsyncClient,
    cfg: dict,
    messages: list[dict],
    state: dict,
) -> None:
    """ReAct loop: LLM turn → tool execution → observation → repeat."""
    for _round in range(MAX_TOOL_ROUNDS):
        turn = await stream_llm_turn(cfg, messages, state)
        messages.append(turn.assistant_message)

        if not turn.tool_calls:
            state["partial"] = ""
            return

        for tool_call in turn.tool_calls:
            observation = await execute_tool_call(client, cfg, tool_call)
            messages.append(observation)

    log.warning("Max tool rounds (%d) reached", MAX_TOOL_ROUNDS)
