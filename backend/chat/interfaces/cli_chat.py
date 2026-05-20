"""Interactive CLI REPL with SIGINT cancellation and session-level state."""

import asyncio
import logging
import signal

import httpx

from backend.chat.agent import stream_turn
from backend.chat.load_config import load_config
from backend.chat.prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

_turn_task: asyncio.Task | None = None

EXIT_COMMANDS: frozenset[str] = frozenset({"quit", "exit", "q"})


def _trim_history(messages: list[dict], max_messages: int) -> None:
    """Trim oldest complete turns, preserving system prompt and valid tool-call groups."""
    if max_messages <= 0 or len(messages) <= max_messages:
        return
    turn_starts = [i for i, msg in enumerate(messages) if msg.get("role") == "user"]
    for start in turn_starts:
        kept_len = 1 + len(messages) - start
        if kept_len <= max_messages:
            del messages[1:start]
            return
    if turn_starts:
        del messages[1:turn_starts[-1]]


def _on_sigint() -> None:
    if _turn_task and not _turn_task.done():
        _turn_task.cancel()
    else:
        raise KeyboardInterrupt


async def _async_main() -> None:
    global _turn_task
    cfg = load_config()
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    log.debug("Session started: model=%s", cfg["llm"]["model_name"])
    print(f"Elyos Chat (model: {cfg['llm']['model_name']})")
    print("Type 'quit' to exit.\n")

    session_state: dict = {"partial": ""}

    async with httpx.AsyncClient() as http_client:
        loop = asyncio.get_running_loop()

        while True:
            loop.remove_signal_handler(signal.SIGINT)
            try:
                user_input = await asyncio.to_thread(input, "You: ")
            except (EOFError, KeyboardInterrupt):
                print()
                break

            stripped = user_input.strip()
            if stripped.lower() in EXIT_COMMANDS:
                break
            if not stripped:
                continue

            loop.add_signal_handler(signal.SIGINT, _on_sigint)
            messages.append({"role": "user", "content": user_input})
            max_hist = cfg.get("cli_chat", {}).get("max_history_messages", 0)
            if max_hist:
                _trim_history(messages, max_hist)
            turn_start = len(messages) - 1
            print("Assistant: ", end="", flush=True)

            session_state["partial"] = ""
            _turn_task = asyncio.create_task(stream_turn(http_client, cfg, messages, session_state))
            try:
                await _turn_task
            except asyncio.CancelledError:
                log.debug("Turn cancelled by user (SIGINT)")
                print("\nCancelled. The interrupted API call may still count against the rate limit.")
                del messages[turn_start:]
                if session_state["partial"]:
                    messages.append({"role": "user", "content": user_input})
                    messages.append({"role": "assistant", "content": session_state["partial"] + " [interrupted]"})
            finally:
                _turn_task = None

    print("Goodbye.")


def main() -> None:
    logging.basicConfig(
        format="%(name)s %(levelname)s: %(message)s",
        level=logging.INFO,
    )
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
