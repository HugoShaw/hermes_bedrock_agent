"""Text utilities for flowchart processing."""

from __future__ import annotations

import re
from typing import Optional


def normalize_japanese_text(text: str) -> str:
    """Normalize Japanese text (full-width to half-width numbers, etc.)."""
    # Full-width digits to half-width
    result = text
    fw_digits = "０１２３４５６７８９"
    hw_digits = "0123456789"
    for fw, hw in zip(fw_digits, hw_digits):
        result = result.replace(fw, hw)

    # Normalize spaces
    result = re.sub(r"[\u3000]+", " ", result)
    return result.strip()


def extract_function_number(text: str) -> Optional[str]:
    """Extract function number like '機能No1' from text."""
    match = re.search(r"機能No\.?(\d+)", text)
    if match:
        return f"機能No{match.group(1)}"
    return None


def contains_api_call(text: str) -> bool:
    """Check if text contains an API call pattern."""
    return bool(re.search(r"(GET|POST|PUT|DELETE)[：:]", text))
