import asyncio
import json
import logging
import os

import httpx
from langsmith import traceable

from backend.chat.models import ToolCall
from backend.chat.parsers import envelope, normalise_weather, parse_research

log = logging.getLogger(__name__)

MAX_THROTTLE_RETRIES: int = 5

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city. Fast response (~200ms).",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string", "description": "City name, e.g. London, Tokyo"}},
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_topic",
            "description": "Look up a best-effort research summary. May return generic, cached, truncated, or timeout results.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "Topic to research, e.g. 'solar energy'"}},
                "required": ["topic"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Elyos API client with throttle-retry
# ---------------------------------------------------------------------------

@traceable(run_type="tool", name="elyos_api_call")
async def call_api(
    client: httpx.AsyncClient, base_url: str, endpoint: str, params: dict, api_key: str,
) -> dict:
    timeout = 20.0 if endpoint == "/research" else 15.0

    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        log.debug("API request: GET %s params=%s (attempt %d)", endpoint, params, attempt + 1)
        try:
            resp = await client.get(
                f"{base_url}{endpoint}",
                params=params,
                headers={"X-API-Key": api_key},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            log.warning("Timeout on %s after %.0fs", endpoint, timeout)
            return {"error": "request_timeout", "message": f"{endpoint} request timed out"}
        except httpx.HTTPError as exc:
            log.warning("HTTP error on %s: %s", endpoint, exc)
            return {"error": "http_error", "message": str(exc)}

        if resp.status_code != 200:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            return {"error": f"http_{resp.status_code}", "message": body}

        try:
            data = resp.json()
        except Exception:
            return {"error": "invalid_json", "message": f"{endpoint} returned non-JSON body"}

        if not (isinstance(data, dict) and data.get("status") == "throttled"):
            return data

        wait = data.get("retry_after_seconds", 30) + 1
        if attempt >= MAX_THROTTLE_RETRIES:
            log.warning("Throttle retries exhausted on %s", endpoint)
            return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}
        log.warning("Throttled on %s, retrying in %ds (attempt %d/%d)", endpoint, wait, attempt + 1, MAX_THROTTLE_RETRIES)
        await asyncio.sleep(wait)

    return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}


# ---------------------------------------------------------------------------
# Tool execution dispatch
# ---------------------------------------------------------------------------

@traceable(run_type="tool", name="execute_tool")
async def execute_tool_call(client: httpx.AsyncClient, cfg: dict, call: ToolCall) -> dict:
    """Execute a tool call and return a tool observation message."""
    try:
        args = json.loads(call.arguments)
    except json.JSONDecodeError:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "content": envelope(call.name, {"error": "invalid_args", "message": f"Could not parse arguments: {call.arguments[:100]}"}),
        }

    base_url = cfg["elyos_api"]["base_url"]
    api_key = os.environ[cfg["elyos_api"]["api_key_env"]]

    if call.name == "get_weather":
        location = args.get("location", "")
        print(f"\r  Looking up weather for {location}...", flush=True)
        data = await call_api(client, base_url, "/weather", {"location": location}, api_key)
        content = envelope(call.name, normalise_weather(data, location))

    elif call.name == "research_topic":
        topic = args.get("topic", "")
        print(f"\r  Researching {topic}... (Ctrl+C to cancel)", flush=True)
        data = await call_api(client, base_url, "/research", {"topic": topic}, api_key)
        content = envelope(call.name, parse_research(data))

    else:
        content = envelope(call.name, {"error": "unknown_tool", "message": f"No tool named {call.name}"})

    return {"role": "tool", "tool_call_id": call.id, "content": content}
