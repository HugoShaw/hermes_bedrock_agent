"""Shared utilities — hashing, JSON helpers, timing decorators."""

from hermes_bedrock_agent.utils.hashing import (
    content_hash,
    file_hash,
    make_chunk_id,
    make_document_id,
    make_entity_id,
    make_evidence_id,
    make_relation_id,
    make_visual_id,
    sha256_hex,
)
from hermes_bedrock_agent.utils.json_utils import (
    count_jsonl,
    merge_jsonl,
    read_jsonl,
    stream_jsonl,
    write_jsonl,
)
from hermes_bedrock_agent.utils.timing import Timer, timed

__all__ = [
    # Hashing
    "sha256_hex",
    "content_hash",
    "file_hash",
    "make_document_id",
    "make_chunk_id",
    "make_visual_id",
    "make_entity_id",
    "make_relation_id",
    "make_evidence_id",
    # JSON
    "write_jsonl",
    "read_jsonl",
    "stream_jsonl",
    "count_jsonl",
    "merge_jsonl",
    # Timing
    "Timer",
    "timed",
]
