"""Tests for retrieval/bedrock_kb_retriever.py — Bedrock Knowledge Base retrieval.

All tests use mock KB client. No real Bedrock calls.
Validates separation from text_retriever.py.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from hermes_bedrock_agent.retrieval.bedrock_kb_retriever import (
    BedrockKBRetriever,
    KBRetrieverConfig,
)
from hermes_bedrock_agent.schemas.retrieval import RetrievalSource


class TestBedrockKBRetrieve(unittest.TestCase):
    """Test single KB retrieval."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.config = KBRetrieverConfig(knowledge_base_id="kb-12345")
        self.retriever = BedrockKBRetriever(self.mock_client, config=self.config)

    def test_calls_client_retrieve(self):
        self.mock_client.retrieve.return_value = []
        self.retriever.retrieve("test query")
        self.mock_client.retrieve.assert_called_once_with(
            query="test query", kb_id="kb-12345", top_k=5
        )

    def test_returns_text_evidence(self):
        self.mock_client.retrieve.return_value = [
            {
                "content": {"text": "KB result content"},
                "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                "score": 0.85,
            }
        ]
        results = self.retriever.retrieve("query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, RetrievalSource.BEDROCK_KB)
        self.assertEqual(results[0].content, "KB result content")
        self.assertIn("s3://bucket/doc.pdf", results[0].source_uri)

    def test_custom_kb_id(self):
        self.mock_client.retrieve.return_value = []
        self.retriever.retrieve("query", knowledge_base_id="kb-other")
        _, kwargs = self.mock_client.retrieve.call_args
        self.assertEqual(kwargs["kb_id"], "kb-other")

    def test_respects_top_k(self):
        self.mock_client.retrieve.return_value = []
        self.retriever.retrieve("query", top_k=3)
        _, kwargs = self.mock_client.retrieve.call_args
        self.assertEqual(kwargs["top_k"], 3)

    def test_handles_error_gracefully(self):
        self.mock_client.retrieve.side_effect = Exception("KB unavailable")
        results = self.retriever.retrieve("query")
        self.assertEqual(results, [])

    def test_no_kb_id_returns_empty(self):
        retriever = BedrockKBRetriever(self.mock_client, config=KBRetrieverConfig())
        results = retriever.retrieve("query")
        self.assertEqual(results, [])
        self.mock_client.retrieve.assert_not_called()

    def test_evidence_has_stable_chunk_id(self):
        """KB results get synthetic chunk_ids (content hash)."""
        self.mock_client.retrieve.return_value = [
            {
                "content": {"text": "Some content"},
                "location": {"s3Location": {"uri": "s3://b/d.pdf"}},
                "score": 0.7,
            }
        ]
        results = self.retriever.retrieve("query")
        self.assertTrue(results[0].chunk_id.startswith("kb_chunk_"))
        # Same content → same chunk_id (deterministic)
        results2 = self.retriever.retrieve("query")
        self.assertEqual(results[0].chunk_id, results2[0].chunk_id)

    def test_filters_by_min_score(self):
        config = KBRetrieverConfig(knowledge_base_id="kb-1", min_score=0.5)
        retriever = BedrockKBRetriever(self.mock_client, config=config)
        self.mock_client.retrieve.return_value = [
            {"content": {"text": "high"}, "location": {}, "score": 0.8},
            {"content": {"text": "low"}, "location": {}, "score": 0.3},
        ]
        results = retriever.retrieve("query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "high")


class TestBedrockKBRetrieveMulti(unittest.TestCase):
    """Test multi-KB retrieval."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.config = KBRetrieverConfig(knowledge_base_id="kb-default")
        self.retriever = BedrockKBRetriever(self.mock_client, config=self.config)

    def test_queries_multiple_kbs(self):
        self.mock_client.retrieve.return_value = [
            {"content": {"text": "result"}, "location": {}, "score": 0.7}
        ]
        results = self.retriever.retrieve_multi("query", ["kb-1", "kb-2", "kb-3"])
        self.assertEqual(self.mock_client.retrieve.call_count, 3)
        # Results from all KBs combined
        self.assertEqual(len(results), 3)

    def test_results_sorted_by_score(self):
        # Different scores from different KBs
        self.mock_client.retrieve.side_effect = [
            [{"content": {"text": "low"}, "location": {}, "score": 0.3}],
            [{"content": {"text": "high"}, "location": {}, "score": 0.9}],
        ]
        results = self.retriever.retrieve_multi("query", ["kb-1", "kb-2"])
        self.assertEqual(results[0].content, "high")
        self.assertEqual(results[1].content, "low")

    def test_ranks_updated(self):
        self.mock_client.retrieve.side_effect = [
            [{"content": {"text": "a"}, "location": {}, "score": 0.5}],
            [{"content": {"text": "b"}, "location": {}, "score": 0.8}],
        ]
        results = self.retriever.retrieve_multi("query", ["kb-1", "kb-2"])
        self.assertEqual(results[0].rank, 0)
        self.assertEqual(results[1].rank, 1)


class TestKBRetrieverSeparation(unittest.TestCase):
    """Verify KB retriever is independent from text_retriever."""

    def test_does_not_import_opensearch(self):
        """KB retriever should not depend on OpenSearch client."""
        import hermes_bedrock_agent.retrieval.bedrock_kb_retriever as mod
        source = open(mod.__file__).read()
        # Check import statements, not docstrings
        self.assertNotIn("from hermes_bedrock_agent.clients.opensearch_client", source)
        self.assertNotIn("import opensearch", source.lower().split('"""', 2)[-1])

    def test_uses_bedrock_kb_source(self):
        mock_client = MagicMock()
        config = KBRetrieverConfig(knowledge_base_id="kb-1")
        retriever = BedrockKBRetriever(mock_client, config=config)
        mock_client.retrieve.return_value = [
            {"content": {"text": "x"}, "location": {}, "score": 0.5}
        ]
        results = retriever.retrieve("q")
        self.assertEqual(results[0].source, RetrievalSource.BEDROCK_KB)
        # NOT opensearch_text or opensearch_vector
        self.assertNotEqual(results[0].source, RetrievalSource.OPENSEARCH_TEXT)


if __name__ == "__main__":
    unittest.main()
