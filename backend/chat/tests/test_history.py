"""Self-tests for conversation history trimming."""

import sys

from backend.chat.interfaces.cli_chat import _trim_history

SYSTEM = {"role": "system", "content": "You are a helpful assistant."}


def _simple_turn(user_text: str, assistant_text: str) -> list[dict]:
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]


def _tool_turn(user_text: str) -> list[dict]:
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"location": "London"}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"data": {}}'},
        {"role": "assistant", "content": "The weather in London is sunny."},
    ]


def test_noop_under_limit():
    """No trimming when under the limit."""
    msgs = [SYSTEM, *_simple_turn("hi", "hello")]
    original = list(msgs)
    _trim_history(msgs, 10)
    assert msgs == original
    return True, "no-op when under limit"


def test_noop_zero_limit():
    """No trimming when limit is 0 (disabled)."""
    msgs = [SYSTEM, *_simple_turn("hi", "hello")]
    original = list(msgs)
    _trim_history(msgs, 0)
    assert msgs == original
    return True, "no-op when limit is 0"


def test_system_prompt_preserved():
    """System prompt is always preserved after trimming."""
    msgs = [SYSTEM, *_simple_turn("a", "b"), *_simple_turn("c", "d"), {"role": "user", "content": "e"}]
    _trim_history(msgs, 4)
    assert msgs[0] == SYSTEM, f"System prompt lost: {msgs[0]}"
    return True, "system prompt preserved"


def test_current_user_message_preserved():
    """Current user message (no assistant response yet) survives trimming."""
    msgs = [SYSTEM, *_simple_turn("old", "reply"), {"role": "user", "content": "new"}]
    _trim_history(msgs, 2)
    assert msgs[-1] == {"role": "user", "content": "new"}, f"Current user message lost: {msgs[-1]}"
    assert msgs[0] == SYSTEM
    return True, "current user message preserved"


def test_complete_turns_not_orphaned():
    """Tool-call turns are kept or removed whole, never orphaned."""
    tool_turn = _tool_turn("weather please")
    msgs = [SYSTEM, *_simple_turn("old1", "reply1"), *tool_turn, {"role": "user", "content": "new"}]
    _trim_history(msgs, 7)
    roles = [m.get("role") for m in msgs]
    if "tool" in roles:
        tool_idx = roles.index("tool")
        assert roles[tool_idx - 1] == "assistant", "Tool result without preceding assistant"
        assert "tool_calls" in msgs[tool_idx - 1], "Preceding assistant has no tool_calls"
    return True, "tool-call turns kept whole"


def test_oldest_turns_trimmed_first():
    """Oldest turns are trimmed before newer ones."""
    msgs = [
        SYSTEM,
        *_simple_turn("turn1", "reply1"),
        *_simple_turn("turn2", "reply2"),
        *_simple_turn("turn3", "reply3"),
        {"role": "user", "content": "turn4"},
    ]
    _trim_history(msgs, 6)
    contents = [m.get("content") for m in msgs]
    assert "turn1" not in contents, "Oldest turn should have been trimmed"
    assert "turn4" in contents, "Current user message should survive"
    return True, "oldest turns trimmed first"


def test_cancellation_rollback_removes_current_turn():
    """turn_start points at the current user message so cancellation rollback is clean."""
    msgs = [
        SYSTEM,
        *_simple_turn("old", "reply"),
        *_simple_turn("prev", "prev_reply"),
    ]
    prior_history = list(msgs)
    msgs.append({"role": "user", "content": "new"})
    _trim_history(msgs, 40)
    turn_start = len(msgs) - 1
    assert msgs[turn_start] == {"role": "user", "content": "new"}, (
        f"turn_start should point at current user message, got: {msgs[turn_start]}"
    )
    del msgs[turn_start:]
    assert msgs == prior_history, "Prior history should be intact after rollback"
    return True, "cancellation rollback removes current turn cleanly"


TESTS = [
    test_noop_under_limit,
    test_noop_zero_limit,
    test_system_prompt_preserved,
    test_current_user_message_preserved,
    test_complete_turns_not_orphaned,
    test_oldest_turns_trimmed_first,
    test_cancellation_rollback_removes_current_turn,
]


def run() -> None:
    for test in TESTS:
        passed, msg = test()
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {test.__doc__} — {msg}")
        if not passed:
            sys.exit(1)
    print(f"All {len(TESTS)} history tests passed.")
