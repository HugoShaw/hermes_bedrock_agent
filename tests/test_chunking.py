"""Tests for chunking/ — StructureAwareChunker.

Validates:
- Stable chunk_id generation (deterministic)
- Section-aware splitting
- Code/SQL chunking
- VisualBlock → VISUAL_DESCRIPTION chunks
- Overlap handling
- Edge cases (empty, short docs)
"""

from __future__ import annotations

import pytest

from hermes_bedrock_agent.chunking.chunker import ChunkerConfig, StructureAwareChunker
from hermes_bedrock_agent.schemas.chunk import ChunkType, DocumentChunk
from hermes_bedrock_agent.schemas.document import (
    DocumentSection,
    NormalizedDocument,
    SourceType,
)
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType


def _make_doc(
    content: str,
    doc_id: str = "doc_test",
    source_type: SourceType = SourceType.MARKDOWN,
    sections: list | None = None,
    language: str = "",
    visual_block_ids: list | None = None,
) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=doc_id,
        source_uri=f"s3://bucket/{doc_id}.md",
        source_type=source_type,
        title="Test Doc",
        content=content,
        sections=sections or [],
        language=language,
        visual_block_ids=visual_block_ids or [],
        content_hash="abc123",
    )


class TestChunkIdStability:
    """Verify that chunk_ids are deterministic."""

    def test_same_input_same_ids(self):
        """Same document produces identical chunk_ids on repeated runs."""
        doc = _make_doc("Hello world this is a test sentence. " * 30)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=200))

        chunks_1 = chunker.chunk_document(doc)
        chunks_2 = chunker.chunk_document(doc)

        assert len(chunks_1) == len(chunks_2)
        for c1, c2 in zip(chunks_1, chunks_2):
            assert c1.chunk_id == c2.chunk_id
            assert c1.content == c2.content
            assert c1.content_hash == c2.content_hash

    def test_different_content_different_ids(self):
        """Different content produces different chunk_ids."""
        doc_a = _make_doc("Content A sentence here. " * 20)
        doc_b = _make_doc("Content B sentence here. " * 20)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=200))

        chunks_a = chunker.chunk_document(doc_a)
        chunks_b = chunker.chunk_document(doc_b)

        ids_a = {c.chunk_id for c in chunks_a}
        ids_b = {c.chunk_id for c in chunks_b}
        assert ids_a.isdisjoint(ids_b)

    def test_chunk_id_format(self):
        """chunk_id starts with 'chunk_' and has correct length."""
        doc = _make_doc("Test content that is long enough for a chunk " * 5)
        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc)

        for c in chunks:
            assert c.chunk_id.startswith("chunk_")
            assert len(c.chunk_id) == 22  # "chunk_" (6) + 16 hex


class TestBasicChunking:
    """Basic chunking behavior."""

    def test_short_doc_single_chunk(self):
        """Short document produces a single chunk."""
        doc = _make_doc("Short document content that fits in one chunk easily.")
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=500))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) == 1
        assert chunks[0].content == doc.content
        assert chunks[0].chunk_index == 0
        assert chunks[0].document_id == "doc_test"

    def test_long_doc_multiple_chunks(self):
        """Long document produces multiple chunks."""
        doc = _make_doc("This is sentence number one. " * 50)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=200, chunk_overlap=50))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) > 1
        # Chunks should be sequential
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_empty_content_no_chunks(self):
        """Empty document produces no chunks."""
        doc = _make_doc("")
        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc)
        assert chunks == []

    def test_whitespace_only_no_chunks(self):
        """Whitespace-only content produces no chunks."""
        doc = _make_doc("   \n\n   \t   ")
        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc)
        assert chunks == []

    def test_too_short_content_skipped(self):
        """Content shorter than min_chunk_size is skipped."""
        doc = _make_doc("Hi")  # 2 chars
        chunker = StructureAwareChunker(ChunkerConfig(min_chunk_size=50))
        chunks = chunker.chunk_document(doc)
        assert chunks == []

    def test_metadata_propagation(self):
        """Chunk inherits document metadata."""
        doc = _make_doc(
            "Content " * 30,
            source_type=SourceType.MARKDOWN,
        )
        doc.acl = ["team-a"]
        doc.language = "markdown"
        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc)

        assert chunks[0].source_uri == doc.source_uri
        assert chunks[0].source_type == "markdown"
        assert chunks[0].language == "markdown"
        assert chunks[0].acl == ["team-a"]

    def test_token_count_estimated(self):
        """Token count is approximately correct."""
        content = "word " * 500  # ~500 words, ~2500 chars
        doc = _make_doc(content)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=3000))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) == 1
        # ~2500 chars / 3.5 chars_per_token ≈ 714 tokens
        assert 600 < chunks[0].token_count < 800


class TestSectionAwareChunking:
    """Section-boundary-aware chunking."""

    def test_sections_respected(self):
        """Chunks break at section boundaries."""
        part_a = "Content A paragraph. " * 20
        part_b = "Content B paragraph. " * 20
        content = f"# Section A\n\n{part_a}\n\n# Section B\n\n{part_b}"
        idx_b = content.index("# Section B")
        sections = [
            {"title": "Section A", "level": "1", "start_offset": "0", "end_offset": str(idx_b)},
            {"title": "Section B", "level": "1", "start_offset": str(idx_b)},
        ]
        doc = _make_doc(content, sections=sections)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=2000, respect_sections=True))
        chunks = chunker.chunk_document(doc)

        # Should have at least 2 chunks (one per section)
        assert len(chunks) >= 2
        # First chunk should reference Section A
        assert chunks[0].section_title == "Section A"

    def test_large_section_split(self):
        """Large sections are split with sliding window."""
        large_content = "Long paragraph sentence here. " * 200  # ~6000 chars > max_chunk_size
        sections = [{"title": "Big Section", "level": "1", "start_offset": "0"}]
        doc = _make_doc(large_content, sections=sections)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=500, max_chunk_size=2000))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) > 1
        for c in chunks:
            assert c.section_title == "Big Section"

    def test_no_sections_fallback(self):
        """Without sections, falls back to sliding window."""
        doc = _make_doc("Paragraph content sentence. " * 40)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=300))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) > 1
        assert all(c.section_title == "" for c in chunks)


class TestCodeChunking:
    """Code/SQL-specific chunking."""

    def test_code_uses_larger_chunks(self):
        """Code files use code_chunk_size."""
        code = "def func_{i}():\n    return {i}\n\n" * 50
        code = "\n".join(f"def func_{i}():\n    return {i}\n" for i in range(50))
        doc = _make_doc(code, source_type=SourceType.CODE, language="python")
        chunker = StructureAwareChunker(ChunkerConfig(code_chunk_size=500, chunk_size=200))
        chunks = chunker.chunk_document(doc)

        # All chunks should be CODE type
        for c in chunks:
            assert c.chunk_type == ChunkType.CODE

    def test_sql_chunking(self):
        """SQL files use code chunking strategy."""
        sql = "\n\n".join(
            f"CREATE TABLE table_{i} (\n  id INT PRIMARY KEY,\n  name VARCHAR(100)\n);"
            for i in range(20)
        )
        doc = _make_doc(sql, source_type=SourceType.SQL, language="sql")
        chunker = StructureAwareChunker(ChunkerConfig(code_chunk_size=300))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) > 1
        assert all(c.chunk_type == ChunkType.CODE for c in chunks)


class TestVisualBlockChunking:
    """VisualBlock → VISUAL_DESCRIPTION chunk generation."""

    def test_visual_block_to_chunk(self):
        """VisualBlock produces a VISUAL_DESCRIPTION chunk."""
        doc = _make_doc("Some document text " * 30, visual_block_ids=["vis_001"])
        vb = VisualBlock(
            visual_id="vis_001",
            document_id="doc_test",
            page=1,
            visual_type=VisualType.ARCHITECTURE,
            visual_summary="System architecture with 3 microservices",
            extracted_text="API Gateway connects to Service A, B, C",
            diagram_nodes=["API Gateway", "Service A", "Service B", "Service C"],
            diagram_edges=["API Gateway -> Service A", "API Gateway -> Service B"],
            detected_entities=["API Gateway", "Service A", "Service B", "Service C"],
            confidence=0.92,
            model_name="claude-sonnet",
        )

        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc, visual_blocks=[vb])

        visual_chunks = [c for c in chunks if c.chunk_type == ChunkType.VISUAL_DESCRIPTION]
        assert len(visual_chunks) == 1

        vc = visual_chunks[0]
        assert "vis_001" in vc.visual_block_ids
        assert "architecture" in vc.content.lower()
        assert "API Gateway" in vc.content
        assert "Service A" in vc.content
        assert vc.page == 1

    def test_visual_no_image_base64_in_chunk(self):
        """image_base64 never appears in chunk content."""
        doc = _make_doc("Text content " * 20, visual_block_ids=["vis_x"])
        vb = VisualBlock(
            visual_id="vis_x",
            document_id="doc_test",
            page=1,
            image_base64="iVBORw0KGgoAAAANSUhEUg==",
            image_format="png",
            visual_type=VisualType.TABLE,
            visual_summary="Revenue table",
            extracted_text="Q1: $1M",
            table_markdown="| Q | Rev |\n|---|---|\n| Q1 | $1M |",
            confidence=0.9,
        )

        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc, visual_blocks=[vb])

        for c in chunks:
            assert "iVBORw0KGgo" not in c.content
            assert "image_base64" not in c.content

    def test_visual_table_in_chunk(self):
        """Table markdown is included in visual chunk."""
        doc = _make_doc("Document with table " * 20, visual_block_ids=["vis_t"])
        vb = VisualBlock(
            visual_id="vis_t",
            document_id="doc_test",
            page=2,
            visual_type=VisualType.TABLE,
            visual_summary="Employee list",
            table_markdown="| Name | Role |\n|---|---|\n| Alice | Engineer |",
            confidence=0.88,
        )

        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc, visual_blocks=[vb])

        visual_chunks = [c for c in chunks if c.chunk_type == ChunkType.VISUAL_DESCRIPTION]
        assert len(visual_chunks) == 1
        assert "| Name | Role |" in visual_chunks[0].content

    def test_multiple_visual_blocks(self):
        """Multiple VisualBlocks produce multiple chunks."""
        doc = _make_doc("Document " * 30, visual_block_ids=["vis_1", "vis_2", "vis_3"])
        blocks = [
            VisualBlock(
                visual_id=f"vis_{i}",
                document_id="doc_test",
                page=i,
                visual_type=VisualType.DIAGRAM,
                visual_summary=f"Diagram {i} showing component layout",
                extracted_text=f"Component_{i}_A connects to Component_{i}_B",
                confidence=0.85,
            )
            for i in range(1, 4)
        ]

        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc, visual_blocks=blocks)

        visual_chunks = [c for c in chunks if c.chunk_type == ChunkType.VISUAL_DESCRIPTION]
        assert len(visual_chunks) == 3

    def test_empty_visual_block_skipped(self):
        """VisualBlock with no useful content is skipped."""
        doc = _make_doc("Document text " * 30, visual_block_ids=["vis_empty"])
        vb = VisualBlock(
            visual_id="vis_empty",
            document_id="doc_test",
            page=1,
            # All text fields empty
        )

        chunker = StructureAwareChunker()
        chunks = chunker.chunk_document(doc, visual_blocks=[vb])

        visual_chunks = [c for c in chunks if c.chunk_type == ChunkType.VISUAL_DESCRIPTION]
        assert len(visual_chunks) == 0

    def test_visual_chunk_disabled(self):
        """include_visual_chunks=False skips visual block chunking."""
        doc = _make_doc("Document " * 30, visual_block_ids=["vis_skip"])
        vb = VisualBlock(
            visual_id="vis_skip",
            document_id="doc_test",
            page=1,
            visual_type=VisualType.DIAGRAM,
            visual_summary="This should be skipped",
            extracted_text="Skipped content",
        )

        chunker = StructureAwareChunker(ChunkerConfig(include_visual_chunks=False))
        chunks = chunker.chunk_document(doc, visual_blocks=[vb])

        visual_chunks = [c for c in chunks if c.chunk_type == ChunkType.VISUAL_DESCRIPTION]
        assert len(visual_chunks) == 0


class TestOverlap:
    """Overlap behavior."""

    def test_overlap_exists(self):
        """Consecutive chunks have overlapping content."""
        content = " ".join(f"Sentence number {i}." for i in range(50))
        doc = _make_doc(content)
        chunker = StructureAwareChunker(ChunkerConfig(chunk_size=300, chunk_overlap=100))
        chunks = chunker.chunk_document(doc)

        if len(chunks) >= 2:
            # Check some overlap between consecutive chunks
            for i in range(len(chunks) - 1):
                end_of_first = chunks[i].content[-50:]
                start_of_second = chunks[i + 1].content[:100]
                # With overlap, some text from end of chunk i should appear
                # at start of chunk i+1 (approximate check)
                # At minimum, char ranges should overlap
                if chunks[i].char_end > 0 and chunks[i + 1].char_start > 0:
                    assert chunks[i].char_end >= chunks[i + 1].char_start


class TestDocumentSection:
    """DocumentSection model tests."""

    def test_from_dict_basic(self):
        """Construct DocumentSection from dict."""
        d = {"title": "Introduction", "level": "2", "page": "3", "offset": "100"}
        section = DocumentSection.from_dict(d)

        assert section.title == "Introduction"
        assert section.level == 2
        assert section.page == 3
        assert section.start_offset == 100

    def test_from_dict_full(self):
        """Construct with all fields."""
        d = {
            "section_id": "sec_001",
            "title": "Methods",
            "content": "Section content here",
            "level": "1",
            "page": "5",
            "start_offset": "200",
            "end_offset": "500",
            "visual_block_ids": ["vis_a", "vis_b"],
        }
        section = DocumentSection.from_dict(d)

        assert section.section_id == "sec_001"
        assert section.content == "Section content here"
        assert section.start_offset == 200
        assert section.end_offset == 500
        assert section.visual_block_ids == ["vis_a", "vis_b"]

    def test_from_dict_missing_fields(self):
        """Missing fields use defaults."""
        d = {"title": "Simple"}
        section = DocumentSection.from_dict(d)

        assert section.title == "Simple"
        assert section.level == 1
        assert section.page is None
        assert section.start_offset == 0
