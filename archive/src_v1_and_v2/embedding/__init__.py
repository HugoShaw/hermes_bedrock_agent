"""Embedding layer — vectorize chunks and load into OpenSearch."""

from hermes_bedrock_agent.embedding.embedder import (
    BaseEmbedder,
    BedrockEmbedder,
    EmbedderConfig,
    MockEmbedder,
)
from hermes_bedrock_agent.embedding.opensearch_loader import (
    build_bulk_records,
    build_index_mapping,
    build_opensearch_record,
    bulk_index_chunks,
    create_index_if_not_exists,
    write_opensearch_bulk_jsonl,
)

__all__ = [
    "BaseEmbedder",
    "BedrockEmbedder",
    "EmbedderConfig",
    "MockEmbedder",
    "build_bulk_records",
    "build_index_mapping",
    "build_opensearch_record",
    "bulk_index_chunks",
    "create_index_if_not_exists",
    "write_opensearch_bulk_jsonl",
]
