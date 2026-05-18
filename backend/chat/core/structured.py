"""Structured-output helper for non-streaming extraction/classification calls."""

from typing import TypeVar

import litellm
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def structured_completion(model: str, messages: list[dict], schema: type[T]) -> T:
    """Call an LLM and parse the response into a Pydantic model."""
    resp = await litellm.acompletion(
        model=model,
        messages=messages,
        response_format=schema,
        drop_params=True,
    )
    return schema.model_validate_json(resp.choices[0].message.content)
