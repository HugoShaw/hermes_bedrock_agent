"""Tests for hybrid retrieval pipeline: preprocessing, keyword search, hybrid merge."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from hermes_bedrock_agent.retrieval.query_preprocessing import (
    QueryIntent,
    RewrittenQueries,
    detect_intent,
    normalize_query,
    rewrite_queries,
)
from hermes_bedrock_agent.retrieval.keyword_retriever import (
    _extract_search_keywords,
    keyword_search,
)
from hermes_bedrock_agent.retrieval.hybrid_retriever import (
    HybridResult,
    hybrid_retrieve,
    _row_to_chunk,
)
from hermes_bedrock_agent.retrieval.trace import HybridTrace
from hermes_bedrock_agent.knowledge_base.schemas import RetrievedChunk


class TestNormalizeQuery(unittest.TestCase):
    def test_strip_whitespace(self):
        assert normalize_query("  hello world  ") == "hello world"

    def test_collapse_spaces(self):
        assert normalize_query("a   b    c") == "a b c"

    def test_nfkc_fullwidth(self):
        # Full-width ABC → half-width ABC
        assert normalize_query("ＡＢＣ") == "ABC"

    def test_nfkc_fullwidth_numbers(self):
        assert normalize_query("１２３") == "123"

    def test_empty_string(self):
        assert normalize_query("") == ""

    def test_japanese_preserved(self):
        assert normalize_query("マッピング処理") == "マッピング処理"

    def test_mixed_whitespace(self):
        assert normalize_query("foo\t\nbar") == "foo bar"


class TestDetectIntent(unittest.TestCase):
    def test_mapping_intent(self):
        result = detect_intent("マッピングテーブルの変換ルール")
        assert result.label == "mapping"
        assert result.confidence > 0.3

    def test_flowchart_intent(self):
        result = detect_intent("処理フローのシーケンスを教えて")
        assert result.label == "flowchart"
        assert result.confidence > 0.3

    def test_api_intent(self):
        result = detect_intent("API endpoint の仕様")
        assert result.label == "api"
        assert result.confidence > 0.3

    def test_field_intent(self):
        result = detect_intent("フィールド定義とカラム")
        assert result.label == "field"
        assert result.confidence > 0.3

    def test_rule_intent(self):
        result = detect_intent("ビジネスルールの条件分岐")
        assert result.label == "rule"
        assert result.confidence > 0.3

    def test_overview_intent(self):
        result = detect_intent("システム概要の全体構成")
        assert result.label == "overview"
        assert result.confidence > 0.3

    def test_no_match_defaults_to_overview(self):
        result = detect_intent("xyz unknown random text")
        assert result.label == "overview"
        assert result.confidence == 0.1

    def test_chunk_type_hints(self):
        result = detect_intent("マッピング対応表")
        assert "mapping_table" in result.chunk_type_hints

    def test_returns_query_intent_type(self):
        result = detect_intent("test")
        assert isinstance(result, QueryIntent)


class TestRewriteQueries(unittest.TestCase):
    def test_basic_rewrite(self):
        intent = QueryIntent(label="mapping", confidence=0.5, chunk_type_hints=[])
        result = rewrite_queries("マッピングの確認", intent)
        assert isinstance(result, RewrittenQueries)
        assert result.original == "マッピングの確認"
        assert result.normalized == "マッピングの確認"
        assert len(result.business_query) > 0
        assert len(result.technical_query) > 0
        assert len(result.keyword_query) > 0

    def test_business_expansion_included(self):
        intent = QueryIntent(label="api", confidence=0.6, chunk_type_hints=[])
        result = rewrite_queries("APIの仕様", intent)
        assert "インターフェース" in result.business_query

    def test_technical_expansion_included(self):
        intent = QueryIntent(label="api", confidence=0.6, chunk_type_hints=[])
        result = rewrite_queries("APIの仕様", intent)
        assert "endpoint" in result.technical_query

    def test_keyword_extraction(self):
        intent = QueryIntent(label="overview", confidence=0.5, chunk_type_hints=[])
        result = rewrite_queries("仕訳基礎の概要を教えて", intent)
        # Should extract kanji compounds
        assert "仕訳基礎" in result.keyword_query or "概要" in result.keyword_query

    def test_empty_query_keyword_fallback(self):
        intent = QueryIntent(label="overview", confidence=0.1, chunk_type_hints=[])
        result = rewrite_queries("a", intent)
        # For single char, keyword_query should fall back to normalized
        assert result.keyword_query == "a"


class TestExtractSearchKeywords(unittest.TestCase):
    def test_kanji_extraction(self):
        keywords = _extract_search_keywords("仕訳基礎モジュールの処理")
        assert "仕訳基礎" in keywords or any("仕訳" in kw for kw in keywords)

    def test_katakana_extraction(self):
        keywords = _extract_search_keywords("マッピングテーブル")
        assert any("マッピング" in kw for kw in keywords)

    def test_latin_extraction(self):
        keywords = _extract_search_keywords("call the API_endpoint function")
        assert "API_endpoint" in keywords

    def test_empty_query(self):
        keywords = _extract_search_keywords("")
        assert keywords == []

    def test_deduplication(self):
        keywords = _extract_search_keywords("API API API endpoint endpoint")
        assert keywords.count("API") == 1
        assert keywords.count("endpoint") == 1


class TestKeywordSearch(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.keyword_retriever.lancedb")
    def test_basic_keyword_search(self, mock_lancedb):
        import pandas as pd

        # Mock LanceDB connection
        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["test_collection"]

        mock_table = MagicMock()
        mock_db.open_table.return_value = mock_table

        # Create mock DataFrame result
        df = pd.DataFrame({
            "id": ["chunk_001", "chunk_002", "chunk_003"],
            "text": [
                "仕訳基礎はAPのモジュールです",
                "対帳単は入力チェックモジュール",
                "unrelated english text only",
            ],
            "chunk_type": ["overview", "overview", "overview"],
            "sheet_index": [0, 1, 2],
            "sheet_name": ["sheet1", "sheet2", "sheet3"],
            "project_id": ["proj1", "proj1", "proj1"],
            "source_pdf_s3_path": ["", "", ""],
            "source_excel_s3_path": ["", "", ""],
        })

        mock_search = MagicMock()
        mock_table.search.return_value = mock_search
        mock_search.where.return_value = mock_search
        mock_search.limit.return_value = mock_search
        mock_search.to_pandas.return_value = df

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        cfg.lancedb_path = "/tmp/test"
        cfg.vector_collection = "test_collection"

        results = keyword_search(
            query="仕訳基礎モジュール",
            top_k=5,
            project_id="proj1",
            cfg=cfg,
            store_path="/tmp/test",
            collection="test_collection",
        )

        # Should find chunks with matching keywords
        assert len(results) >= 1
        # First result should have the best score (most keyword matches)
        assert results[0]["id"] == "chunk_001"

    @patch("hermes_bedrock_agent.retrieval.keyword_retriever.lancedb")
    def test_no_keywords_returns_empty(self, mock_lancedb):
        from hermes_bedrock_agent.config import Config
        cfg = Config()
        # Single char that doesn't match patterns
        results = keyword_search(query="x", top_k=5, cfg=cfg)
        assert results == []

    @patch("hermes_bedrock_agent.retrieval.keyword_retriever.lancedb")
    def test_collection_not_found(self, mock_lancedb):
        mock_db = MagicMock()
        mock_lancedb.connect.return_value = mock_db
        mock_db.table_names.return_value = ["other_collection"]

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        cfg.lancedb_path = "/tmp/test"
        cfg.vector_collection = "missing_collection"

        results = keyword_search(
            query="仕訳基礎",
            top_k=5,
            cfg=cfg,
            store_path="/tmp/test",
            collection="missing_collection",
        )
        assert results == []


class TestHybridRetrieve(unittest.TestCase):
    @patch("hermes_bedrock_agent.retrieval.reranker.load_rerank_config")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_basic_hybrid(self, mock_vector, mock_keyword, mock_rerank_cfg):
        from hermes_bedrock_agent.retrieval.reranker import RerankConfig
        mock_rerank_cfg.return_value = RerankConfig(enabled=False)
        mock_vector.return_value = [
            RetrievedChunk(
                chunk_id="v1", content="vector result 1", chunk_type="overview",
                sheet_index=0, sheet_name="s1", score=0.9,
            ),
            RetrievedChunk(
                chunk_id="v2", content="vector result 2", chunk_type="mapping_table",
                sheet_index=1, sheet_name="s2", score=0.7,
            ),
        ]
        mock_keyword.return_value = [
            {"id": "k1", "text": "keyword result", "chunk_type": "overview",
             "sheet_index": 2, "sheet_name": "s3", "_keyword_score": 0.8,
             "project_id": "p1", "source_pdf_s3_path": "", "source_excel_s3_path": "",
             "parsed_markdown_path": "", "document_id": "", "document_name": "",
             "document_type": "", "source_markdown_file": "", "evidence_path": "",
             "evidence_paths": "", "source_file": "", "source_type": "", "parser_type": ""},
            {"id": "v1", "text": "vector result 1", "chunk_type": "overview",
             "sheet_index": 0, "sheet_name": "s1", "_keyword_score": 0.6,
             "project_id": "p1", "source_pdf_s3_path": "", "source_excel_s3_path": "",
             "parsed_markdown_path": "", "document_id": "", "document_name": "",
             "document_type": "", "source_markdown_file": "", "evidence_path": "",
             "evidence_paths": "", "source_file": "", "source_type": "", "parser_type": ""},
        ]

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        result = hybrid_retrieve(query="テスト検索", top_k=5, cfg=cfg)

        assert isinstance(result, HybridResult)
        assert len(result.chunks) == 3  # v1, v2, k1 (v1 deduped)
        assert result.dedup_removed == 1  # v1 appeared in both
        # v1 should keep vector score (0.9) since it's higher than keyword*0.9
        v1_chunk = next(c for c in result.chunks if c.chunk_id == "v1")
        assert v1_chunk.score == 0.9

    @patch("hermes_bedrock_agent.retrieval.reranker.load_rerank_config")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_empty_results(self, mock_vector, mock_keyword, mock_rerank_cfg):
        from hermes_bedrock_agent.retrieval.reranker import RerankConfig
        mock_rerank_cfg.return_value = RerankConfig(enabled=False)
        mock_vector.return_value = []
        mock_keyword.return_value = []

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        result = hybrid_retrieve(query="nonexistent", top_k=5, cfg=cfg)

        assert isinstance(result, HybridResult)
        assert len(result.chunks) == 0
        assert result.merged_count == 0

    @patch("hermes_bedrock_agent.retrieval.reranker.load_rerank_config")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_trace_populated(self, mock_vector, mock_keyword, mock_rerank_cfg):
        from hermes_bedrock_agent.retrieval.reranker import RerankConfig
        mock_rerank_cfg.return_value = RerankConfig(enabled=False)
        mock_vector.return_value = [
            RetrievedChunk(
                chunk_id="v1", content="test", chunk_type="overview",
                sheet_index=0, sheet_name="s1", score=0.8,
            ),
        ]
        mock_keyword.return_value = []

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        trace = HybridTrace()
        result = hybrid_retrieve(query="APIの仕様確認", top_k=5, cfg=cfg, trace=trace)

        assert trace.normalized_query == "APIの仕様確認"
        assert trace.intent_label == "api"
        assert trace.intent_confidence > 0.0
        assert trace.vector_hits_count == 1
        assert trace.keyword_hits_count == 0
        assert len(trace.keyword_query) > 0

    @patch("hermes_bedrock_agent.retrieval.reranker.load_rerank_config")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_top_k_limit(self, mock_vector, mock_keyword, mock_rerank_cfg):
        from hermes_bedrock_agent.retrieval.reranker import RerankConfig
        mock_rerank_cfg.return_value = RerankConfig(enabled=False)
        mock_vector.return_value = [
            RetrievedChunk(
                chunk_id=f"v{i}", content=f"text {i}", chunk_type="overview",
                sheet_index=i, sheet_name=f"s{i}", score=0.9 - i * 0.1,
            )
            for i in range(10)
        ]
        mock_keyword.return_value = []

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        result = hybrid_retrieve(query="テスト", top_k=3, cfg=cfg)

        assert len(result.chunks) == 3
        # Should be the top-3 by score
        assert result.chunks[0].score >= result.chunks[1].score


class TestProvenanceMetadata(unittest.TestCase):
    def test_retrieved_chunk_backward_compatible(self):
        # Old-style construction without new fields should work
        chunk = RetrievedChunk(
            chunk_id="t",
            content="x",
            chunk_type="y",
            sheet_index=0,
            sheet_name="s",
            score=0.5,
            source_pdf_s3_path="",
            source_excel_s3_path="",
        )
        assert chunk.document_id == ""
        assert chunk.document_name == ""
        assert chunk.source_file == ""
        assert chunk.parser_type == ""

    def test_retrieved_chunk_with_provenance(self):
        chunk = RetrievedChunk(
            chunk_id="t",
            content="x",
            chunk_type="y",
            document_id="doc_001",
            document_name="test_doc",
            document_type="excel",
            source_markdown_file="/path/to/md",
            evidence_path="/path/to/evidence.pdf",
            evidence_paths='["/a.pdf", "/b.pdf"]',
            source_file="input.xlsx",
            source_type="excel",
            parser_type="vlm",
        )
        assert chunk.document_id == "doc_001"
        assert chunk.document_name == "test_doc"
        assert chunk.source_file == "input.xlsx"
        assert chunk.parser_type == "vlm"

    def test_row_to_chunk_preserves_provenance(self):
        row = {
            "id": "chunk_x",
            "text": "content here",
            "chunk_type": "mapping_table",
            "sheet_index": 3,
            "sheet_name": "Sheet3",
            "source_pdf_s3_path": "s3://bucket/file.pdf",
            "source_excel_s3_path": "s3://bucket/file.xlsx",
            "project_id": "proj1",
            "parsed_markdown_path": "/md/path",
            "document_id": "doc_99",
            "document_name": "仕訳基礎",
            "document_type": "excel",
            "source_markdown_file": "/src/md",
            "evidence_path": "/evidence/path",
            "evidence_paths": '["a.pdf"]',
            "source_file": "input.xlsx",
            "source_type": "excel",
            "parser_type": "vlm",
        }
        chunk = _row_to_chunk(row, 0.85, "proj1")
        assert chunk.chunk_id == "chunk_x"
        assert chunk.document_id == "doc_99"
        assert chunk.document_name == "仕訳基礎"
        assert chunk.evidence_paths == '["a.pdf"]'
        assert chunk.parser_type == "vlm"
        assert chunk.score == 0.85


class TestEdgeCases(unittest.TestCase):
    def test_empty_query_normalize(self):
        assert normalize_query("") == ""

    def test_single_char_query(self):
        result = normalize_query("a")
        assert result == "a"

    def test_very_long_query(self):
        long_q = "テスト " * 500
        result = normalize_query(long_q)
        assert "テスト" in result
        assert "  " not in result

    def test_detect_intent_empty(self):
        result = detect_intent("")
        assert result.label == "overview"
        assert result.confidence == 0.1

    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.hybrid_retriever.retrieve_chunks")
    def test_single_char_hybrid(self, mock_vector, mock_keyword):
        mock_vector.return_value = []
        mock_keyword.return_value = []

        from hermes_bedrock_agent.config import Config
        cfg = Config()
        result = hybrid_retrieve(query="x", top_k=5, cfg=cfg)
        assert isinstance(result, HybridResult)
        assert len(result.chunks) == 0


class TestHybridTrace(unittest.TestCase):
    def test_hybrid_trace_defaults(self):
        trace = HybridTrace()
        assert trace.normalized_query == ""
        assert trace.intent_label == ""
        assert trace.intent_confidence == 0.0
        assert trace.vector_hits_count == 0
        assert trace.keyword_hits_count == 0
        assert trace.merged_count == 0
        assert trace.dedup_removed == 0

    def test_retrieval_trace_includes_hybrid(self):
        from hermes_bedrock_agent.retrieval.trace import RetrievalTrace
        trace = RetrievalTrace(enabled=True)
        assert isinstance(trace.hybrid, HybridTrace)
        trace.hybrid.intent_label = "api"
        assert trace.hybrid.intent_label == "api"


class TestAnswerModeIntegration(unittest.TestCase):
    """Test that answer mode uses hybrid retrieval."""

    def test_rows_to_retrieved_chunks_preserves_provenance(self):
        """_rows_to_retrieved_chunks passes through all provenance fields."""
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import _rows_to_retrieved_chunks
        rows = [{
            "id": "test_chunk_001",
            "text": "Sample content",
            "chunk_type": "api_spec",
            "_distance": 0.5,
            "sheet_index": 2,
            "sheet_name": "Sheet2",
            "project_id": "test_project",
            "document_id": "doc123",
            "document_name": "TestDoc.xlsx",
            "document_type": "excel",
            "source_markdown_file": "/path/to/md",
            "evidence_path": "evidence/excel/doc/sheet_02/",
            "evidence_paths": '["path1.pdf", "path2.png"]',
            "source_file": "s3://bucket/file.xlsx",
            "source_type": "excel",
            "parser_type": "excel_vlm",
        }]
        chunks = _rows_to_retrieved_chunks(rows, "fallback_proj")
        assert chunks[0].document_id == "doc123"
        assert chunks[0].document_name == "TestDoc.xlsx"
        assert chunks[0].source_type == "excel"
        assert chunks[0].parser_type == "excel_vlm"
        assert chunks[0].project_id == "test_project"

    def test_keyword_boost_preserves_provenance(self):
        """_keyword_boost_chunks doesn't lose provenance metadata."""
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import _keyword_boost_chunks
        chunk = RetrievedChunk(
            chunk_id="c1", content="API endpoint for 発注データ登録",
            chunk_type="api_spec", sheet_index=1, sheet_name="S1", score=0.7,
            document_id="doc1", document_name="Spec.xlsx",
            source_type="excel", parser_type="excel_vlm",
        )
        result = _keyword_boost_chunks([chunk], "API 発注データ")
        assert result[0].document_id == "doc1"
        assert result[0].document_name == "Spec.xlsx"
        assert result[0].source_type == "excel"
        assert result[0].score >= 0.7

    def test_merge_chunks_preserves_provenance(self):
        """_merge_chunks doesn't lose provenance metadata."""
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import _merge_chunks
        guided = [RetrievedChunk(
            chunk_id="g1", content="guided", chunk_type="api_spec",
            sheet_index=0, sheet_name="S0", score=0.8,
            document_id="docG", source_type="excel", parser_type="excel_vlm",
        )]
        standard = [RetrievedChunk(
            chunk_id="s1", content="standard", chunk_type="flowchart",
            sheet_index=1, sheet_name="S1", score=0.7,
            document_id="docS", source_type="excel", parser_type="excel_vlm",
        )]
        result = _merge_chunks(guided, standard)
        g_chunk = next(c for c in result if c.chunk_id == "g1")
        s_chunk = next(c for c in result if c.chunk_id == "s1")
        assert g_chunk.document_id == "docG"
        assert s_chunk.document_id == "docS"

    @patch("hermes_bedrock_agent.retrieval.graph_guided_retrieval.explore_graph_for_query")
    @patch("hermes_bedrock_agent.retrieval.keyword_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.vector_retriever.retrieve_chunks")
    @patch("hermes_bedrock_agent.retrieval.graph_retriever.fetch_dual_graph_context")
    def test_retrieve_with_graph_guidance_uses_normalized_query(
        self, mock_graph_ctx, mock_vec, mock_kw, mock_explore
    ):
        """retrieve_with_graph_guidance normalizes the query before vector search."""
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import (
            GraphGuidanceHints,
            retrieve_with_graph_guidance,
        )
        from hermes_bedrock_agent.retrieval.trace import RetrievalTrace

        mock_explore.return_value = GraphGuidanceHints(quality="none")
        mock_vec.return_value = []
        mock_kw.return_value = []
        mock_graph_ctx.return_value = None

        trace = RetrievalTrace(enabled=True)
        retrieve_with_graph_guidance(
            "　ＡＰＩ呼出　", top_k=5, project_id="test", trace=trace,
        )

        assert mock_vec.called
        call_kwargs = mock_vec.call_args.kwargs
        query_used = call_kwargs.get("query", "")
        assert "API" in query_used
        assert trace.hybrid.normalized_query == "API呼出"
        assert trace.hybrid.intent_label == "api"

    @patch("hermes_bedrock_agent.retrieval.graph_guided_retrieval.explore_graph_for_query")
    @patch("hermes_bedrock_agent.retrieval.keyword_retriever.keyword_search")
    @patch("hermes_bedrock_agent.retrieval.vector_retriever.retrieve_chunks")
    @patch("hermes_bedrock_agent.retrieval.graph_retriever.fetch_dual_graph_context")
    def test_retrieve_with_graph_guidance_runs_keyword_search(
        self, mock_graph_ctx, mock_vec, mock_kw, mock_explore
    ):
        """retrieve_with_graph_guidance runs keyword search and merges results."""
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import (
            GraphGuidanceHints,
            retrieve_with_graph_guidance,
        )
        from hermes_bedrock_agent.retrieval.trace import RetrievalTrace

        mock_explore.return_value = GraphGuidanceHints(quality="none")
        mock_vec.return_value = [
            RetrievedChunk(
                chunk_id="v1", content="vector result", chunk_type="overview",
                sheet_index=0, sheet_name="s0", score=0.8,
            ),
        ]
        mock_kw.return_value = [
            {"id": "k1", "text": "keyword result", "chunk_type": "api_spec",
             "sheet_index": 1, "sheet_name": "s1", "_keyword_score": 0.7,
             "project_id": "test", "source_pdf_s3_path": "",
             "source_excel_s3_path": "", "parsed_markdown_path": "",
             "document_id": "kd1", "document_name": "kw_doc",
             "document_type": "excel", "source_markdown_file": "",
             "evidence_path": "", "evidence_paths": "",
             "source_file": "", "source_type": "", "parser_type": ""},
        ]
        mock_graph_ctx.return_value = None

        trace = RetrievalTrace(enabled=True)
        chunks, _, _ = retrieve_with_graph_guidance(
            "API test", top_k=10, project_id="test", trace=trace,
        )

        assert mock_kw.called
        assert trace.hybrid.keyword_hits_count == 1
        chunk_ids = [c.chunk_id for c in chunks]
        assert "v1" in chunk_ids
        assert "k1" in chunk_ids


if __name__ == "__main__":
    unittest.main()
