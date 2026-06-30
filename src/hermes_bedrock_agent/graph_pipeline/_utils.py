"""Graph pipeline utilities."""

import re


def normalize_id(raw: str) -> str:
    """Normalize a raw string into a safe ID component (lowercase, alphanumeric + underscore)."""
    if not raw:
        return "unknown"
    # Convert to lowercase and replace non-alphanumeric chars with underscore
    result = re.sub(r"[^a-z0-9_]", "_", raw.lower().strip())
    # Collapse multiple underscores
    result = re.sub(r"_+", "_", result)
    # Strip leading/trailing underscores
    return result.strip("_") or "unknown"
