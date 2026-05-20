"""WebSocket server — connects the frontend to the chat agent.

Listens on ws://localhost:8765. One `_handler` coroutine per connection;
all per-connection state (messages, in-flight turn task) is local to that
coroutine.

Protocol
--------
Inbound (client → server), JSON object per message:

    {"content": str}        — new user message; runs one turn
    {"type": "cancel"}      — cancel the in-flight turn task, if any

Outbound (server → client), JSON object per event. Events are emitted
in time order; every turn ends with a `done` event:

    {"type": "text",        "content": str}              — streamed LLM token
    {"type": "tool_start",  "name": str, "args": dict}   — tool call initiated
    {"type": "status",      "message": str}              — human-readable status
    {"type": "tool_result", "name": str, "data": dict}   — parsed tool result
    {"type": "error",       "message": str}              — turn failed
    {"type": "cancelled"}                                — turn was cancelled
    {"type": "done"}                                     — turn complete (always last)
"""

import asyncio
import json
import logging
from functools import partial

import httpx
import websockets

from backend.chat.agent import stream_turn
from backend.chat.interfaces.cli_chat import _trim_history
from backend.chat.load_config import load_config
from backend.chat.models import Emit
from backend.chat.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)


async def _send(ws, event: dict) -> None:
    """Serialise `event` and send it over the WebSocket."""
    await ws.send(json.dumps(event))


async def _run_turn(
    client: httpx.AsyncClient,
    cfg: dict,
    messages: list[dict],
    state: dict,
    max_hist: int,
    content: str,
    emit: Emit,
) -> None:
    """Run one turn end-to-end, with cancellation rollback.

    On asyncio.CancelledError, removes the in-flight user message from
    `messages` (so a cancelled turn does not corrupt subsequent rounds).
    If partial text was already streamed, preserves a `[interrupted]`
    assistant message so the conversation history records that the turn
    began. Always emits `done` last, even on cancel or error.
    """
    messages.append({"role": "user", "content": content})
    if max_hist:
        _trim_history(messages, max_hist)
    turn_start = len(messages) - 1
    state["partial"] = ""
    try:
        await stream_turn(client, cfg, messages, state, emit=emit)
    except asyncio.CancelledError:
        log.debug("Turn cancelled by user (WS cancel)")
        del messages[turn_start:]
        if state["partial"]:
            messages.append({"role": "user", "content": content})
            messages.append({"role": "assistant", "content": state["partial"] + " [interrupted]"})
        await emit({"type": "cancelled"})
    except Exception as e:
        log.exception("Turn error")
        await emit({"type": "error", "message": str(e)})
    await emit({"type": "done"})


async def _handler(ws):
    """Per-connection handler.

    Owns the WebSocket lifecycle: receives JSON messages, validates them,
    runs at most one turn at a time, and forwards cancel requests to the
    in-flight task. Each turn runs as an `asyncio.Task` so it can be
    cancelled mid-flight when the client sends `{"type": "cancel"}`.

    Invalid JSON, malformed messages, and a new user message while a turn
    is already in flight all emit `{type: error}` + `{type: done}` and
    continue serving the connection.
    """
    cfg = load_config()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    state = {"partial": ""}
    max_hist = cfg.get("cli_chat", {}).get("max_history_messages", 0)
    emit = partial(_send, ws)
    turn_task: asyncio.Task | None = None

    async with httpx.AsyncClient() as client:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                await emit({"type": "error", "message": f"Invalid JSON: {e}"})
                await emit({"type": "done"})
                continue

            msg_type = msg.get("type", "content")

            if msg_type == "cancel":
                if turn_task and not turn_task.done():
                    turn_task.cancel()
                continue

            try:
                content = msg["content"]
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
            except (KeyError, TypeError, ValueError) as e:
                await emit({"type": "error", "message": f"Invalid message: {e}"})
                await emit({"type": "done"})
                continue

            if turn_task and not turn_task.done():
                await emit({"type": "error", "message": "Turn already in progress"})
                await emit({"type": "done"})
                continue

            turn_task = asyncio.create_task(
                _run_turn(client, cfg, messages, state, max_hist, content, emit)
            )


async def _serve():
    """Bind localhost:8765 and serve `_handler` for the lifetime of the process."""
    log.info("WebSocket server on ws://localhost:8765")
    async with websockets.serve(_handler, "localhost", 8765):
        print("WebSocket server running on ws://localhost:8765")
        print("Open frontend/index.html in a browser to chat.")
        await asyncio.Future()


def main():
    """Entry point used by `python -m backend.chat --serve`."""
    logging.basicConfig(format="%(name)s %(levelname)s: %(message)s", level=logging.INFO)
    asyncio.run(_serve())
