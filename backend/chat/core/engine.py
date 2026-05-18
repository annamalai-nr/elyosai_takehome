import asyncio
import json
import os
from typing import Any

import httpx
import litellm

from backend.chat.core.parsers import envelope, normalise_weather, parse_research, truncate
from backend.chat.prompts import TOOLS

MAX_TOOL_ROUNDS = 5
MAX_THROTTLE_RETRIES = 5


async def call_api(
    client: httpx.AsyncClient, base_url: str, endpoint: str, params: dict, api_key: str
) -> dict:
    """GET an Elyos API endpoint with throttle-retry. Always returns a dict."""
    timeout = 20.0 if endpoint == "/research" else 15.0
    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        try:
            resp = await client.get(
                f"{base_url}{endpoint}",
                params=params,
                headers={"X-API-Key": api_key},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return {"error": "request_timeout", "message": f"{endpoint} request timed out"}
        except httpx.HTTPError as e:
            return {"error": "http_error", "message": str(e)}

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                return {"error": "invalid_json", "message": f"{endpoint} returned non-JSON body"}
            if isinstance(data, dict) and data.get("status") == "throttled":
                wait = data.get("retry_after_seconds", 30) + 1
                if attempt < MAX_THROTTLE_RETRIES:
                    print(f"\r  Rate limited, waiting {wait}s...", flush=True)
                    await asyncio.sleep(wait)
                    continue
                return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}
            return data
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return {"error": f"http_{resp.status_code}", "message": body}
    return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}


async def execute_tool(client: httpx.AsyncClient, cfg: dict, name: str, args: dict) -> str:
    """Call the Elyos API for a tool and return an envelope-wrapped JSON string."""
    base = cfg["elyos_api"]["base_url"]
    key = os.environ[cfg["elyos_api"]["api_key_env"]]
    if name == "get_weather":
        location = args.get("location", "")
        print(f"\r  Looking up weather for {location}...", flush=True)
        data = await call_api(client, base, "/weather", {"location": location}, key)
        return envelope(name, normalise_weather(data, location))
    if name == "research_topic":
        topic = args.get("topic", "")
        print(f"\r  Researching {topic}... (Ctrl+C to cancel)", flush=True)
        data = await call_api(client, base, "/research", {"topic": topic}, key)
        return envelope(name, parse_research(data))
    return envelope(name, {"error": "unknown_tool", "message": f"No tool named {name}"})


def _llm_kwargs(cfg: dict) -> dict[str, Any]:
    """Build extra kwargs for the LiteLLM acompletion call from config."""
    llm = cfg["llm"]
    kwargs: dict[str, Any] = {"max_tokens": llm.get("max_tokens", 1500)}
    reasoning = llm.get("reasoning_effort", "none")
    if reasoning and reasoning != "none":
        kwargs["reasoning_effort"] = reasoning
    if "temperature" in llm:
        kwargs["temperature"] = llm["temperature"]
    return kwargs


async def stream_turn(
    client: httpx.AsyncClient,
    cfg: dict,
    messages: list[dict],
    state: dict,
    round_count: int = 0,
) -> None:
    """Stream one LLM turn, recursing if the model invokes tools."""
    stream = await litellm.acompletion(
        model=cfg["llm"]["model_name"],
        messages=messages,
        tools=TOOLS,
        stream=True,
        drop_params=True,
        **_llm_kwargs(cfg),
    )
    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
            content_parts.append(delta.content)
            state["partial"] = "".join(content_parts)
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls:
                    tool_calls[idx] = {"id": tc_delta.id, "name": tc_delta.function.name or "", "args": ""}
                else:
                    if tc_delta.id:
                        tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function.name:
                        tool_calls[idx]["name"] = tc_delta.function.name
                if tc_delta.function.arguments:
                    tool_calls[idx]["args"] += tc_delta.function.arguments

    if not tool_calls:
        full = "".join(content_parts)
        print()
        messages.append({"role": "assistant", "content": full})
        state["partial"] = ""
        return

    # Tool calls present -- execute them, then recurse for the model's follow-up.
    assistant_msg = {
        "role": "assistant",
        "content": "".join(content_parts) or None,
        "tool_calls": [
            {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"]}}
            for tc in tool_calls.values()
        ],
    }
    messages.append(assistant_msg)

    for tc in tool_calls.values():
        try:
            parsed_args = json.loads(tc["args"])
        except json.JSONDecodeError:
            error_data = {"error": "invalid_args", "message": f"Could not parse tool arguments: {truncate(tc['args'], 100)}"}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": envelope(tc["name"], error_data)})
            continue
        result_str = await execute_tool(client, cfg, tc["name"], parsed_args)
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})

    round_count += 1
    if round_count >= MAX_TOOL_ROUNDS:
        print("\n  [Max tool rounds reached]", flush=True)
        return
    return await stream_turn(client, cfg, messages, state, round_count)
