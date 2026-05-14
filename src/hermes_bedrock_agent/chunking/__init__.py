"""Chunking layer — splits NormalizedDocument into DocumentChunks."""

from hermes_bedrock_agent.chunking.chunker import (
    ChunkerConfig,
    StructureAwareChunker,
)

__all__ = [
    "ChunkerConfig",
    "StructureAwareChunker",
]
