"""Tests for retrieval/text_retriever.py — OpenSearch text/vector/hybrid search.

All tests use mock OpenSearch client. No real OpenSearch calls.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from hermes_bedrock_agent.retrieval.text_retriever import (
    OpenSearchTextRetriever,
    TextRetrieverConfig,
)
from hermes_bedrock_agent.schemas.retrieval import RetrievalSource


def _mock_os_response(hits: list[dict], max_score: float = 1.0) -> dict:
    """Build a mock OpenSearch response."""
    return {
        "hits": {
            "total": {"value": len(hits)},
            "max_score": max_score,
            "hits": hits,
        }
    }


def _make_hit(chunk_id: str, text: str, score: float = 0.8, **extra) -> dict:
    """Build a mock OpenSearch hit."""
    source = {
        "chunk_id": chunk_id,
        "document_id": f"doc_{chunk_id}",
        "text": text,
        "source_uri": f"s3://bucket/{chunk_id}.pdf",
        "section_title": "Test Section",
        "page": 1,
        "acl": ["team-a"],
        **extra,
    }
    return {"_id": chunk_id, "_score": score, "_source": source}


class TestVectorSearch(unittest.TestCase):
    """Test vector (kNN) search."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = OpenSearchTextRetriever(self.mock_client)

    def test_calls_knn_search(self):
        self.mock_client.knn_search.return_value = _mock_os_response([])
        self.retriever.vector_search([0.1, 0.2, 0.3])
        self.mock_client.knn_search.assert_called_once()

    def test_returns_text_evidence(self):
        hits = [_make_hit("chunk_001", "Hello world", 0.95)]
        self.mock_client.knn_search.return_value = _mock_os_response(hits)
        results = self.retriever.vector_search([0.1, 0.2])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, "chunk_001")
        self.assertEqual(results[0].source, RetrievalSource.OPENSEARCH_VECTOR)

    def test_respects_top_k(self):
        self.mock_client.knn_search.return_value = _mock_os_response([])
        self.retriever.vector_search([0.1], top_k=5)
        _, kwargs = self.mock_client.knn_search.call_args
        self.assertEqual(kwargs["k"], 5)

    def test_passes_filters(self):
        self.mock_client.knn_search.return_value = _mock_os_response([])
        self.retriever.vector_search([0.1], filters={"term": {"acl": "team-a"}})
        _, kwargs = self.mock_client.knn_search.call_args
        self.assertEqual(kwargs["filters"], {"term": {"acl": "team-a"}})

    def test_handles_error_gracefully(self):
        self.mock_client.knn_search.side_effect = Exception("Connection failed")
        results = self.retriever.vector_search([0.1, 0.2])
        self.assertEqual(results, [])

    def test_evidence_has_score_and_rank(self):
        hits = [
            _make_hit("c1", "first", 0.9),
            _make_hit("c2", "second", 0.7),
        ]
        self.mock_client.knn_search.return_value = _mock_os_response(hits)
        results = self.retriever.vector_search([0.1])
        self.assertEqual(results[0].rank, 0)
        self.assertEqual(results[1].rank, 1)
        self.assertAlmostEqual(results[0].score, 0.9)


class TestKeywordSearch(unittest.TestCase):
    """Test BM25 keyword search."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = OpenSearchTextRetriever(self.mock_client)

    def test_calls_search(self):
        self.mock_client.search.return_value = _mock_os_response([])
        self.retriever.keyword_search("test query")
        self.mock_client.search.assert_called_once()

    def test_returns_text_evidence(self):
        hits = [_make_hit("chunk_002", "Matching text", 0.8)]
        self.mock_client.search.return_value = _mock_os_response(hits)
        results = self.retriever.keyword_search("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, RetrievalSource.OPENSEARCH_TEXT)

    def test_query_text_preserved(self):
        hits = [_make_hit("c1", "text", 0.5)]
        self.mock_client.search.return_value = _mock_os_response(hits)
        results = self.retriever.keyword_search("my query")
        self.assertEqual(results[0].query_text, "my query")

    def test_handles_error_gracefully(self):
        self.mock_client.search.side_effect = Exception("Timeout")
        results = self.retriever.keyword_search("query")
        self.assertEqual(results, [])


class TestHybridSearch(unittest.TestCase):
    """Test hybrid (vector + keyword) search."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = OpenSearchTextRetriever(self.mock_client)

    def test_without_embedding_returns_keyword_only(self):
        hits = [_make_hit("c1", "text", 0.8)]
        self.mock_client.search.return_value = _mock_os_response(hits)
        results = self.retriever.hybrid_search("query")
        self.assertEqual(len(results), 1)
        # knn_search should NOT be called without embedding
        self.mock_client.knn_search.assert_not_called()

    def test_with_embedding_merges_results(self):
        keyword_hits = [_make_hit("c1", "keyword match", 0.8)]
        vector_hits = [_make_hit("c2", "vector match", 0.9)]
        self.mock_client.search.return_value = _mock_os_response(keyword_hits)
        self.mock_client.knn_search.return_value = _mock_os_response(vector_hits)
        results = self.retriever.hybrid_search("query", [0.1, 0.2])
        # Should have both results (no duplicate chunk_id)
        chunk_ids = [r.chunk_id for r in results]
        self.assertIn("c1", chunk_ids)
        self.assertIn("c2", chunk_ids)

    def test_deduplicates_same_chunk(self):
        # Same chunk_id from both searches
        keyword_hits = [_make_hit("c1", "text", 0.7)]
        vector_hits = [_make_hit("c1", "text", 0.9)]
        self.mock_client.search.return_value = _mock_os_response(keyword_hits)
        self.mock_client.knn_search.return_value = _mock_os_response(vector_hits)
        results = self.retriever.hybrid_search("query", [0.1])
        # Deduplicated: only one result for c1
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, "c1")


class TestTextRetrieverConfig(unittest.TestCase):
    """Test retriever configuration."""

    def test_default_config(self):
        config = TextRetrieverConfig()
        self.assertEqual(config.top_k, 10)
        self.assertEqual(config.vector_field, "embedding")
        self.assertEqual(config.text_field, "text")

    def test_custom_config(self):
        config = TextRetrieverConfig(top_k=5, vector_field="vec", text_field="content")
        retriever = OpenSearchTextRetriever(MagicMock(), config=config)
        self.assertEqual(retriever.config.top_k, 5)

    def test_min_score_filter(self):
        mock_client = MagicMock()
        config = TextRetrieverConfig(min_score=0.5)
        retriever = OpenSearchTextRetriever(mock_client, config=config)
        hits = [
            _make_hit("c1", "high", 0.8),
            _make_hit("c2", "low", 0.3),
        ]
        mock_client.knn_search.return_value = _mock_os_response(hits)
        results = retriever.vector_search([0.1])
        # Only c1 (score 0.8) passes min_score 0.5
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, "c1")


if __name__ == "__main__":
    unittest.main()
