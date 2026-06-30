"""Tests for build-kb unified parsed/ directory support.

Validates:
- build-kb reads parsed/excel/**/*.md
- build-kb reads parsed/mermaid/*.md
- Mermaid chunk is included in output
- Frontmatter does not enter chunk text
- Metadata is preserved from frontmatter
"""
import json
import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir
from hermes_bedrock_agent.knowledge_base.schemas import Chunk


# ─── Fixtures ────────────────────────────────────────────────────────────────

EXCEL_FRONTMATTER = """\
---
project_id: "test_project"
source_file: "s3://bucket/path/to/workbook.xlsx"
source_type: "excel"
document_type: "excel"
document_role: "data_source"
parser_type: "excel_vlm"
document_id: "abc123def456"
document_name: "TestWorkbook"
original_relative_path: "path/to/workbook.xlsx"
workbook_name: "TestWorkbook"
sheet_index: 1
sheet_name: "sheet_01"
display_name: "TestWorkbook / sheet_01"
unit_type: "sheet"
evidence_path: "evidence/excel/TestWorkbook/sheet_01/"
evidence_paths:
  - "evidence/excel/TestWorkbook/sheet_01/sheet_01.pdf"
  - "evidence/excel/TestWorkbook/sheet_01/full.png"
---

# Sheet: テストシート

## 1. Overview

This is a test sheet with mapping data.

| Column A | Column B |
|----------|----------|
| Value 1  | Value 2  |
"""

MERMAID_FRONTMATTER = """\
---
project_id: "test_project"
source_file: "s3://bucket/path/to/flowchart.mmd"
source_type: "mermaid"
document_type: "flowchart"
document_role: "flowchart_source"
parser_type: "mermaid_parser"
document_id: "mermaid_001"
document_name: "flowchart"
original_relative_path: "path/to/flowchart.mmd"
display_name: "flowchart (Mermaid)"
linked_excel_workbook: "TestWorkbook"
linked_excel_sheet: null
linkage_confidence: 0.9
mermaid_preferred: true
evidence_paths:
  - "mermaid/flowchart/mermaid_structure.json"
  - "mermaid/flowchart/mermaid_raw.mmd"
---

# Mermaid Flowchart Analysis

**Source:** flowchart.mmd
**Diagram type:** flowchart
**Nodes:** 5 | **Edges:** 4 | **Subgraphs:** 2

## Functional Modules

### Module A
- □ `N1` — Process A
- □ `N2` — Process B

### Module B
- □ `N3` — Process C
- ◇ `N4` — Decision D
"""


@pytest.fixture
def unified_parsed_dir(tmp_path: Path) -> Path:
    """Create a minimal unified parsed/ directory structure."""
    parsed = tmp_path / "parsed"
    (parsed / "excel" / "TestWorkbook").mkdir(parents=True)
    (parsed / "mermaid").mkdir(parents=True)

    # Write excel sheet
    (parsed / "excel" / "TestWorkbook" / "sheet_01.md").write_text(
        EXCEL_FRONTMATTER, encoding="utf-8"
    )

    # Write mermaid file
    (parsed / "mermaid" / "flowchart.md").write_text(
        MERMAID_FRONTMATTER, encoding="utf-8"
    )

    return parsed


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestUnifiedParsedDir:
    """Tests for build_chunks_from_parsed_dir with unified layout."""

    def test_reads_parsed_excel(self, unified_parsed_dir: Path):
        """build-kb reads parsed/excel/**/*.md."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        excel_chunks = [c for c in chunks if c.source_type == "excel"]
        assert len(excel_chunks) > 0, "No excel chunks produced"

    def test_reads_parsed_mermaid(self, unified_parsed_dir: Path):
        """build-kb reads parsed/mermaid/*.md."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        mermaid_chunks = [c for c in chunks if c.source_type == "mermaid"]
        assert len(mermaid_chunks) > 0, "No mermaid chunks produced"

    def test_mermaid_chunk_included(self, unified_parsed_dir: Path):
        """Mermaid chunk is present alongside excel chunks."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        types = {c.source_type for c in chunks}
        assert "excel" in types
        assert "mermaid" in types

    def test_frontmatter_not_in_chunk_text(self, unified_parsed_dir: Path):
        """YAML frontmatter does not leak into chunk content."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        for chunk in chunks:
            text = chunk.content
            # Must not start with frontmatter delimiter followed by YAML
            assert not text.strip().startswith("---\nproject_id"), (
                f"Chunk {chunk.chunk_id} starts with frontmatter"
            )
            # Must not contain frontmatter-only metadata lines
            assert "\nproject_id:" not in text[:300], (
                f"Chunk {chunk.chunk_id} contains 'project_id:' in text"
            )
            assert "\nsource_file:" not in text[:300], (
                f"Chunk {chunk.chunk_id} contains 'source_file:' in text"
            )
            assert "\nevidence_paths:" not in text[:400], (
                f"Chunk {chunk.chunk_id} contains 'evidence_paths:' in text"
            )

    def test_excel_metadata_preserved(self, unified_parsed_dir: Path):
        """Excel chunk preserves frontmatter metadata fields."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        excel_chunks = [c for c in chunks if c.source_type == "excel"]
        ch = excel_chunks[0]

        assert ch.project_id == "test_project"
        assert ch.source_file == "s3://bucket/path/to/workbook.xlsx"
        assert ch.document_id == "abc123def456"
        assert ch.workbook_name == "TestWorkbook"
        assert ch.sheet_index == 1
        assert ch.sheet_name == "sheet_01"
        assert ch.display_name == "TestWorkbook / sheet_01"
        assert ch.parser_type == "excel_vlm"
        assert ch.document_role == "data_source"
        assert ch.evidence_paths == [
            "evidence/excel/TestWorkbook/sheet_01/sheet_01.pdf",
            "evidence/excel/TestWorkbook/sheet_01/full.png",
        ]

    def test_mermaid_metadata_preserved(self, unified_parsed_dir: Path):
        """Mermaid chunk preserves frontmatter metadata fields."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        mermaid_chunks = [c for c in chunks if c.source_type == "mermaid"]
        ch = mermaid_chunks[0]

        assert ch.project_id == "test_project"
        assert ch.source_file == "s3://bucket/path/to/flowchart.mmd"
        assert ch.document_id == "mermaid_001"
        assert ch.document_name == "flowchart"
        assert ch.document_type == "flowchart"
        assert ch.document_role == "flowchart_source"
        assert ch.parser_type == "mermaid_parser"
        assert ch.display_name == "flowchart (Mermaid)"
        assert ch.evidence_paths == [
            "mermaid/flowchart/mermaid_structure.json",
            "mermaid/flowchart/mermaid_raw.mmd",
        ]

    def test_mermaid_is_single_chunk(self, unified_parsed_dir: Path):
        """Mermaid files produce exactly 1 chunk (in _SINGLE_CHUNK_TYPES)."""
        chunks = build_chunks_from_parsed_dir(unified_parsed_dir)
        mermaid_chunks = [c for c in chunks if c.source_type == "mermaid"]
        assert len(mermaid_chunks) == 1

    def test_output_jsonl(self, unified_parsed_dir: Path, tmp_path: Path):
        """Output JSONL file is valid and contains all chunks."""
        out_path = tmp_path / "chunks.jsonl"
        chunks = build_chunks_from_parsed_dir(
            unified_parsed_dir, output_path=out_path
        )

        assert out_path.exists()
        lines = out_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(chunks)

        # Each line is valid JSON that can reconstruct a Chunk
        for line in lines:
            data = json.loads(line)
            assert "chunk_id" in data
            assert "content" in data
            assert "project_id" in data

    def test_project_id_override(self, unified_parsed_dir: Path):
        """project_id parameter overrides frontmatter when they MATCH."""
        # When CLI project_id matches frontmatter, CLI value is used (same value)
        chunks = build_chunks_from_parsed_dir(
            unified_parsed_dir, project_id="test_project"
        )
        for ch in chunks:
            assert ch.project_id == "test_project"

    def test_project_id_from_frontmatter_when_cli_empty(self, unified_parsed_dir: Path):
        """When CLI project_id is empty, frontmatter project_id is used."""
        chunks = build_chunks_from_parsed_dir(
            unified_parsed_dir, project_id=""
        )
        for ch in chunks:
            assert ch.project_id == "test_project"

    def test_project_id_mismatch_raises_error(self, unified_parsed_dir: Path):
        """CLI --project-id and frontmatter project_id mismatch → ValueError."""
        with pytest.raises(ValueError, match="project_id mismatch"):
            build_chunks_from_parsed_dir(
                unified_parsed_dir, project_id="different_project"
            )

    def test_project_id_mismatch_error_message_contains_details(self, unified_parsed_dir: Path):
        """Mismatch error message mentions both IDs and the filename."""
        with pytest.raises(ValueError) as exc_info:
            build_chunks_from_parsed_dir(
                unified_parsed_dir, project_id="wrong_project"
            )
        msg = str(exc_info.value)
        assert "wrong_project" in msg
        assert "test_project" in msg
        # Should mention the file that caused the mismatch
        assert ".md" in msg


class TestUnifiedDetection:
    """Tests for the unified vs legacy directory detection logic."""

    def test_detects_unified_with_excel_subdir(self, tmp_path: Path):
        """Directory with excel/ subdir is detected as unified."""
        parsed = tmp_path / "parsed"
        (parsed / "excel").mkdir(parents=True)
        _UNIFIED_SUBDIRS = {"excel", "mermaid", "docs", "csv", "images", "code"}
        is_unified = any((parsed / d).is_dir() for d in _UNIFIED_SUBDIRS)
        assert is_unified is True

    def test_detects_unified_with_mermaid_subdir(self, tmp_path: Path):
        """Directory with mermaid/ subdir is detected as unified."""
        parsed = tmp_path / "parsed"
        (parsed / "mermaid").mkdir(parents=True)
        _UNIFIED_SUBDIRS = {"excel", "mermaid", "docs", "csv", "images", "code"}
        is_unified = any((parsed / d).is_dir() for d in _UNIFIED_SUBDIRS)
        assert is_unified is True

    def test_detects_legacy_with_sheet_files(self, tmp_path: Path):
        """Directory with sheet_*.md files (no known subdirs) is legacy."""
        vlm_parsed = tmp_path / "vlm_parsed"
        vlm_parsed.mkdir()
        (vlm_parsed / "sheet_01.md").write_text("# content")
        (vlm_parsed / "sheet_02.md").write_text("# content")
        _UNIFIED_SUBDIRS = {"excel", "mermaid", "docs", "csv", "images", "code"}
        is_unified = any((vlm_parsed / d).is_dir() for d in _UNIFIED_SUBDIRS)
        assert is_unified is False
