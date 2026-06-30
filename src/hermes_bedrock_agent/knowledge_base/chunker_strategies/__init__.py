"""Type-aware chunking strategies for document-specific splitting logic.

This package provides a Strategy pattern for chunking:
- ChunkingStrategy protocol defines the interface
- ChunkingStrategyRegistry selects strategies based on document metadata
- DefaultSemanticStrategy wraps the existing _split_semantic behavior
- MermaidFlowchartStrategy splits Mermaid docs into structure-aware chunks (Phase 2)
- Feature-gated: CHUNK_STRATEGY_ENABLED=true to activate (default: false)

Architecture:
    build_chunks_from_parsed_dir()
        → ChunkingStrategyRegistry.select(metadata)
        → strategy.chunk(body, metadata, config)
        → list[ChunkResult]
"""

from .mermaid import MermaidFlowchartStrategy
from .protocol import ChunkConfig, ChunkMetadata, ChunkResult, ChunkingStrategy
from .registry import ChunkingStrategyRegistry, select_strategy

__all__ = [
    "ChunkConfig",
    "ChunkMetadata",
    "ChunkResult",
    "ChunkingStrategy",
    "ChunkingStrategyRegistry",
    "MermaidFlowchartStrategy",
    "select_strategy",
]
