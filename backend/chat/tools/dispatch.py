import json

import httpx
from langsmith import traceable

from backend.chat.models import ToolCall
from backend.chat.parsers import envelope, normalise_weather, parse_research
from backend.chat.tools.elyos_client import get_weather, research_topic


@traceable(run_type="tool", name="execute_tool")
async def execute_tool_call(client: httpx.AsyncClient, cfg: dict, call: ToolCall) -> dict:
    try:
        args = json.loads(call.arguments)
    except json.JSONDecodeError:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "content": envelope(call.name, {"error": "invalid_args", "message": f"Could not parse arguments: {call.arguments[:100]}"}),
        }

    if call.name == "get_weather":
        location = args.get("location", "")
        print(f"\r  Looking up weather for {location}...", flush=True)
        data = await get_weather(client, cfg, location)
        content = envelope(call.name, normalise_weather(data, location))

    elif call.name == "research_topic":
        topic = args.get("topic", "")
        print(f"\r  Researching {topic}... (Ctrl+C to cancel)", flush=True)
        data = await research_topic(client, cfg, topic)
        content = envelope(call.name, parse_research(data))

    else:
        content = envelope(call.name, {"error": "unknown_tool", "message": f"No tool named {call.name}"})

    return {"role": "tool", "tool_call_id": call.id, "content": content}
