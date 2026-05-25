"""
Summary builder for the V2 evidence pipeline.

Produces a summary string for a document or section using extractive methods
only — no LLM calls in this stage.

Summary modes
-------------
  extractive (default)
      First N chars + up to K high-information sentences selected by simple
      heuristics (sentence length, keyword density, position).
  none
      Returns an empty string (summary chunk will be skipped by chunk_builder).

The ``llm`` mode is reserved for a later pipeline stage and raises
``NotImplementedError`` when requested here.
"""
from __future__ import annotations

import re
import logging
from typing import Any

from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord, SectionRecord

logger = logging.getLogger(__name__)

# Number of characters taken from the start of the text as the "head"
_HEAD_CHARS = 300
# Maximum additional key sentences to append
_MAX_KEY_SENTENCES = 5
# Minimum sentence length (chars) to be considered for extraction
_MIN_SENTENCE_LEN = 20
# Maximum total chars in the extractive summary
_MAX_SUMMARY_CHARS = 800


def build_document_summary(
    doc: DocumentRecord,
    sections: list[SectionRecord],
    *,
    mode: str = "extractive",
) -> str:
    """Build a summary string for an entire document.

    Args:
        doc: The document record.
        sections: All sections belonging to the document.
        mode: ``extractive`` or ``none``.

    Returns:
        Summary string, possibly empty when mode is ``none`` or text is absent.
    """
    if mode == "none":
        return ""
    if mode == "llm":
        raise NotImplementedError("LLM summarisation is not available in Stage 04")

    # Concatenate section texts in order, up to a reasonable limit
    combined = "\n\n".join(
        s.text for s in sections if s.text.strip()
    )[:6000]

    return _extractive_summary(combined, doc.title)


def build_section_summary(
    section: SectionRecord,
    *,
    mode: str = "extractive",
) -> str:
    """Build a summary string for a single section.

    Args:
        section: The section record.
        mode: ``extractive`` or ``none``.

    Returns:
        Summary string, possibly empty.
    """
    if mode == "none":
        return ""
    if mode == "llm":
        raise NotImplementedError("LLM summarisation is not available in Stage 04")

    return _extractive_summary(section.text, section.title)


# ---------------------------------------------------------------------------
# Extractive summarisation
# ---------------------------------------------------------------------------

def _extractive_summary(text: str, title: str = "") -> str:
    """Return an extractive summary of *text*."""
    text = text.strip()
    if not text:
        return ""

    # Head: first _HEAD_CHARS characters
    head = text[:_HEAD_CHARS].rstrip()
    if len(text) <= _HEAD_CHARS:
        return head

    # Key sentences from the remainder
    remainder = text[_HEAD_CHARS:]
    sentences = _split_sentences(remainder)
    key = _select_key_sentences(sentences, title=title, n=_MAX_KEY_SENTENCES)

    if key:
        summary = head + " … " + " ".join(key)
    else:
        summary = head

    return summary[:_MAX_SUMMARY_CHARS]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using simple punctuation rules."""
    # Split on Japanese/Chinese sentence-ending punctuation and ASCII periods
    pattern = re.compile(r"(?<=[。！？.!?])\s*")
    parts = pattern.split(text)
    return [p.strip() for p in parts if len(p.strip()) >= _MIN_SENTENCE_LEN]


def _select_key_sentences(
    sentences: list[str],
    title: str = "",
    n: int = _MAX_KEY_SENTENCES,
) -> list[str]:
    """Score sentences and return the top *n*."""
    if not sentences:
        return []

    title_words = set(re.findall(r"\w+", title.lower())) if title else set()

    scored: list[tuple[float, int, str]] = []
    for i, sent in enumerate(sentences):
        score = _sentence_score(sent, title_words, position=i, total=len(sentences))
        scored.append((score, i, sent))

    scored.sort(key=lambda x: -x[0])
    # Re-order by original position to preserve flow
    top = sorted(scored[:n], key=lambda x: x[1])
    return [s for _, _, s in top]


def _sentence_score(
    sentence: str,
    title_words: set[str],
    position: int,
    total: int,
) -> float:
    """Heuristic score for how informative a sentence is."""
    score = 0.0

    # Length bonus (longer sentences tend to carry more info, up to a point)
    length = len(sentence)
    score += min(length / 200.0, 1.0) * 0.3

    # Title word overlap
    sent_words = set(re.findall(r"\w+", sentence.lower()))
    if title_words:
        overlap = len(sent_words & title_words) / max(len(title_words), 1)
        score += overlap * 0.3

    # Contains numbers/dates — often informative
    if re.search(r"\d", sentence):
        score += 0.1

    # Contains CJK noun compounds — likely domain-specific
    if re.search(r"[一-鿿぀-ヿ]{3,}", sentence):
        score += 0.15

    # Position: sentences near the start and end are often more informative
    if total > 1:
        rel = position / (total - 1)
        position_weight = 1.0 - abs(rel - 0.0) * 0.5  # favour early sentences
        score += position_weight * 0.15

    return score
