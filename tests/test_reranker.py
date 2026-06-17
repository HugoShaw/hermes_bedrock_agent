"""Tests for Bedrock reranker module."""
from __future__ import annotations

import json
import os
import unittest
from concurrent.futures import TimeoutError as FuturesTimeoutError
from unittest.mock import MagicMock, patch

from hermes_bedrock_agent.knowledge_base.schemas import RetrievedChunk
from hermes_bedrock_agent.retrieval.reranker import (
    RerankConfig,
    RerankResult,
    load_rerank_config,
    rerank_chunks,
)
from hermes_bedrock_agent.retrieval.trace import RerankTrace, RetrievalTrace


def _make_chunk(chunk_id: str, content: str = "text", score: float = 0.5, **kwargs) -> RetrievedChunk:
    """Helper to create test chunks with full provenance."""
    defaults = dict(
        chunk_id=chunk_id,
        content=content,
        chunk_type=kwargs.pop("chunk_type", "overview"),
        sheet_index=kwargs.pop("sheet_index", 0),
        sheet_name=kwargs.pop("sheet_name", "sheet_01"),
        score=score,
        source_pdf_s3_path=kwargs.pop("source_pdf_s3_path", "s3://bucket/file.pdf"),
        source_excel_s3_path=kwargs.pop("source_excel_s3_path", "s3://bucket/file.xlsx"),
        project_id=kwargs.pop("project_id", "test_project"),
        parsed_markdown_path=kwargs.pop("parsed_markdown_path", "/md/path"),
        document_id=kwargs.pop("document_id", "doc_001"),
        document_name=kwargs.pop("document_name", "TestDoc.xlsx"),
        document_type=kwargs.pop("document_type", "excel"),
        source_markdown_file=kwargs.pop("source_markdown_file", "/src/md"),
        evidence_path=kwargs.pop("evidence_path", "/evidence/path"),
        evidence_paths=kwargs.pop("evidence_paths", '["a.pdf"]'),
        source_file=kwargs.pop("source_file", "input.xlsx"),
        source_type=kwargs.pop("source_type", "excel"),
        parser_type=kwargs.pop("parser_type", "vlm"),
    )
    defaults.update(kwargs)
    return RetrievedChunk(**defaults)


def _mock_rerank_response(indices_and_scores):
    """Create a mock invoke_model response."""
    mock_response = {"body": MagicMock()}
    body_content = json.dumps({
        "results": [
            {"index": idx, "relevance_score": score}
            for idx, score in indices_and_scores
        ]
    })
    mock_response["body"].read.return_value = body_content.encode()
    return mock_response


class TestLoadRerankConfigDefaults(unittest.TestCase):
    def test_load_rerank_config_defaults(self):
        """Verify defaults when no env vars set."""
        env_keys = [
            "RERANK_ENABLED", "RERANK_MODEL_ID", "RERANK_CANDIDATE_K",
            "RERANK_TOP_K", "RERANK_FALLBACK_ON_ERROR", "RERANK_TIMEOUT_SECONDS",
        ]
        cleaned = {k: os.environ.pop(k, None) for k in env_keys}
        try:
            cfg = load_rerank_config()
            assert cfg.enabled is False
            assert cfg.model_id == "amazon.rerank-v1:0"
            assert cfg.candidate_k == 30
            assert cfg.top_k == 5
            assert cfg.fallback_on_error is True
            assert cfg.timeout_seconds == 30
        finally:
            for k, v in cleaned.items():
                if v is not None:
                    os.environ[k] = v


class TestLoadRerankConfigFromEnv(unittest.TestCase):
    def test_load_rerank_config_from_env(self):
        """Verify config loads from env vars."""
        env = {
            "RERANK_ENABLED": "true",
            "RERANK_MODEL_ID": "custom.model:1",
            "RERANK_CANDIDATE_K": "50",
            "RERANK_TOP_K": "10",
            "RERANK_FALLBACK_ON_ERROR": "false",
            "RERANK_TIMEOUT_SECONDS": "60",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_rerank_config()
            assert cfg.enabled is True
            assert cfg.model_id == "custom.model:1"
            assert cfg.candidate_k == 50
            assert cfg.top_k == 10
            assert cfg.fallback_on_error is False
            assert cfg.timeout_seconds == 60


class TestRerankDisabled(unittest.TestCase):
    def test_rerank_disabled_returns_original(self):
        """When enabled=False, chunks returned as-is (truncated to top_k)."""
        chunks = [_make_chunk(f"c{i}", score=0.9 - i * 0.1) for i in range(10)]
        cfg = RerankConfig(enabled=False, top_k=5)
        result = rerank_chunks("test query", chunks, rerank_cfg=cfg)

        assert result.reranked is False
        assert len(result.chunks) == 5
        assert result.chunks[0].chunk_id == "c0"
        assert result.chunks[4].chunk_id == "c4"


class TestRerankSuccess(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_success_reorders_chunks(self, mock_boto3):
        """Mock successful rerank, verify reordering."""
        chunks = [
            _make_chunk("c0", content="first", score=0.9),
            _make_chunk("c1", content="second", score=0.8),
            _make_chunk("c2", content="third", score=0.7),
            _make_chunk("c3", content="fourth", score=0.6),
            _make_chunk("c4", content="fifth", score=0.5),
        ]

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_rerank_response([
            (2, 0.97),
            (0, 0.85),
            (4, 0.72),
        ])

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=5)
        result = rerank_chunks("test query", chunks, rerank_cfg=cfg)

        assert result.reranked is True
        assert len(result.chunks) == 3
        assert result.chunks[0].chunk_id == "c2"
        assert result.chunks[1].chunk_id == "c0"
        assert result.chunks[2].chunk_id == "c4"


class TestRerankPreservesProvenance(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_preserves_provenance_metadata(self, mock_boto3):
        """All provenance fields preserved after rerank."""
        chunk = _make_chunk(
            "prov1",
            content="provenance test",
            score=0.8,
            document_id="doc_999",
            document_name="Provenance.xlsx",
            document_type="excel",
            source_markdown_file="/prov/md",
            evidence_path="/prov/evidence",
            evidence_paths='["/x.pdf", "/y.pdf"]',
            source_file="prov_input.xlsx",
            source_type="excel",
            parser_type="excel_vlm",
            source_pdf_s3_path="s3://bucket/prov.pdf",
            source_excel_s3_path="s3://bucket/prov.xlsx",
            project_id="prov_project",
            parsed_markdown_path="/prov/parsed",
            chunk_type="api_spec",
            sheet_index=3,
            sheet_name="sheet_03",
        )

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_rerank_response([(0, 0.95)])

        cfg = RerankConfig(enabled=True, top_k=1, candidate_k=5)
        result = rerank_chunks("test", [chunk], rerank_cfg=cfg)

        reranked = result.chunks[0]
        assert reranked.chunk_id == "prov1"
        assert reranked.document_id == "doc_999"
        assert reranked.document_name == "Provenance.xlsx"
        assert reranked.document_type == "excel"
        assert reranked.source_markdown_file == "/prov/md"
        assert reranked.evidence_path == "/prov/evidence"
        assert reranked.evidence_paths == '["/x.pdf", "/y.pdf"]'
        assert reranked.source_file == "prov_input.xlsx"
        assert reranked.source_type == "excel"
        assert reranked.parser_type == "excel_vlm"
        assert reranked.source_pdf_s3_path == "s3://bucket/prov.pdf"
        assert reranked.source_excel_s3_path == "s3://bucket/prov.xlsx"
        assert reranked.project_id == "prov_project"
        assert reranked.chunk_type == "api_spec"
        assert reranked.sheet_index == 3
        assert reranked.sheet_name == "sheet_03"


class TestRerankTopK(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_respects_top_k(self, mock_boto3):
        """Only top_k chunks returned."""
        chunks = [_make_chunk(f"c{i}", score=0.9 - i * 0.05) for i in range(10)]

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_rerank_response([
            (i, 0.9 - i * 0.1) for i in range(3)
        ])

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=10)
        result = rerank_chunks("test", chunks, rerank_cfg=cfg)

        assert len(result.chunks) == 3


class TestRerankCandidateK(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_respects_candidate_k(self, mock_boto3):
        """Only candidate_k chunks sent to model."""
        chunks = [_make_chunk(f"c{i}", content=f"text {i}", score=0.9 - i * 0.05) for i in range(20)]

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_rerank_response([
            (0, 0.9), (1, 0.8), (2, 0.7),
        ])

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=5)
        result = rerank_chunks("test", chunks, rerank_cfg=cfg)

        call_args = mock_client.invoke_model.call_args
        body = json.loads(call_args.kwargs["body"])
        assert len(body["documents"]) == 5


class TestRerankFallbackOnError(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_fallback_on_error(self, mock_boto3):
        """When API fails with fallback_on_error=True, returns original ordering."""
        chunks = [_make_chunk(f"c{i}", score=0.9 - i * 0.1) for i in range(5)]

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.side_effect = RuntimeError("API Error")

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=5, fallback_on_error=True)
        result = rerank_chunks("test", chunks, rerank_cfg=cfg)

        assert result.reranked is False
        assert "API Error" in result.error
        assert len(result.chunks) == 3
        assert result.chunks[0].chunk_id == "c0"


class TestRerankRaisesOnErrorNoFallback(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_raises_on_error_no_fallback(self, mock_boto3):
        """When API fails with fallback_on_error=False, raises."""
        chunks = [_make_chunk("c0", score=0.9)]

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.side_effect = RuntimeError("API Error")

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=5, fallback_on_error=False)
        with self.assertRaises(RuntimeError):
            rerank_chunks("test", chunks, rerank_cfg=cfg)


class TestRerankTimeoutHandling(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.ThreadPoolExecutor")
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_timeout_handling(self, mock_boto3, mock_executor_cls):
        """When API hangs, timeout triggers and fallback works."""
        chunks = [_make_chunk(f"c{i}", score=0.9 - i * 0.1) for i in range(5)]

        mock_executor = MagicMock()
        mock_executor_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_executor_cls.return_value.__exit__ = MagicMock(return_value=False)

        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeoutError()
        mock_executor.submit.return_value = mock_future

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=5, fallback_on_error=True, timeout_seconds=5)
        result = rerank_chunks("test", chunks, rerank_cfg=cfg)

        assert result.reranked is False
        assert "timed out" in result.error
        assert len(result.chunks) == 3


class TestRerankResultScores(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    def test_rerank_result_scores(self, mock_boto3):
        """rerank_scores dict populated correctly."""
        chunks = [
            _make_chunk("c0", content="aaa", score=0.9),
            _make_chunk("c1", content="bbb", score=0.8),
            _make_chunk("c2", content="ccc", score=0.7),
        ]

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_rerank_response([
            (1, 0.95),
            (0, 0.80),
            (2, 0.60),
        ])

        cfg = RerankConfig(enabled=True, top_k=3, candidate_k=5)
        result = rerank_chunks("test", chunks, rerank_cfg=cfg)

        assert result.rerank_scores["c1"] == 0.95
        assert result.rerank_scores["c0"] == 0.80
        assert result.rerank_scores["c2"] == 0.60
        assert result.chunks[0].score == 0.95
        assert result.chunks[1].score == 0.8
        assert result.chunks[2].score == 0.6


class TestRerankTracePopulated(unittest.TestCase):
    def test_rerank_trace_populated(self):
        """RerankTrace fields populated correctly."""
        trace = RerankTrace()
        assert trace.enabled is False
        assert trace.model_id == ""
        assert trace.candidate_count == 0
        assert trace.final_count == 0
        assert trace.reranked is False
        assert trace.error == ""
        assert trace.latency_ms == 0.0
        assert trace.rank_comparison == []

        trace.enabled = True
        trace.model_id = "amazon.rerank-v1:0"
        trace.candidate_count = 15
        trace.final_count = 5
        trace.reranked = True
        trace.latency_ms = 234.5
        trace.rank_comparison = [{"chunk_id": "c0", "hybrid_rank": 3, "rerank_rank": 1}]

        assert trace.enabled is True
        assert trace.final_count == 5
        assert len(trace.rank_comparison) == 1


class TestRetrievalTraceHasRerank(unittest.TestCase):
    def test_retrieval_trace_has_rerank(self):
        """RetrievalTrace includes rerank field."""
        t = RetrievalTrace()
        assert hasattr(t, "rerank")
        assert isinstance(t.rerank, RerankTrace)


class TestHybridRetrieveWithRerank(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.boto3")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_hybrid_retrieve_with_rerank_enabled(self, mock_vector, mock_keyword, mock_boto3):
        """Integration: hybrid_retrieve calls rerank when enabled."""
        mock_vector.return_value = [
            _make_chunk("v0", content="vector first", score=0.9),
            _make_chunk("v1", content="vector second", score=0.8),
            _make_chunk("v2", content="vector third", score=0.7),
        ]
        mock_keyword.return_value = []

        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = _mock_rerank_response([
            (2, 0.95),
            (0, 0.80),
        ])

        from hermes_bedrock_agent.retrieval.hybrid_retriever import hybrid_retrieve
        from hermes_bedrock_agent.config import Config

        with patch.dict(os.environ, {"RERANK_ENABLED": "true", "RERANK_TOP_K": "2"}):
            result = hybrid_retrieve(query="test query", top_k=5, cfg=Config())

        assert len(result.chunks) == 2
        assert result.chunks[0].chunk_id == "v2"
        assert result.chunks[1].chunk_id == "v0"

    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_hybrid_retrieve_rerank_disabled_unchanged(self, mock_vector, mock_keyword):
        """Integration: no change when disabled."""
        mock_vector.return_value = [
            _make_chunk("v0", content="first", score=0.9),
            _make_chunk("v1", content="second", score=0.8),
            _make_chunk("v2", content="third", score=0.7),
        ]
        mock_keyword.return_value = []

        from hermes_bedrock_agent.retrieval.hybrid_retriever import hybrid_retrieve
        from hermes_bedrock_agent.config import Config

        with patch.dict(os.environ, {"RERANK_ENABLED": "false"}):
            result = hybrid_retrieve(query="test query", top_k=3, cfg=Config())

        assert len(result.chunks) == 3
        assert result.chunks[0].chunk_id == "v0"
        assert result.chunks[1].chunk_id == "v1"
        assert result.chunks[2].chunk_id == "v2"


if __name__ == "__main__":
    unittest.main()
