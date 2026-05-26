"""
Chunk builder for the V2 evidence pipeline.

Converts DocumentRecord + SectionRecord into EvidenceChunk objects.

Chunk types produced:
  summary    — document-level or section-level summary text
  section    — one chunk per meaningful section (full content)
  small      — sub-chunks split from long sections (with overlap)
  table      — detected markdown/text tables within sections
  code       — code blocks or source code file sections
  sql        — SQL statements
  api        — API endpoint documentation sections
  config     — configuration file content
  testcase   — test-related content
  operation  — operational/procedure documentation
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord, SectionRecord
from hermes_bedrock_agent.v2.schemas.evidence_schema import EvidenceChunk, ALLOWED_CHUNK_TYPES

logger = logging.getLogger(__name__)


@dataclass
class ChunkConfig:
    """Configuration for the chunk builder."""

    chunk_size: int = 1500
    chunk_overlap: int = 200
    max_chunk_size: int = 3000
    min_chunk_size: int = 100
    summary_mode: str = "extractive"
    dataset: str = "murata"
    run_id: str = "murata_semantic_v2"
    project: str = "murata"


class ChunkBuilder:
    """Build EvidenceChunk records from documents, sections, and summaries.

    Usage::

        builder = ChunkBuilder(config=ChunkConfig())
        chunks = builder.build_chunks(doc, sections, doc_summary, section_summaries)
    """

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self.config = config or ChunkConfig()
        self._chunk_index = 0  # global counter per document for deterministic IDs

    def build_chunks(
        self,
        doc: DocumentRecord,
        sections: list[SectionRecord],
        doc_summary: str = "",
        section_summaries: dict[str, str] | None = None,
    ) -> list[EvidenceChunk]:
        """Generate all evidence chunks for a document.

        Args:
            doc: The parent document record.
            sections: Parsed sections for this document.
            doc_summary: Summary text for the document (empty = skip summary chunk).
            section_summaries: {section_id: summary_text}; empty = skip.

        Returns:
            Ordered list of EvidenceChunk objects.
        """
        self._chunk_index = 0
        section_summaries = section_summaries or {}
        chunks: list[EvidenceChunk] = []

        # 1. Document-level summary chunk
        if doc_summary and doc_summary.strip():
            chunk = self._make_chunk(
                doc=doc,
                section_id=None,
                chunk_type="summary",
                title=f"Summary: {doc.title}",
                text=doc_summary.strip(),
                heading_path=[],
            )
            chunks.append(chunk)

        # 2. Per-section chunks
        for section in sections:
            sec_chunks = self._build_section_chunks(doc, section, section_summaries)
            chunks.extend(sec_chunks)

        logger.info(
            "Built %d chunks for document %s (%s)",
            len(chunks), doc.document_id, doc.source_path,
        )
        return chunks

    def _build_section_chunks(
        self,
        doc: DocumentRecord,
        section: SectionRecord,
        section_summaries: dict[str, str],
    ) -> list[EvidenceChunk]:
        """Build chunks for a single section."""
        chunks: list[EvidenceChunk] = []
        text = section.text.strip()
        if not text:
            return chunks

        # Section-level summary chunk
        summary = section_summaries.get(section.section_id, "")
        if summary and summary.strip():
            chunks.append(self._make_chunk(
                doc=doc,
                section_id=section.section_id,
                chunk_type="summary",
                title=f"Summary: {section.title}",
                text=summary.strip(),
                heading_path=section.heading_path,
            ))

        # Determine primary chunk type from doc_type
        primary_type = self._infer_chunk_type(doc, section)

        # Section chunk (full content, up to max_chunk_size)
        if len(text) <= self.config.max_chunk_size:
            chunks.append(self._make_chunk(
                doc=doc,
                section_id=section.section_id,
                chunk_type=primary_type,
                title=section.title,
                text=text,
                heading_path=section.heading_path,
            ))
        else:
            # Section too large: create section chunk (truncated) + small sub-chunks
            chunks.append(self._make_chunk(
                doc=doc,
                section_id=section.section_id,
                chunk_type=primary_type,
                title=section.title,
                text=text[:self.config.max_chunk_size],
                heading_path=section.heading_path,
            ))
            # Small sub-chunks with overlap
            small_chunks = self._split_into_small_chunks(doc, section, text)
            chunks.extend(small_chunks)

        # Detect embedded tables
        table_chunks = self._extract_tables(doc, section, text)
        chunks.extend(table_chunks)

        return chunks

    def _infer_chunk_type(self, doc: DocumentRecord, section: SectionRecord) -> str:
        """Determine the primary chunk type for a section."""
        doc_type = doc.doc_type
        ext = Path(doc.source_path).suffix.lower()

        if doc_type == "database_doc" or ext in (".sql", ".ddl"):
            return "sql"
        if doc_type == "source_code" or ext in (".java", ".py", ".js", ".ts"):
            return "code"
        if doc_type == "config" or ext in (".xml", ".yaml", ".yml", ".json", ".properties"):
            return "config"
        if doc_type == "operation_doc":
            return "operation"
        if doc_type == "test_case":
            return "testcase"
        if doc_type == "api_doc":
            return "api"

        # Default: section type
        return "section"

    def _split_into_small_chunks(
        self,
        doc: DocumentRecord,
        section: SectionRecord,
        text: str,
    ) -> list[EvidenceChunk]:
        """Split long text into overlapping small chunks."""
        chunks: list[EvidenceChunk] = []
        chunk_size = self.config.chunk_size
        overlap = self.config.chunk_overlap
        pos = 0

        while pos < len(text):
            end = min(pos + chunk_size, len(text))

            # Try to break at paragraph or sentence boundary
            if end < len(text):
                break_pos = self._find_break_point(text, pos, end)
                if break_pos > pos:
                    end = break_pos

            chunk_text = text[pos:end].strip()
            if chunk_text and len(chunk_text) >= self.config.min_chunk_size:
                chunks.append(self._make_chunk(
                    doc=doc,
                    section_id=section.section_id,
                    chunk_type="small",
                    title=f"{section.title} (part)",
                    text=chunk_text,
                    heading_path=section.heading_path,
                    extra_meta={
                        "char_start": pos,
                        "char_end": end,
                        "is_sub_chunk": True,
                    },
                ))

            # Advance with overlap
            if end >= len(text):
                break
            new_pos = end - overlap
            if new_pos <= pos:
                new_pos = pos + max(1, chunk_size // 2)
            pos = new_pos

        return chunks

    def _find_break_point(self, text: str, start: int, end: int) -> int:
        """Find a natural break point (paragraph, sentence) near end."""
        # Look for double newline (paragraph break)
        para = text.rfind("\n\n", start + (end - start) // 3, end)
        if para > start:
            return para + 2

        # Look for sentence ending
        for sep in ("。", ".\n", ". ", "！", "？", "!\n", "? "):
            sent = text.rfind(sep, start + (end - start) // 2, end)
            if sent > start:
                return sent + len(sep)

        # Look for any newline
        nl = text.rfind("\n", start + (end - start) // 2, end)
        if nl > start:
            return nl + 1

        return end

    def _extract_tables(
        self,
        doc: DocumentRecord,
        section: SectionRecord,
        text: str,
    ) -> list[EvidenceChunk]:
        """Detect and extract markdown-style tables from text."""
        chunks: list[EvidenceChunk] = []

        # Pattern: lines with | characters forming a table
        table_re = re.compile(
            r"((?:^[|].+[|]\s*\n){2,})",
            re.MULTILINE,
        )

        for match in table_re.finditer(text):
            table_text = match.group(0).strip()
            if len(table_text) >= self.config.min_chunk_size:
                chunks.append(self._make_chunk(
                    doc=doc,
                    section_id=section.section_id,
                    chunk_type="table",
                    title=f"Table in {section.title}",
                    text=table_text,
                    heading_path=section.heading_path,
                    extra_meta={
                        "char_start": match.start(),
                        "char_end": match.end(),
                    },
                ))

        return chunks

    def _make_chunk(
        self,
        doc: DocumentRecord,
        section_id: str | None,
        chunk_type: str,
        title: str,
        text: str,
        heading_path: list[str],
        extra_meta: dict[str, Any] | None = None,
    ) -> EvidenceChunk:
        """Create an EvidenceChunk with a deterministic ID."""
        content_hash = EvidenceChunk.content_hash(text)
        chunk_id = EvidenceChunk.generate_id(
            document_id=doc.document_id,
            section_id=section_id,
            chunk_index=self._chunk_index,
            content_hash=content_hash,
        )
        self._chunk_index += 1

        metadata: dict[str, Any] = {
            "source_path": doc.source_path,
            "file_name": Path(doc.source_path).name,
            "extension": Path(doc.source_path).suffix.lower(),
            "section_title": title,
            "heading_path": " > ".join(heading_path) if heading_path else "",
            "chunk_index": self._chunk_index - 1,
            "content_hash": content_hash,
        }
        if extra_meta:
            metadata.update(extra_meta)

        return EvidenceChunk(
            chunk_id=chunk_id,
            document_id=doc.document_id,
            section_id=section_id,
            project=self.config.project,
            dataset=self.config.dataset,
            run_id=self.config.run_id,
            doc_type=doc.doc_type,
            chunk_type=chunk_type,
            title=title,
            text=text,
            heading_path=heading_path,
            source_path=doc.source_path,
            language=doc.language,
            metadata=metadata,
        )
