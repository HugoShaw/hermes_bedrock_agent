"""
V2 Document schemas — DocumentRecord and SectionRecord.

These represent the document inventory and section breakdown
used across the V2 pipeline for evidence store building and graph extraction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DocumentRecord(BaseModel):
    """Represents a single document in the V2 pipeline.

    Each document is a unit from S3 or local filesystem that has been
    parsed and normalized. Documents are broken into sections, which
    are then chunked into evidence chunks.
    """

    document_id: str = Field(..., description="Unique document identifier (sha256 of source_path + dataset)")
    project: str = Field(default="murata", description="Project name")
    dataset: str = Field(default="murata", description="Dataset name")
    run_id: str = Field(default="murata_semantic_v2", description="Run identifier")
    source_path: str = Field(..., description="S3 key or local file path")
    doc_type: str = Field(..., description="Document type: business_doc, api_doc, ddl, source_code, user_manual, config, test_case, etc.")
    title: str = Field(default="", description="Document title")
    language: str = Field(default="auto", description="Language: ja, zh, en, mixed, or auto")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Flexible metadata")

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("document_id must not be empty")
        return v.strip()

    @field_validator("doc_type")
    @classmethod
    def validate_doc_type(cls, v: str) -> str:
        allowed = {
            "business_doc", "api_doc", "ddl", "source_code", "user_manual",
            "config", "test_case", "data_dict", "field_mapping", "sql_file",
            "workflow_config", "operation_doc", "glossary", "function_list",
            "unknown",
        }
        if v and v not in allowed:
            # Warn but don't block — allow extensibility
            pass
        return v

    @staticmethod
    def generate_id(source_path: str, dataset: str = "murata") -> str:
        """Generate a deterministic document_id from source_path and dataset."""
        raw = f"{dataset}:{source_path}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "DocumentRecord":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())


class SectionRecord(BaseModel):
    """Represents a section within a document.

    Sections are structural units (headings, chapters, named blocks)
    that organize the document content hierarchically.
    """

    section_id: str = Field(..., description="Unique section identifier (sha256 of document_id + heading_path)")
    document_id: str = Field(..., description="Parent document identifier")
    title: str = Field(default="", description="Section title or heading text")
    heading_path: list[str] = Field(default_factory=list, description="Hierarchical heading path, e.g. ['Chapter 1', '1.2 Payment', 'Overview']")
    level: int = Field(default=0, ge=0, le=10, description="Heading level (0=root, 1-6=standard headings)")
    text: str = Field(default="", description="Full section text content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Flexible metadata")

    @field_validator("section_id")
    @classmethod
    def validate_section_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("section_id must not be empty")
        return v.strip()

    @staticmethod
    def generate_id(document_id: str, heading_path: list[str]) -> str:
        """Generate a deterministic section_id."""
        path_str = " > ".join(heading_path) if heading_path else "root"
        raw = f"{document_id}:{path_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "SectionRecord":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())
