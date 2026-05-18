import asyncio
import json
import os

import httpx

from backend.chat.core.parsers import _cap, envelope, normalise_weather, parse_research
from backend.chat.prompts import TOOLS

MAX_TOOL_ROUNDS = 5
MAX_THROTTLE_RETRIES = 5


async def call_api(client, base_url, endpoint, params, api_key):
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
            data = resp.json()
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


async def execute_tool(client, cfg, name, args):
    base = cfg["elyos_api"]["base_url"]
    key = os.environ[cfg["elyos_api"]["api_key_env"]]
    if name == "get_weather":
        location = args.get("location", "")
        print(f"\r  Looking up weather for {location}...", flush=True)
        data = await call_api(client, base, "/weather", {"location": location}, key)
        return envelope(name, normalise_weather(data, location))
    elif name == "research_topic":
        topic = args.get("topic", "")
        print(f"\r  Researching {topic}... (Ctrl+C to cancel)", flush=True)
        data = await call_api(client, base, "/research", {"topic": topic}, key)
        return envelope(name, parse_research(data))
    return envelope(name, {"error": "unknown_tool", "message": f"No tool named {name}"})


async def stream_turn(oai, client, cfg, messages, state, round_count=0):
    stream = await oai.chat.completions.create(
        model=cfg["llm"]["model_name"],
        messages=messages,
        tools=TOOLS,
        stream=True,
    )
    content_parts = []
    tool_calls = {}

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

    if tool_calls:
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
                args = json.loads(tc["args"])
            except json.JSONDecodeError:
                args = {}
                result_str = envelope(tc["name"], {"error": "invalid_args", "message": f"Could not parse tool arguments: {_cap(tc['args'], 100)}"})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})
                continue
            result_str = await execute_tool(client, cfg, tc["name"], args)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})

        round_count += 1
        if round_count >= MAX_TOOL_ROUNDS:
            print("\n  [Max tool rounds reached]", flush=True)
            return
        return await stream_turn(oai, client, cfg, messages, state, round_count)
    else:
        full = "".join(content_parts)
        print()
        messages.append({"role": "assistant", "content": full})
        state["partial"] = ""
