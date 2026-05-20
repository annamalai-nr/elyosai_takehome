"""LiteLLM streaming adapter — streams one LLM turn and accumulates tool calls."""

import logging
from typing import Any

logging.getLogger("LiteLLM").setLevel(logging.ERROR)
import litellm  # noqa: E402

from backend.chat.models import Emit, LLMTurn, ToolCall
from backend.chat.tools import TOOLS

litellm.callbacks = ["langsmith"]

log = logging.getLogger(__name__)


def _llm_kwargs(cfg: dict) -> dict[str, Any]:
    llm_cfg = cfg["llm"]
    kwargs: dict[str, Any] = {"max_tokens": llm_cfg.get("max_tokens", 1500)}

    reasoning = llm_cfg.get("reasoning_effort")
    if reasoning and reasoning != "none":
        kwargs["reasoning_effort"] = reasoning
    if "temperature" in llm_cfg:
        kwargs["temperature"] = llm_cfg["temperature"]

    return kwargs


def _accumulate_tool_call(tool_calls: dict[int, dict], tc_delta: Any) -> None:
    idx = tc_delta.index
    entry = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
    if tc_delta.id:
        entry["id"] = tc_delta.id
    if tc_delta.function.name:
        entry["name"] = tc_delta.function.name
    if tc_delta.function.arguments:
        entry["args"] += tc_delta.function.arguments


async def stream_llm_turn(cfg: dict, messages: list[dict], state: dict, emit: Emit | None = None) -> LLMTurn:
    """Stream one LLM completion, printing content and accumulating tool calls."""
    model = cfg["llm"]["model_name"]
    log.debug("Calling LLM: model=%s messages=%d", model, len(messages))
    stream = await litellm.acompletion(
        model=cfg["llm"]["model_name"],
        messages=messages,
        tools=TOOLS,
        stream=True,
        drop_params=True,
        **_llm_kwargs(cfg),
    )

    content_parts: list[str] = []
    raw_tool_calls: dict[int, dict] = {}

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            if emit:
                await emit({"type": "text", "content": delta.content})
            else:
                print(delta.content, end="", flush=True)
            content_parts.append(delta.content)
            state["partial"] = "".join(content_parts)
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                _accumulate_tool_call(raw_tool_calls, tc_delta)

    content_text = "".join(content_parts)

    if raw_tool_calls:
        log.debug("LLM requested %d tool call(s): %s", len(raw_tool_calls),
                  ", ".join(tc["name"] for tc in raw_tool_calls.values()))
    elif not emit:
        print()

    return LLMTurn(
        content=content_text,
        tool_calls=[
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["args"])
            for tc in raw_tool_calls.values()
        ],
    )
