"""Core document models for multi-format project parsing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DocumentRole(str, Enum):
    CONTRACT = "contract"
    SPECIFICATION = "specification"
    TEST_CASE = "test_case"
    DESIGN_DOC = "design_doc"
    DATA_MAPPING = "data_mapping"
    PROCESS_FLOW = "process_flow"
    MEETING_NOTES = "meeting_notes"
    CONFIGURATION = "configuration"
    DATA_SAMPLE = "data_sample"
    SCREENSHOT = "screenshot"
    ASSET = "asset"
    UNKNOWN = "unknown"


def generate_doc_id(project_id: str, relative_path: str) -> str:
    """Deterministic document ID from project + path. Stable across re-runs."""
    raw = f"{project_id}::{relative_path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class FileState(str, Enum):
    DISCOVERED = "discovered"
    QUEUED = "queued"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"
    CHUNKED = "chunked"
    INDEXED = "indexed"


class SourceType(str, Enum):
    EXCEL_SHEET = "excel_sheet"
    PDF_NATIVE = "pdf_native"
    DOCX = "docx"
    PPTX = "pptx"
    CSV = "csv"
    CODE = "code"
    MARKDOWN = "markdown"
    MERMAID = "mermaid"
    IMAGE = "image"
    HTML = "html"
    PLAINTEXT = "plaintext"
    UNKNOWN = "unknown"


EXTENSION_MAP: dict[str, SourceType] = {
    ".xlsx": SourceType.EXCEL_SHEET,
    ".xls": SourceType.EXCEL_SHEET,
    ".xlsm": SourceType.EXCEL_SHEET,
    ".pdf": SourceType.PDF_NATIVE,
    ".docx": SourceType.DOCX,
    ".doc": SourceType.DOCX,
    ".pptx": SourceType.PPTX,
    ".csv": SourceType.CSV,
    ".tsv": SourceType.CSV,
    ".java": SourceType.CODE,
    ".py": SourceType.CODE,
    ".sql": SourceType.CODE,
    ".xml": SourceType.CODE,
    ".json": SourceType.CODE,
    ".yaml": SourceType.CODE,
    ".yml": SourceType.CODE,
    ".properties": SourceType.CODE,
    ".sh": SourceType.CODE,
    ".bat": SourceType.CODE,
    ".md": SourceType.MARKDOWN,
    ".mmd": SourceType.MERMAID,
    ".mermaid": SourceType.MERMAID,
    ".png": SourceType.IMAGE,
    ".jpg": SourceType.IMAGE,
    ".jpeg": SourceType.IMAGE,
    ".gif": SourceType.IMAGE,
    ".tiff": SourceType.IMAGE,
    ".bmp": SourceType.IMAGE,
    ".html": SourceType.HTML,
    ".htm": SourceType.HTML,
    ".txt": SourceType.PLAINTEXT,
    ".log": SourceType.PLAINTEXT,
}

SKIP_FILENAMES = {
    "thumbs.db", ".ds_store", "desktop.ini", ".gitkeep",
}

SKIP_PREFIXES = ("__macosx", "~$")


def classify_extension(filename: str) -> SourceType:
    """Classify a filename by its extension."""
    lower = filename.lower()
    for prefix in SKIP_PREFIXES:
        if lower.startswith(prefix):
            return SourceType.UNKNOWN
    from pathlib import PurePosixPath
    ext = PurePosixPath(lower).suffix
    return EXTENSION_MAP.get(ext, SourceType.UNKNOWN)


def should_skip(filename: str) -> bool:
    """Return True if this file should be skipped during scanning."""
    lower = filename.lower()
    if lower in SKIP_FILENAMES:
        return True
    for prefix in SKIP_PREFIXES:
        if lower.startswith(prefix):
            return True
    return False


@dataclass
class ProjectFile:
    path: str
    source_type: SourceType
    size_bytes: int = 0
    relative_path: str = ""
    parent_folder: str = ""
    state: FileState = FileState.DISCOVERED
    content_hash: str = ""
    parsed_at: str = ""
    error: str = ""
    # Enhanced fields for multi-type parsing pipeline
    document_role: str = ""
    parser_type: str = ""
    skip_reason: str = ""
    parsed_output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_type": self.source_type.value,
            "size_bytes": self.size_bytes,
            "relative_path": self.relative_path,
            "parent_folder": self.parent_folder,
            "state": self.state.value,
            "content_hash": self.content_hash,
            "parsed_at": self.parsed_at,
            "error": self.error,
            "document_role": self.document_role,
            "parser_type": self.parser_type,
            "skip_reason": self.skip_reason,
            "parsed_output_path": self.parsed_output_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectFile":
        return cls(
            path=data["path"],
            source_type=SourceType(data["source_type"]),
            size_bytes=data.get("size_bytes", 0),
            relative_path=data.get("relative_path", ""),
            parent_folder=data.get("parent_folder", ""),
            state=FileState(data.get("state", FileState.DISCOVERED.value)),
            content_hash=data.get("content_hash", ""),
            parsed_at=data.get("parsed_at", ""),
            error=data.get("error", ""),
            document_role=data.get("document_role", ""),
            parser_type=data.get("parser_type", ""),
            skip_reason=data.get("skip_reason", ""),
            parsed_output_path=data.get("parsed_output_path", ""),
        )


@dataclass
class ProjectManifest:
    project_id: str
    display_name: str
    source_location: str
    files: list[ProjectFile] = field(default_factory=list)
    scan_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def file_count(self) -> int:
        return len(self.files)

    def type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.files:
            key = f.source_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def parseable_counts(self) -> dict[str, int]:
        """Return counts of parseable file types plus a total."""
        tc = self.type_counts()
        excel = tc.get(SourceType.EXCEL_SHEET.value, 0)
        pdf = tc.get(SourceType.PDF_NATIVE.value, 0)
        docx = tc.get(SourceType.DOCX.value, 0)
        csv = tc.get(SourceType.CSV.value, 0)
        return {
            "excel_count": excel,
            "pdf_count": pdf,
            "docx_count": docx,
            "csv_count": csv,
            "total_parseable": excel + pdf + docx + csv,
        }

    def total_size_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)

    def role_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.files:
            key = f.document_role or "unclassified"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "display_name": self.display_name,
            "source_location": self.source_location,
            "file_count": self.file_count,
            "type_counts": self.type_counts(),
            "parseable_counts": self.parseable_counts(),
            "role_counts": self.role_counts(),
            "total_size_bytes": self.total_size_bytes(),
            "scan_timestamp": self.scan_timestamp,
            "manifest_version": "2.0",
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectManifest":
        files = [ProjectFile.from_dict(f) for f in data.get("files", [])]
        return cls(
            project_id=data["project_id"],
            display_name=data.get("display_name", data["project_id"]),
            source_location=data.get("source_location", ""),
            files=files,
            scan_timestamp=data.get("scan_timestamp", ""),
        )


@dataclass
class ParsedDocument:
    doc_id: str
    project_id: str
    source_path: str
    source_type: SourceType
    title: str
    content_markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_paths: list[str] = field(default_factory=list)
    parent_doc_id: str = ""
    language: str = ""
    parse_method: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash and self.content_markdown:
            self.content_hash = hashlib.sha256(
                self.content_markdown.encode("utf-8")
            ).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "project_id": self.project_id,
            "source_path": self.source_path,
            "source_type": self.source_type.value,
            "title": self.title,
            "content_markdown": self.content_markdown,
            "metadata": self.metadata,
            "evidence_paths": self.evidence_paths,
            "parent_doc_id": self.parent_doc_id,
            "language": self.language,
            "parse_method": self.parse_method,
            "content_hash": self.content_hash,
        }
