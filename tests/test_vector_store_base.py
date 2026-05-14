"""Tests for vector_store/base.py — interface contract verification.

Validates:
- VectorStoreBackend cannot be instantiated directly
- VectorStoreRecord fields and defaults
- VectorSearchResult fields and defaults
- Abstract methods enforce implementation
"""

from __future__ import annotations

import unittest

from hermes_bedrock_agent.vector_store.base import (
    VectorSearchResult,
    VectorStoreBackend,
    VectorStoreRecord,
)


class TestVectorStoreRecord(unittest.TestCase):
    """Tests for VectorStoreRecord dataclass."""

    def test_required_fields(self):
        """Core fields are required."""
        record = VectorStoreRecord(
            chunk_id="chunk_001",
            document_id="doc_001",
            text="Hello world",
            embedding=[0.1] * 384,
        )
        self.assertEqual(record.chunk_id, "chunk_001")
        self.assertEqual(record.document_id, "doc_001")
        self.assertEqual(record.text, "Hello world")
        self.assertEqual(len(record.embedding), 384)

    def test_default_fields(self):
        """Optional fields have sensible defaults."""
        record = VectorStoreRecord(
            chunk_id="c1", document_id="d1", text="t", embedding=[0.1]
        )
        self.assertEqual(record.source_uri, "")
        self.assertEqual(record.source_type, "")
        self.assertIsNone(record.page)
        self.assertEqual(record.section_title, "")
        self.assertEqual(record.visual_block_ids, [])
        self.assertEqual(record.acl, [])
        self.assertEqual(record.content_hash, "")
        self.assertEqual(record.embedding_model, "")
        self.assertEqual(record.metadata, {})

    def test_full_record(self):
        """All fields can be set."""
        record = VectorStoreRecord(
            chunk_id="chunk_002",
            document_id="doc_002",
            text="仕訳基礎 module documentation",
            embedding=[0.2] * 1024,
            source_uri="s3://bucket/docs/shiwake.pdf",
            source_type="pdf",
            page=3,
            section_title="概要",
            visual_block_ids=["vb_001"],
            acl=["group:engineering"],
            content_hash="abc123",
            embedding_model="amazon.titan-embed-text-v2:0",
            metadata={"language": "ja"},
        )
        self.assertEqual(record.source_uri, "s3://bucket/docs/shiwake.pdf")
        self.assertEqual(record.page, 3)
        self.assertEqual(record.acl, ["group:engineering"])


class TestVectorSearchResult(unittest.TestCase):
    """Tests for VectorSearchResult dataclass."""

    def test_basic_result(self):
        """Basic result with required fields."""
        result = VectorSearchResult(
            chunk_id="chunk_001",
            document_id="doc_001",
            text="test content",
        )
        self.assertEqual(result.chunk_id, "chunk_001")
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.distance, 0.0)

    def test_result_with_scores(self):
        """Result with score and distance."""
        result = VectorSearchResult(
            chunk_id="c1",
            document_id="d1",
            text="content",
            score=0.95,
            distance=0.05,
        )
        self.assertEqual(result.score, 0.95)
        self.assertEqual(result.distance, 0.05)


class TestVectorStoreBackendAbstract(unittest.TestCase):
    """Tests that VectorStoreBackend cannot be instantiated directly."""

    def test_cannot_instantiate(self):
        """Abstract base cannot be instantiated."""
        with self.assertRaises(TypeError):
            VectorStoreBackend()

    def test_requires_all_methods(self):
        """Subclass missing methods cannot be instantiated."""

        class IncompleteStore(VectorStoreBackend):
            def upsert_chunks(self, records):
                return 0

        with self.assertRaises(TypeError):
            IncompleteStore()

    def test_complete_implementation_works(self):
        """Complete subclass can be instantiated."""

        class MockStore(VectorStoreBackend):
            def upsert_chunks(self, records):
                return len(records)

            def search(self, query_embedding, *, top_k=10, filters=None):
                return []

            def keyword_search(self, query, *, top_k=10, filters=None):
                return []

            def hybrid_search(self, query, query_embedding, *, top_k=10, filters=None):
                return []

            def count(self):
                return 0

            def delete_collection(self):
                return True

            def health_check(self):
                return {"healthy": True, "backend": "mock"}

        store = MockStore()
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.health_check()["backend"], "mock")

    def test_abstract_methods_list(self):
        """VectorStoreBackend defines exactly 7 abstract methods."""
        abstract_methods = VectorStoreBackend.__abstractmethods__
        expected = {
            "upsert_chunks",
            "search",
            "keyword_search",
            "hybrid_search",
            "count",
            "delete_collection",
            "health_check",
        }
        self.assertEqual(abstract_methods, expected)


if __name__ == "__main__":
    unittest.main()
