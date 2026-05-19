"""Runs all self-tests (parser + resilience + history)."""

from backend.chat.tests.test_history import run as run_history_tests
from backend.chat.tests.test_parsers import run as run_parser_tests
from backend.chat.tests.test_resilience import run as run_resilience_tests


def run_all() -> None:
    run_parser_tests()
    run_resilience_tests()
    run_history_tests()


if __name__ == "__main__":
    run_all()
