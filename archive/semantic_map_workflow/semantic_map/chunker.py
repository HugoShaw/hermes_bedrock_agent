"""
Text chunking utilities for the semantic map workflow.

Provides both generic character-level chunking and structure-aware chunking
for Java source files, SQL DDL scripts, and MyBatis XML mapper files.

The top-level :func:`smart_chunk` function selects the appropriate strategy
based on the ``source_type`` label produced by :mod:`file_classifier`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from semantic_map.text_loader import load_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MAX_CHARS = 4000
DEFAULT_OVERLAP = 200

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------
# Java: class / interface / enum / @interface declarations (captures from here to EOF slice)
_RE_JAVA_CLASS_BOUNDARY = re.compile(
    r"(?m)^(?:[ \t]*)(?:(?:public|protected|private|abstract|final|static)\s+)*"
    r"(?:class|interface|enum|@interface)\s+\w+"
)

# Java method boundary (heuristic: return-type methodName(...)  {)
_RE_JAVA_METHOD_BOUNDARY = re.compile(
    r"(?m)^[ \t]*(?:(?:public|protected|private|static|final|synchronized|"
    r"abstract|native|default|transient|volatile)\s+)*"
    r"[\w<>\[\],\s]+\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{"
)

# SQL: CREATE TABLE (case-insensitive, multiline)
_RE_CREATE_TABLE = re.compile(r"(?im)(?=^\s*CREATE\s+TABLE\b)")

# XML mapper statement tags
_RE_XML_STMT = re.compile(
    r"(?s)<(?P<tag>select|insert|update|delete)\b[^>]*>.*?</(?P=tag)>",
    re.IGNORECASE,
)


class Chunker:
    """Collection of text-chunking strategies."""

    # ------------------------------------------------------------------
    # Generic chunking
    # ------------------------------------------------------------------

    def chunk_text(
        self,
        text: str,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap: int = DEFAULT_OVERLAP,
    ) -> list[str]:
        """Split *text* into overlapping character-level chunks.

        Parameters
        ----------
        text:
            Input text.
        max_chars:
            Maximum characters per chunk.
        overlap:
            Characters of overlap between consecutive chunks.

        Returns
        -------
        list[str]
            Non-empty list of chunks.  Returns ``[]`` when *text* is empty.
        """
        if not text:
            return []

        if len(text) <= max_chars:
            return [text]

        overlap = min(overlap, max_chars // 2)
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap

        return chunks

    def chunk_file(
        self,
        path: str,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap: int = DEFAULT_OVERLAP,
    ) -> list[str]:
        """Load *path* and apply :meth:`chunk_text`.

        Parameters
        ----------
        path:
            Path to the source file.
        max_chars:
            Maximum characters per chunk.
        overlap:
            Overlap characters.

        Returns
        -------
        list[str]
        """
        text = load_text(path)
        if not text:
            logger.warning("chunk_file: empty or unreadable file: %s", path)
            return []
        return self.chunk_text(text, max_chars=max_chars, overlap=overlap)

    # ------------------------------------------------------------------
    # Java-aware chunking
    # ------------------------------------------------------------------

    def chunk_java_class(self, text: str) -> list[str]:
        """Split Java source text at class and method boundaries.

        The heuristic works in two passes:

        1. Split on class/interface/enum declarations.
        2. For each class block, further split on method boundaries when the
           block exceeds :data:`DEFAULT_MAX_CHARS`.

        Parameters
        ----------
        text:
            Java source text.

        Returns
        -------
        list[str]
            One chunk per logical unit (class or method).
        """
        if not text:
            return []

        # First pass: split at top-level class declarations
        class_splits = self._split_on_pattern(_RE_JAVA_CLASS_BOUNDARY, text)

        chunks: list[str] = []
        for block in class_splits:
            if len(block) <= DEFAULT_MAX_CHARS:
                chunks.append(block)
            else:
                # Second pass: split within the class at method boundaries
                method_splits = self._split_on_pattern(_RE_JAVA_METHOD_BOUNDARY, block)
                for method_block in method_splits:
                    if len(method_block) <= DEFAULT_MAX_CHARS:
                        chunks.append(method_block)
                    else:
                        # Fall back to character chunking for very long methods
                        chunks.extend(
                            self.chunk_text(method_block, max_chars=DEFAULT_MAX_CHARS)
                        )

        return [c for c in chunks if c.strip()]

    # ------------------------------------------------------------------
    # SQL DDL chunking
    # ------------------------------------------------------------------

    def chunk_sql_ddl(self, text: str) -> list[str]:
        """Split a SQL script into individual CREATE TABLE statement chunks.

        Each chunk contains one complete ``CREATE TABLE … ;`` block.  Any
        leading text before the first ``CREATE TABLE`` is included in the
        first chunk.  If no ``CREATE TABLE`` is found the entire text is
        returned as a single chunk.

        Parameters
        ----------
        text:
            SQL script text.

        Returns
        -------
        list[str]
        """
        if not text:
            return []

        parts = self._split_on_pattern(_RE_CREATE_TABLE, text)
        chunks: list[str] = []
        for part in parts:
            stripped = part.strip()
            if not stripped:
                continue
            if len(stripped) <= DEFAULT_MAX_CHARS:
                chunks.append(stripped)
            else:
                # Very large tables – fall back to character chunking
                chunks.extend(self.chunk_text(stripped, max_chars=DEFAULT_MAX_CHARS))

        return chunks

    # ------------------------------------------------------------------
    # MyBatis XML mapper chunking
    # ------------------------------------------------------------------

    def chunk_xml_mapper(self, text: str) -> list[str]:
        """Split a MyBatis XML mapper into per-statement chunks.

        Extracts each ``<select>``, ``<insert>``, ``<update>``, and
        ``<delete>`` block as its own chunk.  Any content not matched by
        those tags (e.g. the root ``<mapper>`` opening/closing tags and
        ``<resultMap>`` blocks) is returned as a preamble chunk.

        Parameters
        ----------
        text:
            XML mapper file text.

        Returns
        -------
        list[str]
        """
        if not text:
            return []

        chunks: list[str] = []
        matched_spans: list[tuple[int, int]] = []

        for m in _RE_XML_STMT.finditer(text):
            matched_spans.append((m.start(), m.end()))
            chunks.append(m.group(0).strip())

        # Collect all non-statement text as a preamble/metadata chunk
        if matched_spans:
            preamble_parts: list[str] = []
            prev_end = 0
            for start, end in matched_spans:
                gap = text[prev_end:start].strip()
                if gap:
                    preamble_parts.append(gap)
                prev_end = end
            tail = text[prev_end:].strip()
            if tail:
                preamble_parts.append(tail)
            if preamble_parts:
                preamble = "\n".join(preamble_parts)
                chunks.insert(0, preamble)
        else:
            # No recognised statement tags – return as-is
            chunks = [text] if text.strip() else []

        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_on_pattern(pattern: re.Pattern, text: str) -> list[str]:
        """Split *text* at every position where *pattern* matches.

        Unlike ``re.split`` this keeps the match text at the *start* of
        each resulting segment (lookahead split semantics).
        """
        positions = [m.start() for m in pattern.finditer(text)]
        if not positions:
            return [text]

        parts: list[str] = []
        prev = 0
        for pos in positions:
            if pos > prev:
                parts.append(text[prev:pos])
            prev = pos
        parts.append(text[prev:])
        return parts


# ---------------------------------------------------------------------------
# Module-level smart_chunk helper
# ---------------------------------------------------------------------------

_DEFAULT_CHUNKER = Chunker()


def smart_chunk(
    text: str,
    source_type: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[str]:
    """Dispatch to the best chunking strategy for *source_type*.

    +--------------------+-----------------------------------------------+
    | source_type        | strategy                                      |
    +====================+===============================================+
    | ``source_code``    | :meth:`Chunker.chunk_java_class` (Java-like)  |
    |                    | for ``*.java`` hint; otherwise generic.       |
    | ``ddl``            | :meth:`Chunker.chunk_sql_ddl`                 |
    | ``sql_mapper``     | :meth:`Chunker.chunk_xml_mapper`              |
    | *(any other)*      | :meth:`Chunker.chunk_text` with *max_chars*   |
    +--------------------+-----------------------------------------------+

    Parameters
    ----------
    text:
        Source text.
    source_type:
        One of the ``ST_*`` constants from :mod:`file_classifier`.
    max_chars:
        Character limit for generic chunking fallback.

    Returns
    -------
    list[str]
    """
    if not text:
        return []

    if source_type == "ddl":
        return _DEFAULT_CHUNKER.chunk_sql_ddl(text)

    if source_type == "sql_mapper":
        return _DEFAULT_CHUNKER.chunk_xml_mapper(text)

    if source_type == "source_code":
        # Use Java-aware chunking if the text looks like Java (heuristic)
        if _RE_JAVA_CLASS_BOUNDARY.search(text):
            return _DEFAULT_CHUNKER.chunk_java_class(text)
        return _DEFAULT_CHUNKER.chunk_text(text, max_chars=max_chars)

    return _DEFAULT_CHUNKER.chunk_text(text, max_chars=max_chars)
