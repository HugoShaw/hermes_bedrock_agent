"""Pydantic schemas for the S3 Graph ETL pipeline."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ContentType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    DIAGRAM = "diagram"
    CODE = "code"
    DDL = "ddl"


class ParserType(str, Enum):
    PYTHON_PARSER = "python_parser"
    LLM_TEXT_PARSER = "llm_text_parser"
    LLM_VISION_PARSER = "llm_vision_parser"


class RelationType(str, Enum):
    CONTAINS = "CONTAINS"
    REFERENCES = "REFERENCES"
    USES_TABLE = "USES_TABLE"
    USES_COLUMN = "USES_COLUMN"
    CALLS_API = "CALLS_API"
    IMPLEMENTS_PROCESS = "IMPLEMENTS_PROCESS"
    DESCRIBES_RULE = "DESCRIBES_RULE"
    DEPENDS_ON = "DEPENDS_ON"
    SAME_AS = "SAME_AS"
    RELATED_TO = "RELATED_TO"
    FLOWS_TO = "FLOWS_TO"


class DetectedEntity(BaseModel):
    """An entity detected during parsing."""
    name: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class DetectedRelation(BaseModel):
    """A relation detected during parsing."""
    from_name: str
    to_name: str
    relation_type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    """A parsed chunk from a document, ready for extraction."""
    id: str
    source_uri: str
    source_file: str
    page_number: int = 0
    chunk_index: int = 0
    content_type: ContentType = ContentType.TEXT
    title: str = ""
    heading_path: list[str] = Field(default_factory=list)
    text: str = ""
    structured_content: dict[str, Any] = Field(default_factory=dict)
    visual_description: str = ""
    detected_entities: list[DetectedEntity] = Field(default_factory=list)
    detected_relations: list[DetectedRelation] = Field(default_factory=list)
    evidence_text: str = ""
    confidence: float = 0.0
    parser_type: ParserType = ParserType.PYTHON_PARSER
    needs_review: bool = False


class GraphNode(BaseModel):
    """A node to be written to Neptune."""
    id: str
    label: str
    name: str
    text: str = ""
    source_uri: str = ""
    source_file: str = ""
    evidence_text: str = ""
    confidence: float = 0.0
    embedding: list[float] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """An edge to be written to Neptune."""
    id: str
    from_id: str
    to_id: str
    type: str
    evidence_text: str = ""
    confidence: float = 0.0
    source_uri: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class FileRecord(BaseModel):
    """A record in the file registry tracking processed files."""
    uri: str
    bucket: str
    key: str
    size: int = 0
    last_modified: str = ""
    etag: str = ""
    content_type: str = ""
    status: str = "pending"  # pending | processing | done | failed
    error_message: str = ""
    chunk_count: int = 0
