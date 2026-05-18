"""Shared helpers for LiteLLM and ChatLiteLLM kwargs mapping.

Rules are documented in `backend/reference_docs/llm_rules.md` and enforced
through these small mapping functions.
"""

from __future__ import annotations

from typing import Any

GPT5_PREFIXES = (
    "gpt-5.4",
    "gpt-5.5",
)


def is_gemini(model_name: str) -> bool:
    return "gemini" in model_name.lower()


def is_claude(model_name: str) -> bool:
    return "claude" in model_name.lower()


def is_claude_opus_47(model_name: str) -> bool:
    return "claude-opus-4-7" in model_name.lower()


def is_gpt5_family(model_name: str) -> bool:
    lower = model_name.lower()
    return any(lower.startswith(prefix) for prefix in GPT5_PREFIXES)


def get_token_kwargs(model_name: str, max_tokens: int) -> dict[str, Any]:
    if is_gpt5_family(model_name):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def get_model_kwargs(
    model_name: str,
    temperature: float | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    if is_gpt5_family(model_name):
        if reasoning_effort and reasoning_effort != "none":
            return {"reasoning_effort": reasoning_effort}
        kwargs: dict[str, Any] = {"reasoning_effort": "none"}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return kwargs

    if is_gemini(model_name):
        kwargs = {"temperature": 1.0}
        if reasoning_effort and reasoning_effort != "none":
            kwargs["reasoning_effort"] = reasoning_effort
        return kwargs

    if is_claude(model_name):
        kwargs = {}
        if reasoning_effort and reasoning_effort != "none":
            kwargs["reasoning_effort"] = reasoning_effort
        if temperature is not None and not is_claude_opus_47(model_name):
            kwargs["temperature"] = temperature
        return kwargs

    if temperature is not None:
        return {"temperature": temperature}
    return {}


def build_litellm_completion_kwargs(
    model_name: str,
    max_tokens: int,
    temperature: float | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"drop_params": True}
    kwargs.update(get_token_kwargs(model_name, max_tokens))
    kwargs.update(get_model_kwargs(model_name, temperature, reasoning_effort))
    return kwargs


def build_chatlitellm_kwargs(
    model_name: str,
    max_tokens: int,
    temperature: float | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    token_kwargs = get_token_kwargs(model_name, max_tokens)
    model_kwargs = get_model_kwargs(model_name, temperature, reasoning_effort)

    if is_gpt5_family(model_name):
        result: dict[str, Any] = {"model_kwargs": token_kwargs}
        result.update(model_kwargs)
        return result

    result = dict(token_kwargs)
    result.update(model_kwargs)
    return result
