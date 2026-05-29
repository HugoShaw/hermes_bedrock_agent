"""Shared utilities for the graph pipeline."""

from __future__ import annotations

import re
import unicodedata


def normalize_id(text: str) -> str:
    """Normalize text to a stable ID component (keeps Japanese chars, collapses separators)."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\s\-/\\]+", "_", text)
    text = re.sub(r"[^\w]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if text.isascii():
        text = text.lower()
    return text[:80]
