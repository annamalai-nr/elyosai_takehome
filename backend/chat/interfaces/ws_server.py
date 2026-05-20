"""WebSocket server — connects the frontend to the chat agent."""

import asyncio
import json
import logging

import httpx
import websockets

from backend.chat.agent import stream_turn
from backend.chat.interfaces.cli_chat import _trim_history
from backend.chat.load_config import load_config
from backend.chat.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)


async def _handler(ws):
    cfg = load_config()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    state = {"partial": ""}
    max_hist = cfg.get("cli_chat", {}).get("max_history_messages", 0)

    async def emit(event):
        await ws.send(json.dumps(event))

    async with httpx.AsyncClient() as client:
        async for raw in ws:
            try:
                msg = json.loads(raw)
                content = msg["content"]
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                await emit({"type": "error", "message": f"Invalid message: {e}"})
                await emit({"type": "done"})
                continue

            messages.append({"role": "user", "content": content})
            if max_hist:
                _trim_history(messages, max_hist)
            state["partial"] = ""
            try:
                await stream_turn(client, cfg, messages, state, emit=emit)
            except Exception as e:
                log.exception("Turn error")
                await emit({"type": "error", "message": str(e)})
            await emit({"type": "done"})


async def _serve():
    log.info("WebSocket server on ws://localhost:8765")
    async with websockets.serve(_handler, "localhost", 8765):
        print("WebSocket server running on ws://localhost:8765")
        print("Open frontend/index.html in a browser to chat.")
        await asyncio.Future()


def main():
    logging.basicConfig(format="%(name)s %(levelname)s: %(message)s", level=logging.INFO)
    asyncio.run(_serve())
