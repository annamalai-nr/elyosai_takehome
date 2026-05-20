"""WebSocket server — connects the frontend to the chat agent."""

import asyncio
import json
import logging
from functools import partial

import httpx
import websockets

from backend.chat.agent import stream_turn
from backend.chat.interfaces.cli_chat import _trim_history
from backend.chat.load_config import load_config
from backend.chat.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)


async def _send(ws, event: dict) -> None:
    await ws.send(json.dumps(event))


async def _run_turn(
    client: httpx.AsyncClient,
    cfg: dict,
    messages: list[dict],
    state: dict,
    max_hist: int,
    content: str,
    emit,
) -> None:
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
    log.info("WebSocket server on ws://localhost:8765")
    async with websockets.serve(_handler, "localhost", 8765):
        print("WebSocket server running on ws://localhost:8765")
        print("Open frontend/index.html in a browser to chat.")
        await asyncio.Future()


def main():
    logging.basicConfig(format="%(name)s %(levelname)s: %(message)s", level=logging.INFO)
    asyncio.run(_serve())
