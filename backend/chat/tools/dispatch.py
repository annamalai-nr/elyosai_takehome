"""Tool execution dispatch — routes LLM tool calls to Elyos API functions."""

import json
import logging

import httpx
from langsmith import traceable

from backend.chat.models import ToolCall
from backend.chat.parsers import envelope, normalise_weather, parse_research
from backend.chat.tools.elyos_client import get_weather, research_topic

log = logging.getLogger(__name__)


def _dump(parsed) -> dict:
    return parsed.model_dump(exclude_none=True) if hasattr(parsed, "model_dump") else parsed


@traceable(run_type="tool", name="execute_tool")
async def execute_tool_call(client: httpx.AsyncClient, cfg: dict, call: ToolCall, emit=None) -> dict:
    """Execute a single tool call and return an OpenAI-format tool message."""
    try:
        args = json.loads(call.arguments)
    except json.JSONDecodeError:
        log.warning("Invalid JSON in tool call arguments: %s", call.arguments[:100])
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "content": envelope(call.name, {"error": "invalid_args", "message": f"Could not parse arguments: {call.arguments[:100]}"}),
        }

    if call.name == "get_weather":
        location = args.get("location", "")
        log.debug("Executing get_weather(location=%s)", location)
        if emit:
            await emit({"type": "status", "message": f"Looking up weather for {location}..."})
        else:
            print(f"\r  Looking up weather for {location}...", flush=True)
        data = await get_weather(client, cfg, location)
        parsed = normalise_weather(data, location)
        if emit:
            await emit({"type": "tool_result", "name": "get_weather", "data": _dump(parsed)})
        content = envelope(call.name, parsed)

    elif call.name == "research_topic":
        topic = args.get("topic", "")
        log.debug("Executing research_topic(topic=%s)", topic[:50])
        if emit:
            await emit({"type": "status", "message": f"Researching {topic}..."})
        else:
            print(f"\r  Researching {topic}... (Ctrl+C to cancel)", flush=True)
        data = await research_topic(client, cfg, topic)
        parsed = parse_research(data)
        if emit:
            await emit({"type": "tool_result", "name": "research_topic", "data": _dump(parsed)})
        content = envelope(call.name, parsed)

    else:
        log.warning("Unknown tool requested: %s", call.name)
        content = envelope(call.name, {"error": "unknown_tool", "message": f"No tool named {call.name}"})

    return {"role": "tool", "tool_call_id": call.id, "content": content}
