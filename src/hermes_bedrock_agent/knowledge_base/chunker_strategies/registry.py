"""Strategy registry — selects the appropriate chunking strategy based on metadata.

Phase 2 selection rules (ordered by specificity):
1. Strong mermaid signals → MermaidFlowchartStrategy
2. source_type in {"images"} or parsed_subdir="images" → SingleChunkStrategy
3. All other cases → DefaultSemanticStrategy

Multi-signal selection (Phase 2b):
- Mermaid triggers ONLY on strong signals: source_type="mermaid", parser_type in
  {"mermaid_parser", "mermaid_v2"}, or parsed_subdir="mermaid".
- document_type="flowchart" alone does NOT trigger Mermaid strategy (Excel flowchart
  sheets also have this value).
- For future Excel strategies, will require ≥3 signal matches (Phase 3).

Note: When CHUNK_STRATEGY_ENABLED=false, the registry is never called.
The old code path (SingleChunkStrategy for mermaid/images, semantic for rest)
runs directly in chunker.py.
"""

from __future__ import annotations

import logging
from typing import Optional

from .default import DefaultSemanticStrategy, SingleChunkStrategy
from .mermaid import MermaidFlowchartStrategy
from .protocol import ChunkMetadata, ChunkingStrategy

logger = logging.getLogger(__name__)


# Single-chunk types: these produce one chunk without any splitting.
# Phase 2: Mermaid is no longer in this set — it gets MermaidFlowchartStrategy.
_SINGLE_CHUNK_SUBDIRS = {"images"}

# Strong Mermaid signals — any one triggers MermaidFlowchartStrategy.
# NOTE: document_type="flowchart" is intentionally EXCLUDED because Excel
# flowchart sheets also carry that value. Only unambiguous Mermaid indicators
# are included here.
_MERMAID_SIGNALS = {
    "source_type": {"mermaid"},
    "parsed_subdir": {"mermaid"},
    "parser_type": {"mermaid_parser", "mermaid_v2"},
}


class ChunkingStrategyRegistry:
    """Registry that selects chunking strategy based on document metadata.

    Phase 2 behavior:
    - Mermaid documents → MermaidFlowchartStrategy (structure-aware multi-chunk)
    - Images → SingleChunkStrategy
    - Everything else → DefaultSemanticStrategy

    Selection uses multi-signal matching:
    - Mermaid: any one signal from _MERMAID_SIGNALS triggers the strategy
    - Future: Excel strategies will require ≥3 signals (Phase 3)
    """

    def __init__(self):
        self._default = DefaultSemanticStrategy()
        self._single_chunk = SingleChunkStrategy()
        self._mermaid = MermaidFlowchartStrategy()

    def select(self, metadata: ChunkMetadata) -> ChunkingStrategy:
        """Select the best strategy for the given document metadata.

        Selection priority:
        1. Mermaid signals → MermaidFlowchartStrategy
        2. Single-chunk types (images) → SingleChunkStrategy
        3. Default → DefaultSemanticStrategy
        """
        # Phase 2: Mermaid multi-signal detection
        if self._is_mermaid(metadata):
            logger.debug(
                "Strategy selected: %s (mermaid signals matched for %s)",
                self._mermaid.name, metadata.filename,
            )
            return self._mermaid

        # Single-chunk types (images only now)
        if metadata.parsed_subdir in _SINGLE_CHUNK_SUBDIRS:
            logger.debug(
                "Strategy selected: %s (parsed_subdir=%s)",
                self._single_chunk.name, metadata.parsed_subdir,
            )
            return self._single_chunk

        if metadata.source_type in _SINGLE_CHUNK_SUBDIRS:
            logger.debug(
                "Strategy selected: %s (source_type=%s)",
                self._single_chunk.name, metadata.source_type,
            )
            return self._single_chunk

        logger.debug(
            "Strategy selected: %s (fallback for source_type=%s, parsed_subdir=%s)",
            self._default.name, metadata.source_type, metadata.parsed_subdir,
        )
        return self._default

    def _is_mermaid(self, metadata: ChunkMetadata) -> bool:
        """Check if any strong mermaid signal matches.

        Only source_type, parsed_subdir, and parser_type are checked.
        document_type="flowchart" is NOT sufficient (Excel flowchart sheets
        also carry that value).
        """
        if metadata.source_type in _MERMAID_SIGNALS["source_type"]:
            return True
        if metadata.parsed_subdir in _MERMAID_SIGNALS["parsed_subdir"]:
            return True
        if metadata.parser_type in _MERMAID_SIGNALS["parser_type"]:
            return True
        return False


# Module-level singleton for convenience
_registry: Optional[ChunkingStrategyRegistry] = None


def select_strategy(metadata: ChunkMetadata) -> ChunkingStrategy:
    """Select chunking strategy for the given metadata (module-level convenience)."""
    global _registry
    if _registry is None:
        _registry = ChunkingStrategyRegistry()
    return _registry.select(metadata)
