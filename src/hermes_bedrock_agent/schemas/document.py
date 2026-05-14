"""Document-level data models for the ingestion pipeline.

Covers the lifecycle from raw S3 object to normalized document ready for chunking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field


class SourceType(str, Enum):
    """Supported document source types."""

    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"
    DOCX = "docx"
    PPTX = "pptx"
    SPREADSHEET = "spreadsheet"
    DDL = "ddl"
    SQL = "sql"
    CODE = "code"
    CONFIG = "config"
    IMAGE = "image"
    UNKNOWN = "unknown"


class DocumentStatus(str, Enum):
    """Document processing status in the registry."""

    DISCOVERED = "discovered"
    DOWNLOADING = "downloading"
    PARSING = "parsing"
    PARSED = "parsed"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    GRAPH_EXTRACTED = "graph_extracted"
    LOADED = "loaded"
    FAILED = "failed"
    SKIPPED = "skipped"


class SourceDocument(BaseModel):
    """A raw document discovered in S3 (or other source).

    This is the first record created when a file is found during ingestion scan.
    It tracks the document through its full processing lifecycle.
    """

    document_id: str = Field(..., description="Stable hash-based ID: sha256(source_uri)")
    source_uri: str = Field(..., description="Full S3 URI (s3://bucket/key) or file path")
    source_type: SourceType = Field(default=SourceType.UNKNOWN)
    filename: str = Field(default="", description="Original filename without path")
    file_size: int = Field(default=0, ge=0, description="File size in bytes")
    content_hash: str = Field(default="", description="SHA-256 of file content for dedup/change detection")

    # S3-specific metadata
    s3_bucket: str = Field(default="", description="S3 bucket name")
    s3_key: str = Field(default="", description="S3 object key")
    s3_etag: str = Field(default="", description="S3 ETag for change detection")

    # Metadata
    status: DocumentStatus = Field(default=DocumentStatus.DISCOVERED)
    acl: list[str] = Field(default_factory=list, description="Access control labels")
    tags: dict[str, str] = Field(default_factory=dict, description="User-defined metadata tags")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_modified: Optional[Any] = Field(default=None, description="S3 LastModified")
    processed_at: Optional[datetime] = Field(default=None)

    # Processing tracking
    error_message: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0, ge=0)

    @computed_field
    @property
    def is_image(self) -> bool:
        """Check if document is an image type."""
        return self.source_type == SourceType.IMAGE

    @computed_field
    @property
    def needs_vlm(self) -> bool:
        """Check if document requires VLM (Vision Language Model) parsing."""
        return self.source_type in (SourceType.IMAGE, SourceType.PDF)


class DocumentSection(BaseModel):
    """A logical section within a normalized document.

    Provides strong typing for section boundaries. Chunker relies on these
    fields to perform section-aware splitting.
    """

    section_id: str = Field(default="", description="Unique section identifier")
    title: str = Field(default="")
    content: str = Field(default="", description="Section text content (optional, may be empty if using offsets)")
    level: int = Field(default=1, ge=0, description="Heading level (1=top)")
    page: Optional[int] = Field(default=None, description="Source page number (PDF)")
    start_offset: int = Field(default=0, ge=0, description="Start char offset in NormalizedDocument.content")
    end_offset: int = Field(default=0, ge=0, description="End char offset (0 = not set)")
    visual_block_ids: list[str] = Field(
        default_factory=list,
        description="VisualBlock IDs associated with this section",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentSection":
        """Construct from a loose dict (backward compat with parser output)."""
        return cls(
            section_id=d.get("section_id", ""),
            title=d.get("title", ""),
            content=d.get("content", ""),
            level=int(d.get("level", 1)),
            page=int(d["page"]) if d.get("page") else None,
            start_offset=int(d.get("start_offset", d.get("offset", 0))),
            end_offset=int(d.get("end_offset", 0)),
            visual_block_ids=d.get("visual_block_ids", []),
            metadata={k: v for k, v in d.items()
                      if k not in ("section_id", "title", "content", "level",
                                   "page", "start_offset", "end_offset",
                                   "offset", "visual_block_ids", "metadata")},
        )


class NormalizedDocument(BaseModel):
    """A document after parsing and normalization, ready for chunking.

    Contains structured text with section boundaries, metadata extracted
    during parsing, and references to any visual blocks.
    """

    document_id: str = Field(..., description="Same as SourceDocument.document_id")
    source_uri: str = Field(...)
    source_type: SourceType = Field(default=SourceType.UNKNOWN)

    # Content
    title: str = Field(default="", description="Document title (extracted or filename)")
    content: str = Field(default="", description="Complete normalized text content")
    sections: list[dict[str, str]] = Field(
        default_factory=list,
        description="Section boundaries: [{title, level, offset/page, ...}]",
    )
    page_count: int = Field(default=1, ge=0, description="Total pages (1 for non-PDF)")
    language: str = Field(default="", description="Detected language (e.g. python, markdown, sql)")

    # Parsing metadata
    content_hash: str = Field(default="", description="SHA-256 of original file bytes")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Parser-specific metadata")

    # Traceability
    visual_block_ids: list[str] = Field(
        default_factory=list,
        description="All VisualBlock IDs found in this document",
    )
    acl: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)

    @computed_field
    @property
    def char_count(self) -> int:
        return len(self.content)

    @computed_field
    @property
    def section_count(self) -> int:
        return len(self.sections)
