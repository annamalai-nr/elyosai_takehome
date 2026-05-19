"""Runs all self-tests (parser + resilience)."""

from backend.chat.tests.test_parsers import run as run_parser_tests
from backend.chat.tests.test_resilience import run as run_resilience_tests


def run_all() -> None:
    run_parser_tests()
    run_resilience_tests()


if __name__ == "__main__":
    run_all()
