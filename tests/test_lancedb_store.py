"""Tests for vector_store/lancedb_store.py — LanceDB local backend.

Validates:
- Upsert records to temp directory
- Vector search returns top_k ranked results
- Keyword search finds text matches
- Hybrid search combines both via RRF
- Metadata filtering works
- count() and delete_collection() work
- health_check() returns correct status
- No real external service access

All tests use tempfile directories — no persistent state.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_bedrock_agent.vector_store.base import VectorStoreRecord
from hermes_bedrock_agent.vector_store.lancedb_store import LanceDBStore


def _make_records(n: int = 5, dim: int = 64) -> list[VectorStoreRecord]:
    """Create n mock records with distinct embeddings."""
    records = []
    for i in range(n):
        # Each vector is slightly different
        vec = [0.1 * (i + 1)] * dim
        records.append(VectorStoreRecord(
            chunk_id=f"chunk_{i:03d}",
            document_id=f"doc_{i // 2:03d}",
            text=f"This is chunk {i} about {'仕訳基礎' if i % 2 == 0 else '対帳単'} module",
            embedding=vec,
            source_uri=f"s3://bucket/docs/file_{i}.pdf",
            source_type="pdf",
            page=i + 1,
            section_title=f"Section {i}",
            visual_block_ids=[f"vb_{i:03d}"] if i % 3 == 0 else [],
            acl=["group:all"],
            content_hash=f"hash_{i}",
            embedding_model="titan-embed-v2",
        ))
    return records


class TestLanceDBStoreUpsert(unittest.TestCase):
    """Tests for upsert operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LanceDBStore(
            db_path=self.tmpdir,
            collection="test_collection",
        )

    def test_upsert_creates_table(self):
        """First upsert creates the table."""
        records = _make_records(3)
        count = self.store.upsert_chunks(records)
        self.assertEqual(count, 3)
        self.assertEqual(self.store.count(), 3)

    def test_upsert_appends(self):
        """Subsequent upserts append to existing table."""
        records1 = _make_records(3)
        records2 = [
            VectorStoreRecord(
                chunk_id="chunk_extra",
                document_id="doc_extra",
                text="Extra content",
                embedding=[0.5] * 64,
            )
        ]
        self.store.upsert_chunks(records1)
        self.store.upsert_chunks(records2)
        self.assertEqual(self.store.count(), 4)

    def test_upsert_empty_list(self):
        """Empty records list returns 0."""
        count = self.store.upsert_chunks([])
        self.assertEqual(count, 0)


class TestLanceDBStoreVectorSearch(unittest.TestCase):
    """Tests for vector similarity search."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LanceDBStore(
            db_path=self.tmpdir,
            collection="test_vector",
        )
        self.records = _make_records(5)
        self.store.upsert_chunks(self.records)

    def test_vector_search_returns_results(self):
        """Vector search returns results."""
        # Query similar to chunk_0 (vec = [0.1]*64)
        results = self.store.search([0.1] * 64, top_k=3)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)

    def test_vector_search_ranked_by_distance(self):
        """Results are ranked by distance (closest first)."""
        results = self.store.search([0.1] * 64, top_k=5)
        # First result should be chunk_000 (exact match)
        self.assertEqual(results[0].chunk_id, "chunk_000")
        # Distances should be non-decreasing
        for i in range(len(results) - 1):
            self.assertLessEqual(results[i].distance, results[i + 1].distance)

    def test_vector_search_top_k_limits(self):
        """top_k limits result count."""
        results = self.store.search([0.1] * 64, top_k=2)
        self.assertEqual(len(results), 2)

    def test_vector_search_has_fields(self):
        """Results have all expected fields."""
        results = self.store.search([0.1] * 64, top_k=1)
        r = results[0]
        self.assertEqual(r.chunk_id, "chunk_000")
        self.assertEqual(r.document_id, "doc_000")
        self.assertIn("仕訳基礎", r.text)
        self.assertEqual(r.source_type, "pdf")
        self.assertEqual(r.page, 1)
        self.assertEqual(r.acl, ["group:all"])

    def test_vector_search_empty_table(self):
        """Search on empty store returns empty."""
        empty_store = LanceDBStore(
            db_path=self.tmpdir, collection="empty_table"
        )
        results = empty_store.search([0.1] * 64, top_k=5)
        self.assertEqual(results, [])


class TestLanceDBStoreKeywordSearch(unittest.TestCase):
    """Tests for keyword/text search."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LanceDBStore(
            db_path=self.tmpdir,
            collection="test_keyword",
        )
        self.records = _make_records(5)
        self.store.upsert_chunks(self.records)

    def test_keyword_search_finds_matches(self):
        """Keyword search finds chunks containing the query."""
        results = self.store.keyword_search("仕訳基礎", top_k=5)
        # Chunks 0, 2, 4 contain "仕訳基礎"
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("仕訳基礎", r.text)

    def test_keyword_search_no_match(self):
        """No results for non-matching query."""
        results = self.store.keyword_search("XYZ_NONEXISTENT_TERM", top_k=5)
        self.assertEqual(len(results), 0)

    def test_keyword_search_top_k(self):
        """top_k limits keyword results."""
        results = self.store.keyword_search("chunk", top_k=2)
        self.assertLessEqual(len(results), 2)


class TestLanceDBStoreHybridSearch(unittest.TestCase):
    """Tests for hybrid search (vector + keyword RRF)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LanceDBStore(
            db_path=self.tmpdir,
            collection="test_hybrid",
            rrf_k=10,  # Small k for test differentiation
        )
        self.records = _make_records(5)
        self.store.upsert_chunks(self.records)

    def test_hybrid_search_returns_results(self):
        """Hybrid search returns fused results."""
        results = self.store.hybrid_search(
            "仕訳基礎", [0.1] * 64, top_k=3
        )
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)

    def test_hybrid_search_combines_both(self):
        """Hybrid search boosts results found by both methods."""
        # chunk_000 matches both vector ([0.1]*64) AND keyword (仕訳基礎)
        results = self.store.hybrid_search(
            "仕訳基礎", [0.1] * 64, top_k=5
        )
        # chunk_000 should be first (boosted by both signals)
        if results:
            self.assertEqual(results[0].chunk_id, "chunk_000")

    def test_hybrid_search_has_score(self):
        """Hybrid results have RRF-based scores."""
        results = self.store.hybrid_search(
            "仕訳基礎", [0.1] * 64, top_k=5
        )
        for r in results:
            self.assertGreater(r.score, 0.0)


class TestLanceDBStoreFilters(unittest.TestCase):
    """Tests for metadata filtering."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LanceDBStore(
            db_path=self.tmpdir,
            collection="test_filters",
        )
        self.records = _make_records(5)
        self.store.upsert_chunks(self.records)

    def test_filter_by_source_uri(self):
        """Filter by source_uri in vector search."""
        results = self.store.search(
            [0.1] * 64,
            top_k=10,
            filters={"source_uri": "s3://bucket/docs/file_0.pdf"},
        )
        for r in results:
            self.assertEqual(r.source_uri, "s3://bucket/docs/file_0.pdf")

    def test_filter_by_source_type(self):
        """Filter by source_type."""
        results = self.store.search(
            [0.1] * 64,
            top_k=10,
            filters={"source_type": "pdf"},
        )
        # All records are PDF, so all should match
        self.assertEqual(len(results), 5)


class TestLanceDBStoreManagement(unittest.TestCase):
    """Tests for count, delete, and health_check."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LanceDBStore(
            db_path=self.tmpdir,
            collection="test_mgmt",
        )

    def test_count_empty(self):
        """Count on empty store returns 0."""
        self.assertEqual(self.store.count(), 0)

    def test_count_after_insert(self):
        """Count returns correct number after insert."""
        self.store.upsert_chunks(_make_records(4))
        self.assertEqual(self.store.count(), 4)

    def test_delete_collection(self):
        """delete_collection removes the table."""
        self.store.upsert_chunks(_make_records(3))
        self.assertEqual(self.store.count(), 3)
        success = self.store.delete_collection()
        self.assertTrue(success)

    def test_health_check_healthy(self):
        """health_check returns healthy status."""
        self.store.upsert_chunks(_make_records(2))
        health = self.store.health_check()
        self.assertTrue(health["healthy"])
        self.assertEqual(health["backend"], "lancedb")
        self.assertEqual(health["collection"], "test_mgmt")
        self.assertEqual(health["row_count"], 2)

    def test_health_check_empty(self):
        """health_check works on empty store."""
        health = self.store.health_check()
        self.assertTrue(health["healthy"])
        self.assertEqual(health["row_count"], 0)


class TestLanceDBStorePersistence(unittest.TestCase):
    """Tests that data persists across store instances."""

    def test_reopen_same_path(self):
        """Data persists when reopening the same path/collection."""
        tmpdir = tempfile.mkdtemp()

        # Write data
        store1 = LanceDBStore(db_path=tmpdir, collection="persist_test")
        store1.upsert_chunks(_make_records(3))
        self.assertEqual(store1.count(), 3)

        # Reopen
        store2 = LanceDBStore(db_path=tmpdir, collection="persist_test")
        self.assertEqual(store2.count(), 3)

        # Search still works
        results = store2.search([0.1] * 64, top_k=2)
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
