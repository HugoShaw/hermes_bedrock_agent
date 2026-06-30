"""Default chunking strategy — wraps the existing semantic/fixed split logic.

This strategy produces IDENTICAL output to the pre-strategy chunker code,
ensuring backward compatibility when CHUNK_STRATEGY_ENABLED is true but no
type-specific strategy matches.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from .protocol import ChunkConfig, ChunkMetadata, ChunkResult

logger = logging.getLogger(__name__)

# These patterns are imported from chunker.py at runtime to avoid duplication.
# The strategy delegates actual splitting to the same functions used before.
_RE_SECTION = re.compile(r"^## .+")
_RE_FIELD = re.compile(r"^### .+")
_RE_TABLE = re.compile(r"^\|.+\|")
_RE_FENCE = re.compile(r"^```")
_RE_QUOTE = re.compile(r"^> ")
_RE_META = re.compile(r"^\*\*.+\*\*")
_RE_VERSION = re.compile(r"^## Ver.+変更", re.IGNORECASE)
_STRUCTURE_RES = [re.compile(r"^# .+"), _RE_SECTION, _RE_FIELD, _RE_TABLE, _RE_FENCE, _RE_QUOTE]

_CHUNK_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("flowchart", ["flowchart", "フローチャート", "API呼出順序", "api call", "sequence", "flow"]),
    ("data_condition", ["データ取得条件", "data condition", "取得条件", "where clause", "抽出条件"]),
    ("business_rule", ["business rule", "ビジネスルール", "条件", "注意事項", "補足", "special", "注記"]),
    ("api_spec", ["api", "endpoint", "REST", "HTTP", "GET", "POST", "PUT", "DELETE", "request", "response"]),
    ("mapping_table", ["マッピング", "mapping", "フィールド", "field", "項目名", "送信元", "送信先"]),
    ("overview", ["overview", "概要", "document", "change history", "変更履歴", "summary", "一覧"]),
]


def _infer_chunk_type(text: str, sheet_name: str = "") -> str:
    """Infer chunk type from text content using keyword matching."""
    combined = (text + " " + sheet_name).lower()
    for ctype, keywords in _CHUNK_TYPE_RULES:
        if any(kw.lower() in combined for kw in keywords):
            return ctype
    return "overview"


def _extract_section_name(text: str) -> str:
    """Extract the first ## section heading from chunk text."""
    for line in text.split("\n"):
        if line.startswith("## "):
            return line[3:].strip()
    return ""


class DefaultSemanticStrategy:
    """Default strategy that wraps existing _split_semantic / _split_fixed logic.

    Produces byte-for-byte identical output to the non-strategy code path.
    This is the fallback strategy when no type-specific strategy matches.
    """

    @property
    def name(self) -> str:
        return "default_semantic"

    def __init__(self, split_fn: Callable | None = None):
        """Initialize with optional split function override.

        Args:
            split_fn: If None, will be resolved lazily from chunker module.
                      Signature: (markdown, max_size, min_size, mode, target) -> list[str]
        """
        self._split_fn = split_fn

    def _get_split_fn(self) -> Callable:
        """Lazy-load the split function from chunker module to avoid circular imports."""
        if self._split_fn is None:
            from ..chunker import _split_into_chunks
            self._split_fn = _split_into_chunks
        return self._split_fn

    def chunk(
        self,
        body: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Split body using existing semantic/fixed chunking logic.

        Produces identical chunk text as the pre-strategy code path.
        chunk_type is inferred via keyword matching (same as before).
        embedding_text is left empty — the caller builds it using the same
        default template as before.
        """
        if not body.strip():
            return []

        split_fn = self._get_split_fn()
        text_chunks = split_fn(
            body,
            config.max_chars,
            config.min_chars,
            mode=config.mode,
            target=config.target_chars,
        )

        results: list[ChunkResult] = []
        for chunk_text in text_chunks:
            chunk_type = _infer_chunk_type(chunk_text, metadata.sheet_name)
            section_name = _extract_section_name(chunk_text)
            results.append(ChunkResult(
                text=chunk_text,
                chunk_type=chunk_type,
                section_name=section_name,
                # Leave embedding_text empty — caller applies default template
                embedding_text="",
                # Leave extraction empty — caller runs same extractors as before
                systems=[],
                apis=[],
                fields=[],
                field_codes=[],
            ))

        return results


class SingleChunkStrategy:
    """Strategy for document types that should not be split (mermaid, images).

    Emits the entire body as a single chunk. Equivalent to the
    _SINGLE_CHUNK_TYPES behavior in the existing code.
    """

    @property
    def name(self) -> str:
        return "single_chunk"

    def chunk(
        self,
        body: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Return entire body as a single chunk."""
        text = body.strip()
        if not text:
            return []

        chunk_type = _infer_chunk_type(text, metadata.sheet_name)
        section_name = _extract_section_name(text)
        return [ChunkResult(
            text=text,
            chunk_type=chunk_type,
            section_name=section_name,
            embedding_text="",
            systems=[],
            apis=[],
            fields=[],
            field_codes=[],
        )]
