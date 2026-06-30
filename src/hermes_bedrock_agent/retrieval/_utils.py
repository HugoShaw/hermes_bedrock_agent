"""Shared utility functions for retrieval modules."""
from __future__ import annotations

import math


def _safe_str(val: object) -> str:
    """Convert a pandas row value to a clean string, handling NaN/None/float safely.

    Used across vector_retriever, graph_guided_retrieval, and graph_expansion
    to prevent NaN propagation when reading LanceDB/pandas results.
    """
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
        return str(val)
    s = str(val).strip()
    if s in ("nan", "None", "null"):
        return ""
    return s
