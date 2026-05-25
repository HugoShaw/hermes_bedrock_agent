"""
V2 Evidence package — document loading, parsing, chunking, and JSONL persistence.

Stages:
  1. document_loader      — S3 → DocumentRecord
  2. document_structure_parser — DocumentRecord → SectionRecord
  3. summary_builder      — SectionRecord → summary text
  4. chunk_builder        — SectionRecord → EvidenceChunk
  5. evidence_store_builder — orchestrates 1-4, writes JSONL
  6. evidence_index       — LanceDB vector index (optional)
"""

from hermes_bedrock_agent.v2.evidence.jsonl_io import (
    write_jsonl,
    read_jsonl,
    append_jsonl,
    ensure_parent_dir,
)

__all__ = [
    "write_jsonl",
    "read_jsonl",
    "append_jsonl",
    "ensure_parent_dir",
]
