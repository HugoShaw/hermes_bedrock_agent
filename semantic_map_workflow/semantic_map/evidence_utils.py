"""
Evidence handling utilities for the semantic map workflow.

All functions operate on plain strings and use only the Python standard library.
"""

from __future__ import annotations

import re

from .constants import CONFIDENCE_HIGH, CONFIDENCE_MED


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_CHARS = 500
_DEFAULT_CONTEXT_CHARS = 200
_PIPE_SEP = " | "
_EVIDENCE_BOOST = 0.05          # confidence boost when evidence is present
_CONFIDENCE_CEIL = 1.0           # maximum allowed confidence value


# ---------------------------------------------------------------------------
# truncate_evidence
# ---------------------------------------------------------------------------

def truncate_evidence(text: str, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """
    Truncate *text* to at most *max_chars* characters.

    If truncation occurs an ellipsis (``…``) is appended so that readers can
    tell the text was cut.

    Args:
        text:      The evidence string to truncate.
        max_chars: Maximum number of characters to keep (default 500).

    Returns:
        The (possibly truncated) evidence string.

    Examples::

        >>> truncate_evidence("hello world", 5)
        'hello…'
        >>> truncate_evidence("short", 500)
        'short'
    """
    if not isinstance(text, str):
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    # Reserve one character for the ellipsis
    return text[: max_chars - 1] + "…"


# ---------------------------------------------------------------------------
# extract_evidence_snippet
# ---------------------------------------------------------------------------

def extract_evidence_snippet(
    full_text: str,
    keyword: str,
    context_chars: int = _DEFAULT_CONTEXT_CHARS,
) -> str:
    """
    Find the first occurrence of *keyword* (case-insensitive) in *full_text*
    and return a context window of ±*context_chars* characters around it.

    If the keyword is not found the function returns an empty string.
    The returned snippet is stripped of leading/trailing whitespace.

    Args:
        full_text:     Source document to search.
        keyword:       Word or phrase to locate.
        context_chars: Number of characters of context on each side (default 200).

    Returns:
        A context snippet, possibly prefixed/suffixed with ``…`` when the
        window was clipped, or an empty string if *keyword* was not found.

    Examples::

        >>> text = "The payment process starts when the user submits a form."
        >>> extract_evidence_snippet(text, "payment", context_chars=10)
        'The payment process'
    """
    if not isinstance(full_text, str) or not isinstance(keyword, str):
        return ""
    if not full_text or not keyword:
        return ""

    # Case-insensitive search
    idx = full_text.lower().find(keyword.lower())
    if idx == -1:
        return ""

    start = max(0, idx - context_chars)
    end = min(len(full_text), idx + len(keyword) + context_chars)

    snippet = full_text[start:end].strip()

    # Add ellipsis markers when the window was clipped
    if start > 0:
        snippet = "…" + snippet
    if end < len(full_text):
        snippet = snippet + "…"

    return snippet


# ---------------------------------------------------------------------------
# combine_evidence
# ---------------------------------------------------------------------------

def combine_evidence(*snippets: str, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """
    Combine multiple evidence snippets into a single string.

    The snippets are:
    1. Stripped of surrounding whitespace.
    2. Deduplicated (preserving first-seen order).
    3. Joined with `` | `` as a separator.
    4. Truncated to *max_chars* characters via :func:`truncate_evidence`.

    Args:
        *snippets:  One or more evidence strings.
        max_chars:  Maximum character length of the combined string (default 500).

    Returns:
        A combined, deduplicated, truncated evidence string.

    Examples::

        >>> combine_evidence("foo", "bar", "foo")
        'foo | bar'
    """
    seen: dict[str, None] = {}  # ordered set (insertion-order dict)
    for snippet in snippets:
        if not isinstance(snippet, str):
            continue
        clean = snippet.strip()
        if clean:
            seen[clean] = None

    combined = _PIPE_SEP.join(seen.keys())
    return truncate_evidence(combined, max_chars)


# ---------------------------------------------------------------------------
# evidence_confidence_boost
# ---------------------------------------------------------------------------

def evidence_confidence_boost(base_conf: float, has_evidence: bool) -> float:
    """
    Apply a small confidence boost when supporting evidence is present.

    The boost is fixed at +0.05 and the result is clamped to [0.0, 1.0].

    Args:
        base_conf:    Starting confidence value (should be in [0.0, 1.0]).
        has_evidence: Whether evidence was found that supports the assertion.

    Returns:
        Adjusted confidence value clamped to [0.0, 1.0].

    Examples::

        >>> evidence_confidence_boost(0.80, True)
        0.85
        >>> evidence_confidence_boost(0.97, True)
        1.0
        >>> evidence_confidence_boost(0.80, False)
        0.8
    """
    if not isinstance(base_conf, (int, float)):
        raise TypeError(
            f"base_conf must be a float, got {type(base_conf).__name__!r}"
        )

    conf = float(base_conf)

    if has_evidence:
        conf += _EVIDENCE_BOOST

    # Clamp to valid range
    return max(0.0, min(_CONFIDENCE_CEIL, conf))
