"""Structured output validation and parsing for LLM responses."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def parse_llm_json(text: str) -> dict[str, Any]:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try to find JSON array in text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return {"items": json.loads(match.group())}
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}...")


def validate_structured_output(data: dict[str, Any], model_class: type[T]) -> T | None:
    """Validate parsed JSON against a Pydantic model."""
    try:
        return model_class.model_validate(data)
    except ValidationError as exc:
        logger.warning("Structured output validation failed: %s", exc.errors())
        return None
