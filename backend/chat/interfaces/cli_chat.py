import asyncio
import signal

import httpx

from backend.chat.core.engine import stream_turn
from backend.chat.load_config import load_config
from backend.chat.prompts import SYSTEM_PROMPT

_turn_task = None


def _on_sigint():
    global _turn_task
    if _turn_task and not _turn_task.done():
        _turn_task.cancel()
    else:
        raise KeyboardInterrupt


async def _async_main():
    global _turn_task
    cfg = load_config()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"Elyos Chat (model: {cfg['llm']['model_name']})")
    print("Type 'quit' to exit.\n")

    async with httpx.AsyncClient() as http_client:
        loop = asyncio.get_running_loop()

        while True:
            loop.remove_signal_handler(signal.SIGINT)
            try:
                user_input = await asyncio.to_thread(input, "You: ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if user_input.strip().lower() in ("quit", "exit", "q"):
                break
            if not user_input.strip():
                continue

            loop.add_signal_handler(signal.SIGINT, _on_sigint)
            turn_start = len(messages)
            messages.append({"role": "user", "content": user_input})
            print("Assistant: ", end="", flush=True)

            state = {"partial": ""}
            _turn_task = asyncio.create_task(stream_turn(http_client, cfg, messages, state))
            try:
                await _turn_task
            except asyncio.CancelledError:
                print("\nCancelled.")
                del messages[turn_start:]
                if state["partial"]:
                    messages.append({"role": "user", "content": user_input})
                    messages.append({"role": "assistant", "content": state["partial"] + " [interrupted]"})
            finally:
                _turn_task = None

    print("Goodbye.")


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
