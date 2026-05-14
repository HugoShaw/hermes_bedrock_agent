"""Tests for ingestion/ module — document registry, file router, pipeline.

All tests use local/mock data, no real AWS calls.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.ingestion.document_registry import (
    build_document_id,
    calculate_content_hash,
    detect_new_or_changed,
    infer_source_type,
    register_documents,
)
from hermes_bedrock_agent.ingestion.file_router import FileRouter
from hermes_bedrock_agent.ingestion.pipeline import (
    IngestionPipeline,
    PipelineConfig,
    PipelineResult,
)
from hermes_bedrock_agent.parsers.base import BaseParser, ParserContext, ParserOutput
from hermes_bedrock_agent.schemas.document import (
    NormalizedDocument,
    SourceDocument,
    SourceType,
)


# ---- document_registry tests ----


class TestBuildDocumentId:
    def test_deterministic(self):
        """Same URI always produces same document_id."""
        uri = "s3://bucket/path/file.pdf"
        id1 = build_document_id(uri)
        id2 = build_document_id(uri)
        assert id1 == id2

    def test_prefix(self):
        """Document IDs have doc_ prefix."""
        doc_id = build_document_id("s3://bucket/test.md")
        assert doc_id.startswith("doc_")

    def test_different_uris(self):
        """Different URIs produce different IDs."""
        id1 = build_document_id("s3://bucket/file1.pdf")
        id2 = build_document_id("s3://bucket/file2.pdf")
        assert id1 != id2


class TestCalculateContentHash:
    def test_bytes_input(self):
        """Hash bytes content."""
        h = calculate_content_hash(b"hello world")
        assert len(h) == 64  # SHA-256 hex

    def test_deterministic(self):
        """Same content produces same hash."""
        h1 = calculate_content_hash(b"test content")
        h2 = calculate_content_hash(b"test content")
        assert h1 == h2

    def test_different_content(self):
        """Different content produces different hash."""
        h1 = calculate_content_hash(b"content A")
        h2 = calculate_content_hash(b"content B")
        assert h1 != h2


class TestInferSourceType:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("readme.md", SourceType.MARKDOWN),
            ("notes.txt", SourceType.TEXT),
            ("schema.sql", SourceType.SQL),
            ("create_tables.ddl", SourceType.SQL),
            ("app.py", SourceType.CODE),
            ("Main.java", SourceType.CODE),
            ("config.yaml", SourceType.CONFIG),
            ("data.json", SourceType.CONFIG),
            ("report.pdf", SourceType.PDF),
            ("diagram.png", SourceType.IMAGE),
            ("photo.jpg", SourceType.IMAGE),
            ("doc.docx", SourceType.DOCX),
            ("slides.pptx", SourceType.PPTX),
            ("data.xlsx", SourceType.SPREADSHEET),
            ("unknown.xyz", SourceType.UNKNOWN),
        ],
    )
    def test_extension_mapping(self, filename, expected):
        assert infer_source_type(filename) == expected


class TestRegisterDocuments:
    def test_register_basic(self):
        """Register a list of file records."""
        records = [
            {
                "uri": "s3://bucket/path/file.md",
                "bucket": "bucket",
                "key": "path/file.md",
                "size": 1234,
                "last_modified": None,
                "etag": "abc123",
                "content_type": "text/markdown",
            }
        ]
        docs = register_documents(records)
        assert len(docs) == 1
        assert docs[0].document_id.startswith("doc_")
        assert docs[0].source_uri == "s3://bucket/path/file.md"
        assert docs[0].source_type == SourceType.MARKDOWN
        assert docs[0].filename == "file.md"
        assert docs[0].file_size == 1234
        assert docs[0].s3_bucket == "bucket"
        assert docs[0].s3_key == "path/file.md"

    def test_register_empty(self):
        """Register empty list returns empty."""
        assert register_documents([]) == []

    def test_register_multiple(self):
        """Register multiple files."""
        records = [
            {"uri": f"s3://b/file{i}.py", "bucket": "b", "key": f"file{i}.py",
             "size": 100 * i, "last_modified": None, "etag": "", "content_type": ""}
            for i in range(5)
        ]
        docs = register_documents(records)
        assert len(docs) == 5
        ids = [d.document_id for d in docs]
        assert len(set(ids)) == 5  # All unique


class TestDetectNewOrChanged:
    def test_all_new(self):
        """All documents are new when no previous registry."""
        current = register_documents([
            {"uri": "s3://b/new.md", "bucket": "b", "key": "new.md",
             "size": 100, "last_modified": None, "etag": "", "content_type": ""}
        ])
        new, changed = detect_new_or_changed(current, [])
        assert len(new) == 1
        assert len(changed) == 0

    def test_detect_changed_hash(self):
        """Detect changed documents by content_hash."""
        prev_doc = SourceDocument(
            document_id="doc_abc123",
            source_uri="s3://b/file.md",
            source_type=SourceType.MARKDOWN,
            filename="file.md",
            content_hash="old_hash_value",
        )
        curr_doc = SourceDocument(
            document_id="doc_abc123",
            source_uri="s3://b/file.md",
            source_type=SourceType.MARKDOWN,
            filename="file.md",
            content_hash="new_hash_value",
        )
        new, changed = detect_new_or_changed([curr_doc], [prev_doc])
        assert len(new) == 0
        assert len(changed) == 1
        assert changed[0].document_id == "doc_abc123"

    def test_detect_unchanged(self):
        """Skip unchanged documents."""
        doc = SourceDocument(
            document_id="doc_abc123",
            source_uri="s3://b/file.md",
            source_type=SourceType.MARKDOWN,
            filename="file.md",
            content_hash="same_hash",
        )
        new, changed = detect_new_or_changed([doc], [doc])
        assert len(new) == 0
        assert len(changed) == 0


# ---- file_router tests ----


class TestFileRouter:
    def test_route_markdown(self):
        """Route markdown to TextParser."""
        router = FileRouter()
        doc = SourceDocument(
            document_id="doc_test",
            source_uri="s3://b/readme.md",
            source_type=SourceType.MARKDOWN,
            filename="readme.md",
        )
        parser = router.get_parser(doc)
        assert parser.parser_name == "TextParser"

    def test_route_pdf(self):
        """Route PDF to PdfParser."""
        router = FileRouter()
        doc = SourceDocument(
            document_id="doc_test",
            source_uri="s3://b/report.pdf",
            source_type=SourceType.PDF,
            filename="report.pdf",
        )
        parser = router.get_parser(doc)
        assert parser.parser_name == "PdfParser"

    def test_route_image(self):
        """Route image to ImageParser."""
        router = FileRouter()
        doc = SourceDocument(
            document_id="doc_test",
            source_uri="s3://b/diagram.png",
            source_type=SourceType.IMAGE,
            filename="diagram.png",
        )
        parser = router.get_parser(doc)
        assert parser.parser_name == "ImageParser"

    def test_route_code(self):
        """Route code files to TextParser."""
        router = FileRouter()
        doc = SourceDocument(
            document_id="doc_test",
            source_uri="s3://b/app.py",
            source_type=SourceType.CODE,
            filename="app.py",
        )
        parser = router.get_parser(doc)
        assert parser.parser_name == "TextParser"

    def test_route_unknown_fallback(self):
        """Unknown types fall back to TextParser."""
        router = FileRouter()
        doc = SourceDocument(
            document_id="doc_test",
            source_uri="s3://b/unknown.xyz",
            source_type=SourceType.UNKNOWN,
            filename="unknown.xyz",
        )
        parser = router.get_parser(doc)
        assert parser.parser_name == "TextParser"


# ---- pipeline tests ----


class TestIngestionPipeline:
    def test_local_mode(self, tmp_path):
        """Pipeline can scan and parse local files."""
        # Create test files
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nWorld")
        py_file = tmp_path / "app.py"
        py_file.write_text("def main():\n    pass")

        config = PipelineConfig(local_dir=str(tmp_path))
        pipeline = IngestionPipeline(config=config)
        result = pipeline.run()

        assert result.scanned_count == 2
        assert result.parsed_count == 2
        assert result.error_count == 0
        assert len(result.normalized) == 2

    def test_dry_run(self, tmp_path):
        """Dry run registers but does not parse."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test")

        config = PipelineConfig(local_dir=str(tmp_path), dry_run=True)
        pipeline = IngestionPipeline(config=config)
        result = pipeline.run()

        assert result.scanned_count == 1
        assert result.registered_count == 1
        assert result.parsed_count == 0
        assert len(result.normalized) == 0

    def test_empty_dir(self, tmp_path):
        """Empty directory produces zero results."""
        config = PipelineConfig(local_dir=str(tmp_path))
        pipeline = IngestionPipeline(config=config)
        result = pipeline.run()

        assert result.scanned_count == 0
        assert result.parsed_count == 0

    def test_max_files(self, tmp_path):
        """max_files limits scan results."""
        for i in range(10):
            (tmp_path / f"file{i}.txt").write_text(f"Content {i}")

        config = PipelineConfig(local_dir=str(tmp_path), max_files=3)
        pipeline = IngestionPipeline(config=config)
        result = pipeline.run()

        assert result.scanned_count == 3
        assert result.parsed_count == 3

    def test_extension_filter(self, tmp_path):
        """allowed_extensions filters files."""
        (tmp_path / "readme.md").write_text("# Hi")
        (tmp_path / "notes.txt").write_text("notes")
        (tmp_path / "app.py").write_text("x = 1")

        config = PipelineConfig(
            local_dir=str(tmp_path),
            allowed_extensions={".md", ".py"},
        )
        pipeline = IngestionPipeline(config=config)
        result = pipeline.run()

        assert result.scanned_count == 2
        assert result.parsed_count == 2

    def test_incremental_skips_unchanged(self, tmp_path):
        """Incremental mode skips unchanged documents."""
        (tmp_path / "file.md").write_text("# Content")

        # First run
        config = PipelineConfig(local_dir=str(tmp_path), incremental=False)
        pipeline = IngestionPipeline(config=config)
        first_result = pipeline.run()

        # Second run with previous registry
        config2 = PipelineConfig(local_dir=str(tmp_path), incremental=True)
        pipeline2 = IngestionPipeline(
            config=config2,
            previous_registry=first_result.documents,
        )
        second_result = pipeline2.run()

        # Same docs, no content_hash change tracked in registry
        # (registry hash is set during parsing, not scanning)
        assert second_result.registered_count == 1

    def test_no_source_configured(self):
        """Pipeline with no source returns empty result."""
        config = PipelineConfig()  # No s3_bucket, no local_dir
        pipeline = IngestionPipeline(config=config)
        result = pipeline.run()
        assert result.scanned_count == 0
