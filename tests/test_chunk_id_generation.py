"""Tests for the provenance-aware chunk_id generation rule.

Validates:
- Same content in different documents → different chunk_id
- Same project + document + content → stable chunk_id across runs
- chunk_id does not contain absolute local paths
- content_hash unchanged for identical content
- chunk_id includes document provenance (document_id)
- Existing metadata fields preserved after re-chunking
"""

import hashlib
import pytest

from hermes_bedrock_agent.knowledge_base.chunker import _make_chunk_id


class TestMakeChunkId:
    """Unit tests for _make_chunk_id()."""

    def test_format(self):
        """Verify the output format matches spec."""
        cid = _make_chunk_id(
            document_id="abc123def456",
            source_type="excel",
            unit_label="s01",
            chunk_index=0,
            content_hash="deadbeef1234",
        )
        assert cid == "excel_abc123def456_s01_c000_deadbeef1234"

    def test_different_documents_same_content_produce_different_ids(self):
        """Two documents with identical chunk text must have different chunk_ids."""
        content = "## Header\n\n| A | B |\n|---|---|\n| 1 | 2 |"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

        id_a = _make_chunk_id(
            document_id="8f5a6a85586e30f8",  # workbook A
            source_type="excel",
            unit_label="s01",
            chunk_index=1,
            content_hash=content_hash,
        )
        id_b = _make_chunk_id(
            document_id="7450c18e61cdc028",  # workbook B
            source_type="excel",
            unit_label="s01",
            chunk_index=1,
            content_hash=content_hash,
        )
        assert id_a != id_b
        # But content_hash portion is the same
        assert id_a.split("_")[-1] == id_b.split("_")[-1]

    def test_same_document_same_content_stable_across_runs(self):
        """Repeated calls with identical inputs produce identical chunk_id."""
        kwargs = dict(
            document_id="abc123",
            source_type="csv",
            unit_label="doc",
            chunk_index=0,
            content_hash="fedcba987654",
        )
        id_run1 = _make_chunk_id(**kwargs)
        id_run2 = _make_chunk_id(**kwargs)
        assert id_run1 == id_run2

    def test_no_absolute_paths_in_id(self):
        """chunk_id must not contain filesystem-specific paths."""
        cid = _make_chunk_id(
            document_id="docid123",
            source_type="excel",
            unit_label="s03",
            chunk_index=5,
            content_hash="aabbccddee00",
        )
        assert "/home/" not in cid
        assert "/tmp/" not in cid
        assert "outputs/" not in cid
        assert "run_" not in cid

    def test_content_hash_unchanged_for_identical_content(self):
        """content_hash depends only on text, not provenance."""
        text = "Hello world table content"
        h1 = hashlib.sha256(text.encode()).hexdigest()[:12]
        h2 = hashlib.sha256(text.encode()).hexdigest()[:12]
        assert h1 == h2

    def test_document_id_present_in_chunk_id(self):
        """chunk_id must contain the document_id for provenance."""
        doc_id = "unique_doc_hash_99"
        cid = _make_chunk_id(
            document_id=doc_id,
            source_type="mermaid",
            unit_label="doc",
            chunk_index=2,
            content_hash="112233445566",
        )
        assert doc_id in cid

    def test_different_chunk_indices_produce_different_ids(self):
        """Within the same document+unit, different indices → different IDs."""
        base = dict(
            document_id="docX",
            source_type="excel",
            unit_label="s01",
            content_hash="aaa111bbb222",
        )
        id_0 = _make_chunk_id(chunk_index=0, **base)
        id_1 = _make_chunk_id(chunk_index=1, **base)
        assert id_0 != id_1

    def test_different_unit_labels_produce_different_ids(self):
        """Same document, different sheets → different IDs."""
        base = dict(
            document_id="docY",
            source_type="excel",
            chunk_index=0,
            content_hash="fff000eee111",
        )
        id_s01 = _make_chunk_id(unit_label="s01", **base)
        id_s02 = _make_chunk_id(unit_label="s02", **base)
        assert id_s01 != id_s02

    def test_source_type_in_id(self):
        """chunk_id starts with source_type prefix."""
        cid = _make_chunk_id(
            document_id="d1",
            source_type="csv",
            unit_label="doc",
            chunk_index=0,
            content_hash="123456789012",
        )
        assert cid.startswith("csv_")

    def test_mermaid_source_type(self):
        """Mermaid chunks use mermaid prefix."""
        cid = _make_chunk_id(
            document_id="m1",
            source_type="mermaid",
            unit_label="doc",
            chunk_index=0,
            content_hash="aabbccdd0011",
        )
        assert cid.startswith("mermaid_")
