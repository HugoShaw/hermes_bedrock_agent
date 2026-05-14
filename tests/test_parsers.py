"""Tests for parsers/ module — TextParser, PdfParser, ImageParser, merge.

All tests use synthetic data, no real AWS calls or file downloads.
"""

from __future__ import annotations

import struct

import pytest

from hermes_bedrock_agent.parsers.base import ParserContext, ParserError, ParserOutput
from hermes_bedrock_agent.parsers.image_parser import ImageParser
from hermes_bedrock_agent.parsers.parser_merge import merge_parser_outputs
from hermes_bedrock_agent.parsers.text_parser import TextParser
from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceDocument, SourceType
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType


# ---- TextParser tests ----


class TestTextParser:
    def _make_ctx(self, content: str, filename: str, source_type: SourceType) -> ParserContext:
        doc = SourceDocument(
            document_id="doc_test123",
            source_uri=f"s3://bucket/{filename}",
            source_type=source_type,
            filename=filename,
        )
        return ParserContext(
            document=doc,
            content_bytes=content.encode("utf-8"),
        )

    def test_parse_markdown(self):
        """Parse markdown with headings."""
        content = "# Title\n\n## Section 1\n\nHello world\n\n## Section 2\n\nGoodbye"
        ctx = self._make_ctx(content, "readme.md", SourceType.MARKDOWN)
        parser = TextParser()
        output = parser.parse(ctx)

        assert output.normalized_document.title == "Title"
        assert output.normalized_document.content == content
        assert len(output.normalized_document.sections) == 3  # Title + 2 sections
        assert output.normalized_document.language == "markdown"
        assert output.visual_blocks == []

    def test_parse_python(self):
        """Parse Python code with class/function detection."""
        content = "class MyClass:\n    pass\n\ndef helper():\n    return 42\n"
        ctx = self._make_ctx(content, "app.py", SourceType.CODE)
        parser = TextParser()
        output = parser.parse(ctx)

        assert output.normalized_document.language == "python"
        sections = output.normalized_document.sections
        assert len(sections) == 2
        assert sections[0]["title"] == "MyClass"
        assert sections[1]["title"] == "helper"

    def test_parse_sql(self):
        """Parse SQL with section comments."""
        content = "-- ============ CREATE TABLES ============\nCREATE TABLE foo (id INT);\n"
        ctx = self._make_ctx(content, "schema.sql", SourceType.SQL)
        parser = TextParser()
        output = parser.parse(ctx)

        assert output.normalized_document.language == "sql"
        sections = output.normalized_document.sections
        assert len(sections) == 1
        assert "CREATE TABLES" in sections[0]["title"]

    def test_parse_plain_text(self):
        """Parse plain text (no sections)."""
        content = "Just some plain text\nwith multiple lines"
        ctx = self._make_ctx(content, "notes.txt", SourceType.TEXT)
        parser = TextParser()
        output = parser.parse(ctx)

        assert output.normalized_document.title == "notes"
        assert output.normalized_document.content == content
        assert output.normalized_document.sections == []

    def test_content_hash_populated(self):
        """Content hash is populated."""
        content = "test content"
        ctx = self._make_ctx(content, "test.md", SourceType.MARKDOWN)
        parser = TextParser()
        output = parser.parse(ctx)

        assert output.normalized_document.content_hash != ""
        assert len(output.normalized_document.content_hash) == 64

    def test_metadata_populated(self):
        """Parser metadata is populated."""
        content = "line1\nline2\nline3"
        ctx = self._make_ctx(content, "test.txt", SourceType.TEXT)
        parser = TextParser()
        output = parser.parse(ctx)

        meta = output.normalized_document.metadata
        assert meta["parser"] == "TextParser"
        assert meta["line_count"] == 3
        assert meta["char_count"] == len(content)

    def test_parser_name(self):
        parser = TextParser()
        assert parser.parser_name == "TextParser"


# ---- ImageParser tests ----


class TestImageParser:
    def _make_png_bytes(self, width: int = 100, height: int = 50) -> bytes:
        """Create minimal PNG header bytes for testing."""
        # PNG signature + IHDR
        signature = b"\x89PNG\r\n\x1a\n"
        # IHDR: length(13) + "IHDR" + width(4) + height(4) + depth(1) + color(1) + ...
        ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data
        return signature + ihdr

    def _make_jpeg_bytes(self, width: int = 200, height: int = 150) -> bytes:
        """Create minimal JPEG with SOF0 marker for testing."""
        # SOI + SOF0 marker
        soi = b"\xff\xd8"
        # SOF0: marker(2) + length(2) + precision(1) + height(2) + width(2)
        sof0 = b"\xff\xc0" + struct.pack(">HBH", 11, 8, height) + struct.pack(">H", width) + b"\x03\x01\x11\x00"
        return soi + sof0

    def test_parse_png(self):
        """Parse PNG image bytes."""
        png_bytes = self._make_png_bytes(320, 240)
        doc = SourceDocument(
            document_id="doc_img001",
            source_uri="s3://bucket/diagram.png",
            source_type=SourceType.IMAGE,
            filename="diagram.png",
        )
        ctx = ParserContext(document=doc, content_bytes=png_bytes)
        parser = ImageParser()
        output = parser.parse(ctx)

        assert output.normalized_document.document_id == "doc_img001"
        assert output.normalized_document.source_type == SourceType.IMAGE
        assert len(output.visual_blocks) == 1
        vb = output.visual_blocks[0]
        assert vb.visual_id.startswith("vis_")
        assert vb.document_id == "doc_img001"
        assert vb.image_format == "png"
        assert vb.width == 320
        assert vb.height == 240
        assert vb.confidence == 0.0  # Not yet VLM-processed

    def test_parse_jpeg(self):
        """Parse JPEG image bytes."""
        jpg_bytes = self._make_jpeg_bytes(800, 600)
        doc = SourceDocument(
            document_id="doc_img002",
            source_uri="s3://bucket/photo.jpg",
            source_type=SourceType.IMAGE,
            filename="photo.jpg",
        )
        ctx = ParserContext(document=doc, content_bytes=jpg_bytes)
        parser = ImageParser()
        output = parser.parse(ctx)

        vb = output.visual_blocks[0]
        assert vb.image_format == "jpeg"
        assert vb.width == 800
        assert vb.height == 600
        assert vb.visual_type == VisualType.PHOTOGRAPH

    def test_png_is_diagram(self):
        """PNG images default to DIAGRAM type."""
        png_bytes = self._make_png_bytes()
        doc = SourceDocument(
            document_id="doc_img003",
            source_uri="s3://bucket/arch.png",
            source_type=SourceType.IMAGE,
            filename="arch.png",
        )
        ctx = ParserContext(document=doc, content_bytes=png_bytes)
        parser = ImageParser()
        output = parser.parse(ctx)

        assert output.visual_blocks[0].visual_type == VisualType.DIAGRAM

    def test_visual_block_id_stable(self):
        """Visual block IDs are deterministic."""
        png_bytes = self._make_png_bytes()
        doc = SourceDocument(
            document_id="doc_stable",
            source_uri="s3://bucket/img.png",
            source_type=SourceType.IMAGE,
            filename="img.png",
        )
        ctx = ParserContext(document=doc, content_bytes=png_bytes)
        parser = ImageParser()

        out1 = parser.parse(ctx)
        out2 = parser.parse(ctx)
        assert out1.visual_blocks[0].visual_id == out2.visual_blocks[0].visual_id

    def test_parser_name(self):
        parser = ImageParser()
        assert parser.parser_name == "ImageParser"


# ---- parser_merge tests ----


class TestParserMerge:
    def test_merge_with_vlm_blocks(self):
        """Merge text output with VLM blocks."""
        text_doc = NormalizedDocument(
            document_id="doc_merge",
            source_uri="s3://bucket/report.pdf",
            source_type=SourceType.PDF,
            title="Report",
            content="Page 1 text content",
            sections=[{"title": "Intro", "level": "1", "page": "1"}],
            page_count=2,
            content_hash="abc123",
        )
        text_output = ParserOutput(normalized_document=text_doc)

        vlm_blocks = [
            VisualBlock(
                visual_id="vis_page1",
                document_id="doc_merge",
                source_uri="s3://bucket/report.pdf",
                page=1,
                visual_type=VisualType.TABLE,
                visual_summary="Revenue table Q1-Q4",
                extracted_text="Q1: $1M, Q2: $1.5M",
                table_markdown="| Q | Revenue |\n|---|---|\n| Q1 | $1M |",
                confidence=0.92,
                model_name="claude-sonnet",
            )
        ]

        merged = merge_parser_outputs(text_output, vlm_blocks)

        # Content should include VLM text
        assert "VLM Extracted Content" in merged.normalized_document.content
        assert "Q1: $1M, Q2: $1.5M" in merged.normalized_document.content
        assert "| Q | Revenue |" in merged.normalized_document.content

        # Visual block IDs should be merged
        assert "vis_page1" in merged.normalized_document.visual_block_ids

        # Sections should include VLM section
        titles = [s["title"] for s in merged.normalized_document.sections]
        assert any("Revenue table" in t for t in titles)

        # Metadata
        assert merged.normalized_document.metadata["vlm_merged"] is True
        assert merged.normalized_document.metadata["vlm_block_count"] == 1

    def test_merge_no_vlm_blocks(self):
        """Merge with empty VLM blocks preserves original."""
        text_doc = NormalizedDocument(
            document_id="doc_nomerge",
            source_uri="s3://bucket/plain.md",
            source_type=SourceType.MARKDOWN,
            title="Plain",
            content="Simple content",
            content_hash="def456",
        )
        text_output = ParserOutput(normalized_document=text_doc)
        merged = merge_parser_outputs(text_output, [])

        assert merged.normalized_document.content == "Simple content"
        assert merged.normalized_document.metadata.get("vlm_block_count") == 0

    def test_merge_preserves_existing_visual_ids(self):
        """Merge preserves pre-existing visual_block_ids."""
        text_doc = NormalizedDocument(
            document_id="doc_existing",
            source_uri="s3://bucket/doc.pdf",
            content="text",
            visual_block_ids=["vis_existing"],
            content_hash="xyz",
        )
        text_output = ParserOutput(
            normalized_document=text_doc,
            visual_blocks=[
                VisualBlock(
                    visual_id="vis_existing",
                    document_id="doc_existing",
                    page=1,
                )
            ],
        )

        new_vlm = [
            VisualBlock(
                visual_id="vis_new",
                document_id="doc_existing",
                page=2,
                visual_type=VisualType.DIAGRAM,
                visual_summary="Architecture",
                extracted_text="Service A -> Service B",
                confidence=0.88,
            )
        ]

        merged = merge_parser_outputs(text_output, new_vlm)
        assert "vis_existing" in merged.normalized_document.visual_block_ids
        assert "vis_new" in merged.normalized_document.visual_block_ids
        assert len(merged.visual_blocks) == 2
