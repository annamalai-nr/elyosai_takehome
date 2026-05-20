"""Allow `python -m backend.chat` and `python -m backend.chat --validate`."""

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.chat",
        description="Elyos streaming CLI chat with weather and research tools.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run parser and resilience self-tests and exit.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start WebSocket server for the web UI (ws://localhost:8765).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.validate:
        from backend.chat.tests.runner import run_all

        run_all()
    elif args.serve:
        from backend.chat.interfaces.ws_server import main as ws_main

        ws_main()
    else:
        from backend.chat.interfaces.cli_chat import main as cli_main

        cli_main()


if __name__ == "__main__":
    main()
