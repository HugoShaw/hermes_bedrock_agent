"""Chunk-level data models for the chunking and embedding stages.

DocumentChunk represents a text segment ready for embedding.
ChunkEmbedding adds the vector representation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChunkType(str, Enum):
    """Origin of a chunk's content."""

    TEXT = "text"
    CODE = "code"
    TABLE = "table"
    VISUAL_DESCRIPTION = "visual_description"
    HEADING = "heading"
    MIXED = "mixed"


class DocumentChunk(BaseModel):
    """A text segment produced by the chunking stage.

    Chunks are the atomic unit for embedding and retrieval.
    Each chunk traces back to its source document and optionally to
    specific sections or visual blocks.
    """

    chunk_id: str = Field(..., description="Stable ID: sha256(document_id + chunk_index + content_hash)")
    document_id: str = Field(..., description="Parent document ID")
    chunk_index: int = Field(..., ge=0, description="Sequential index within document")

    # Content
    content: str = Field(..., min_length=1, description="Chunk text content")
    chunk_type: ChunkType = Field(default=ChunkType.TEXT)
    token_count: int = Field(default=0, ge=0, description="Approximate token count")

    # Source traceability
    source_uri: str = Field(default="")
    source_type: str = Field(default="")
    page: Optional[int] = Field(default=None, description="Source page (if PDF)")
    section_title: str = Field(default="", description="Enclosing section title")
    char_start: int = Field(default=0, ge=0, description="Start offset in NormalizedDocument.full_text")
    char_end: int = Field(default=0, ge=0, description="End offset in NormalizedDocument.full_text")

    # Visual references
    visual_block_ids: list[str] = Field(
        default_factory=list,
        description="VisualBlock IDs whose content is included in this chunk",
    )

    # Metadata
    content_hash: str = Field(default="", description="SHA-256 of content field")
    language: str = Field(default="")
    acl: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_visual_derived(self) -> bool:
        """Check if this chunk came from VLM output."""
        return self.chunk_type == ChunkType.VISUAL_DESCRIPTION or bool(self.visual_block_ids)


class ChunkEmbedding(BaseModel):
    """A chunk with its vector embedding, ready for OpenSearch loading.

    Produced by the embedding stage. The vector field holds the dense
    embedding; metadata is preserved for filtering during retrieval.
    """

    chunk_id: str = Field(..., description="Same as DocumentChunk.chunk_id")
    document_id: str = Field(...)
    content: str = Field(..., description="Original chunk text (stored alongside vector)")
    embedding: list[float] = Field(..., description="Dense embedding vector")
    embedding_model: str = Field(default="", description="Embedding model ID used")
    embedding_dimension: int = Field(default=1024, ge=1, description="Vector dimension")

    # Embedding metadata
    embedding_time_ms: Optional[int] = Field(default=None, ge=0)
    content_hash: str = Field(default="", description="SHA-256 of content field")

    # Preserved from DocumentChunk for retrieval filtering
    source_uri: str = Field(default="")
    source_type: str = Field(default="")
    chunk_type: ChunkType = Field(default=ChunkType.TEXT)
    section_title: str = Field(default="")
    page: Optional[int] = Field(default=None)
    visual_block_ids: list[str] = Field(default_factory=list)
    language: str = Field(default="")
    acl: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
