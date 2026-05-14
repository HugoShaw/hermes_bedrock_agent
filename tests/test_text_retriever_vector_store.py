"""Tests for VectorStoreTextRetriever — text retrieval via VectorStoreBackend.

Validates:
- VectorStoreTextRetriever works with LanceDB backend
- vector_search returns TextEvidence
- keyword_search returns TextEvidence
- hybrid_search returns TextEvidence
- TextEvidence fields are correctly populated
- No real OpenSearch/external service access
"""

from __future__ import annotations

import tempfile
import unittest

from hermes_bedrock_agent.retrieval.text_retriever import (
    TextRetrieverConfig,
    VectorStoreTextRetriever,
)
from hermes_bedrock_agent.schemas.retrieval import RetrievalSource, TextEvidence
from hermes_bedrock_agent.vector_store.base import VectorStoreRecord
from hermes_bedrock_agent.vector_store.lancedb_store import LanceDBStore


def _setup_store(tmpdir: str) -> LanceDBStore:
    """Create and populate a LanceDB store for testing."""
    store = LanceDBStore(db_path=tmpdir, collection="test_retriever")
    records = [
        VectorStoreRecord(
            chunk_id="chunk_001",
            document_id="doc_001",
            text="仕訳基礎はAP基盤の中核モジュールです。",
            embedding=[0.1] * 64,
            source_uri="s3://bucket/shiwake.pdf",
            source_type="pdf",
            page=1,
            section_title="概要",
            acl=["group:eng"],
        ),
        VectorStoreRecord(
            chunk_id="chunk_002",
            document_id="doc_001",
            text="対帳単は入力チェックを担当するモジュールです。",
            embedding=[0.3] * 64,
            source_uri="s3://bucket/taichou.pdf",
            source_type="pdf",
            page=5,
            section_title="対帳単",
            acl=["group:eng"],
        ),
        VectorStoreRecord(
            chunk_id="chunk_003",
            document_id="doc_002",
            text="付款申請は支払い処理のワークフローです。",
            embedding=[0.5] * 64,
            source_uri="s3://bucket/fukkinn.pdf",
            source_type="pdf",
            page=2,
            section_title="付款申請",
            acl=["group:finance"],
        ),
        VectorStoreRecord(
            chunk_id="chunk_004",
            document_id="doc_002",
            text="The payment workflow integrates with 仕訳基礎 for posting.",
            embedding=[0.15] * 64,
            source_uri="s3://bucket/integration.md",
            source_type="markdown",
            page=None,
            section_title="Integration",
            acl=["group:all"],
        ),
    ]
    store.upsert_chunks(records)
    return store


class TestVectorStoreTextRetrieverInit(unittest.TestCase):
    """Tests for VectorStoreTextRetriever initialization."""

    def test_accepts_vector_store_backend(self):
        """Accepts any VectorStoreBackend instance."""
        tmpdir = tempfile.mkdtemp()
        store = LanceDBStore(db_path=tmpdir, collection="init_test")
        retriever = VectorStoreTextRetriever(store)
        self.assertIsNotNone(retriever)

    def test_rejects_non_backend(self):
        """Raises TypeError for non-VectorStoreBackend."""
        with self.assertRaises(TypeError):
            VectorStoreTextRetriever("not_a_backend")

    def test_custom_config(self):
        """Custom config is applied."""
        tmpdir = tempfile.mkdtemp()
        store = LanceDBStore(db_path=tmpdir, collection="cfg_test")
        config = TextRetrieverConfig(top_k=5, min_score=0.3)
        retriever = VectorStoreTextRetriever(store, config=config)
        self.assertEqual(retriever.config.top_k, 5)
        self.assertEqual(retriever.config.min_score, 0.3)


class TestVectorStoreTextRetrieverVectorSearch(unittest.TestCase):
    """Tests for vector_search method."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = _setup_store(self.tmpdir)
        self.retriever = VectorStoreTextRetriever(self.store)

    def test_returns_text_evidence(self):
        """vector_search returns list of TextEvidence."""
        results = self.retriever.vector_search(
            [0.1] * 64, top_k=3, query_text="仕訳基礎"
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIsInstance(r, TextEvidence)

    def test_first_result_is_closest(self):
        """First result is the most similar chunk."""
        results = self.retriever.vector_search(
            [0.1] * 64, top_k=3, query_text="仕訳基礎"
        )
        # chunk_001 has embedding [0.1]*64 → exact match
        self.assertEqual(results[0].chunk_id, "chunk_001")

    def test_evidence_fields_populated(self):
        """TextEvidence has all fields correctly populated."""
        results = self.retriever.vector_search(
            [0.1] * 64, top_k=1, query_text="test"
        )
        ev = results[0]
        self.assertEqual(ev.chunk_id, "chunk_001")
        self.assertEqual(ev.document_id, "doc_001")
        self.assertIn("仕訳基礎", ev.content)
        self.assertEqual(ev.source_uri, "s3://bucket/shiwake.pdf")
        self.assertEqual(ev.section_title, "概要")
        self.assertEqual(ev.page, 1)
        self.assertEqual(ev.source, RetrievalSource.OPENSEARCH_VECTOR)
        self.assertGreater(ev.score, 0.0)
        self.assertEqual(ev.rank, 0)
        self.assertEqual(ev.acl, ["group:eng"])
        self.assertTrue(ev.evidence_id.startswith("te_"))

    def test_top_k_limits_results(self):
        """top_k limits the number of results."""
        results = self.retriever.vector_search(
            [0.1] * 64, top_k=2, query_text="test"
        )
        self.assertEqual(len(results), 2)


class TestVectorStoreTextRetrieverKeywordSearch(unittest.TestCase):
    """Tests for keyword_search method."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = _setup_store(self.tmpdir)
        self.retriever = VectorStoreTextRetriever(self.store)

    def test_finds_matching_chunks(self):
        """keyword_search finds chunks containing query text."""
        results = self.retriever.keyword_search("仕訳基礎", top_k=5)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("仕訳基礎", r.content)

    def test_returns_text_evidence(self):
        """Results are TextEvidence instances."""
        results = self.retriever.keyword_search("モジュール", top_k=5)
        for r in results:
            self.assertIsInstance(r, TextEvidence)
            self.assertEqual(r.source, RetrievalSource.OPENSEARCH_TEXT)

    def test_no_results_for_nonexistent(self):
        """No results for non-matching query."""
        results = self.retriever.keyword_search("ZZZZZ_NO_MATCH", top_k=5)
        self.assertEqual(len(results), 0)


class TestVectorStoreTextRetrieverHybridSearch(unittest.TestCase):
    """Tests for hybrid_search method."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = _setup_store(self.tmpdir)
        self.retriever = VectorStoreTextRetriever(self.store)

    def test_hybrid_returns_results(self):
        """hybrid_search returns fused results."""
        results = self.retriever.hybrid_search(
            "仕訳基礎", [0.1] * 64, top_k=3
        )
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)

    def test_hybrid_returns_text_evidence(self):
        """Hybrid results are TextEvidence."""
        results = self.retriever.hybrid_search(
            "仕訳基礎", [0.1] * 64, top_k=3
        )
        for r in results:
            self.assertIsInstance(r, TextEvidence)

    def test_hybrid_boosts_dual_match(self):
        """Chunk matching both vector AND keyword is ranked first."""
        # chunk_001: embedding=[0.1]*64 AND text contains "仕訳基礎"
        results = self.retriever.hybrid_search(
            "仕訳基礎", [0.1] * 64, top_k=5
        )
        if results:
            self.assertEqual(results[0].chunk_id, "chunk_001")

    def test_hybrid_without_embedding(self):
        """Falls back to keyword_search when no embedding provided."""
        results = self.retriever.hybrid_search(
            "仕訳基礎", None, top_k=3
        )
        # Should still return results (keyword only)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("仕訳基礎", r.content)


class TestVectorStoreTextRetrieverMinScore(unittest.TestCase):
    """Tests for min_score filtering."""

    def test_min_score_filters_low_scores(self):
        """Results below min_score are filtered out."""
        tmpdir = tempfile.mkdtemp()
        store = _setup_store(tmpdir)
        config = TextRetrieverConfig(min_score=0.99)
        retriever = VectorStoreTextRetriever(store, config=config)

        # Very high min_score should filter everything except exact match
        results = retriever.vector_search(
            [0.1] * 64, top_k=5, query_text="test"
        )
        # Only exact match (score≈1.0) or no results at all
        for r in results:
            self.assertGreaterEqual(r.score, 0.99)


if __name__ == "__main__":
    unittest.main()
