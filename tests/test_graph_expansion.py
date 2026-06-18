"""Tests for graph expansion: entity extraction, Neptune expansion, LanceDB join, trace."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import asdict

import pandas as pd

from hermes_bedrock_agent.retrieval.entity_extractor import extract_entities, ExtractedEntity
from hermes_bedrock_agent.retrieval.graph_expansion import (
    expand_graph,
    resolve_graph_candidates_to_chunks,
    GraphCandidate,
    GraphExpansionResult,
    INTENT_RELATION_ALLOWLISTS,
    MAX_GRAPH_CANDIDATES,
    INTENTS_ALLOWING_2HOP,
    _get_allowlist,
)
from hermes_bedrock_agent.retrieval.trace import GraphExpansionTrace, RetrievalTrace
from hermes_bedrock_agent.knowledge_base.schemas import RetrievedChunk


def _make_chunk(chunk_id="c001", content="テスト", chunk_type="overview",
                project_id="sample_20260519", workbook_name="", sheet_name="",
                document_name="", score=0.85):
    return RetrievedChunk(
        chunk_id=chunk_id,
        content=content,
        chunk_type=chunk_type,
        project_id=project_id,
        workbook_name=workbook_name,
        sheet_name=sheet_name,
        document_name=document_name,
        score=score,
    )


class TestEntityExtractionJapanese(unittest.TestCase):
    """Test entity extraction from Japanese queries."""

    def test_kanji_compound_extraction(self):
        entities = extract_entities("債務伝票の処理フロー", [], [])
        texts = [e.text for e in entities]
        self.assertIn("債務伝票", texts)
        self.assertIn("処理", texts)

    def test_katakana_extraction(self):
        entities = extract_entities("システムのマッピング定義", [], [])
        texts = [e.text for e in entities]
        self.assertIn("システム", texts)
        self.assertIn("マッピング", texts)

    def test_mapping_keyword_trigger(self):
        entities = extract_entities("マッピング定義の確認", [], [])
        mapping_entities = [e for e in entities if e.text == "マッピング"]
        self.assertTrue(len(mapping_entities) > 0)
        self.assertEqual(mapping_entities[0].entity_type, "mapping")

    def test_api_keyword_trigger(self):
        entities = extract_entities("API呼出順序の確認", [], [])
        api_entities = [e for e in entities if e.entity_type == "api"]
        self.assertTrue(len(api_entities) > 0)

    def test_process_keyword_trigger(self):
        entities = extract_entities("処理フローの確認", [], [])
        process_entities = [e for e in entities if e.entity_type == "process"]
        self.assertTrue(len(process_entities) > 0)

    def test_mixed_japanese_query(self):
        entities = extract_entities("債務奉行クラウドのAPI仕様", [], [])
        self.assertTrue(len(entities) > 0)
        types = {e.entity_type for e in entities}
        self.assertTrue(types.intersection({"api", "business_term", "system"}))


class TestEntityExtractionEnglish(unittest.TestCase):
    """Test entity extraction from English/code identifiers."""

    def test_upper_case_field(self):
        entities = extract_entities("COMPANY_CODE field mapping", [], [])
        upper_entities = [e for e in entities if e.text == "COMPANY_CODE"]
        self.assertTrue(len(upper_entities) > 0)
        self.assertEqual(upper_entities[0].entity_type, "field")

    def test_upper_case_id_code(self):
        entities = extract_entities("SAP system ID is SAP001", [], [])
        sap_entities = [e for e in entities if e.text == "SAP"]
        # SAP is 3 chars UPPER_CASE without underscore -> id_code
        self.assertTrue(len(sap_entities) > 0)

    def test_camel_case_extraction(self):
        entities = extract_entities("DataSpider sends PurchaseOrder", [], [])
        texts = [e.text for e in entities]
        self.assertIn("DataSpider", texts)
        self.assertIn("PurchaseOrder", texts)

    def test_alphanumeric_code(self):
        entities = extract_entities("N101の条件分岐を確認", [], [])
        code_entities = [e for e in entities if e.text == "N101"]
        self.assertTrue(len(code_entities) > 0)
        self.assertEqual(code_entities[0].entity_type, "id_code")
        self.assertEqual(code_entities[0].confidence, 0.9)

    def test_numeric_code(self):
        entities = extract_entities("301の処理を確認", [], [])
        code_entities = [e for e in entities if e.text == "301"]
        self.assertTrue(len(code_entities) > 0)
        self.assertEqual(code_entities[0].entity_type, "id_code")


class TestEntityExtractionFromChunks(unittest.TestCase):
    """Test entity extraction from chunk metadata."""

    def test_workbook_name_extraction(self):
        chunk = _make_chunk(
            workbook_name="MW_IFマッピング定義書_205_発注情報(登録・変更・取消)",
            document_name="MW_IFマッピング定義書_205_発注情報(登録・変更・取消)",
        )
        entities = extract_entities("テスト", [], [chunk])
        chunk_entities = [e for e in entities if e.source == "chunk"]
        self.assertTrue(len(chunk_entities) > 0)
        wb_entity = [e for e in chunk_entities if "MW_IF" in e.text or "マッピング" in e.text]
        self.assertTrue(len(wb_entity) > 0)
        self.assertEqual(wb_entity[0].confidence, 0.5)

    def test_sheet_name_extraction(self):
        chunk = _make_chunk(sheet_name="sheet_03")
        entities = extract_entities("テスト", [], [chunk])
        sheet_entities = [e for e in entities if e.text == "sheet_03"]
        self.assertTrue(len(sheet_entities) > 0)
        self.assertEqual(sheet_entities[0].source, "chunk")
        self.assertEqual(sheet_entities[0].confidence, 0.4)

    def test_deduplication(self):
        """Same text from query and chunk -> keep highest confidence."""
        chunk = _make_chunk(workbook_name="マッピング定義")
        entities = extract_entities("マッピング定義の確認", [], [chunk])
        mapping_entities = [e for e in entities if "マッピング" in e.text]
        # Should be deduplicated (same text appears from query with higher confidence)
        texts_lower = [e.text.lower() for e in entities]
        # No exact duplicates
        self.assertEqual(len(texts_lower), len(set(texts_lower)))


class TestEntityExtractionMisc(unittest.TestCase):
    """Test miscellaneous entity extraction behavior."""

    def test_max_entities_limit(self):
        # Long query with many potential entities
        query = "FIELD_A FIELD_B FIELD_C FIELD_D FIELD_E FIELD_F FIELD_G FIELD_H FIELD_I FIELD_J FIELD_K FIELD_L FIELD_M FIELD_N FIELD_O FIELD_P FIELD_Q FIELD_R FIELD_S FIELD_T FIELD_U"
        entities = extract_entities(query, [], [], max_entities=5)
        self.assertLessEqual(len(entities), 5)

    def test_rewritten_queries_contribute(self):
        entities = extract_entities(
            "テスト",
            ["DataSpider連携のAPI仕様", "マッピング処理"],
            [],
        )
        rewrite_entities = [e for e in entities if e.source == "rewrite"]
        self.assertTrue(len(rewrite_entities) > 0)

    def test_empty_query(self):
        entities = extract_entities("", [], [])
        self.assertEqual(entities, [])

    def test_confidence_ordering(self):
        """Higher confidence entities should come first."""
        entities = extract_entities("N101のCOMPANY_CODEとマッピング定義", [], [])
        if len(entities) >= 2:
            for i in range(len(entities) - 1):
                self.assertGreaterEqual(entities[i].confidence, entities[i + 1].confidence)


class TestIntentAllowlists(unittest.TestCase):
    """Test intent-aware relation allowlist selection."""

    def test_api_allowlist(self):
        allowlist = _get_allowlist("api")
        self.assertIn("CALLS_API", allowlist)
        self.assertIn("EXTRACTED_OBJECT", allowlist)

    def test_mapping_allowlist(self):
        allowlist = _get_allowlist("mapping")
        self.assertIn("EXTRACTED_OBJECT", allowlist)
        self.assertIn("HAS_SHEET", allowlist)

    def test_overview_allowlist(self):
        allowlist = _get_allowlist("overview")
        self.assertIn("HAS_SHEET", allowlist)
        self.assertIn("EXTRACTED_OBJECT", allowlist)
        self.assertNotIn("CALLS_API", allowlist)

    def test_unknown_intent_fallback(self):
        allowlist = _get_allowlist("unknown_intent")
        self.assertIn("EXTRACTED_OBJECT", allowlist)
        self.assertIn("HAS_SHEET", allowlist)

    def test_all_intent_types_covered(self):
        for intent in ["api", "mapping", "flowchart", "field", "rule", "overview"]:
            self.assertIn(intent, INTENT_RELATION_ALLOWLISTS)

    def test_2hop_intents(self):
        self.assertIn("mapping", INTENTS_ALLOWING_2HOP)
        self.assertIn("flowchart", INTENTS_ALLOWING_2HOP)
        self.assertIn("api", INTENTS_ALLOWING_2HOP)
        self.assertNotIn("field", INTENTS_ALLOWING_2HOP)
        self.assertNotIn("overview", INTENTS_ALLOWING_2HOP)


class TestGraphExpansion(unittest.TestCase):
    """Test graph expansion with mocked Neptune."""

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_neptune_unavailable(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = False
        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="テスト", entity_type="business_term", source="query", confidence=0.6)]
        result = expand_graph(entities, "api", "sample_20260519", set())

        self.assertFalse(result.neptune_available)
        self.assertEqual(result.candidates, [])

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_basic_expansion(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = True

        # First call: entity search
        # Second call: hop expansion
        mock_client.execute_query.side_effect = [
            {"results": [
                {"n": {"~id": "node1", "~labels": ["APIOperation"], "name": "発注登録API",
                       "project_id": "sample_20260519",
                       "workbook_name": "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)",
                       "sheet_name": "sheet_03", "description": "発注登録APIの仕様"}},
            ]},
            {"results": [
                {"n": {"~id": "node1", "~labels": ["APIOperation"], "name": "発注登録API"},
                 "rel": "EXTRACTED_OBJECT",
                 "m": {"~id": "node2", "~labels": ["Field"], "name": "伝票番号",
                       "project_id": "sample_20260519",
                       "workbook_name": "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)",
                       "sheet_name": "sheet_03", "description": "伝票番号フィールド"}},
            ]},
        ]
        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="発注登録", entity_type="api", source="query", confidence=0.8)]
        result = expand_graph(entities, "api", "sample_20260519", set())

        self.assertTrue(result.neptune_available)
        self.assertEqual(len(result.graph_nodes_matched), 1)
        self.assertTrue(len(result.candidates) > 0)
        self.assertEqual(result.candidates[0].graph_node_name, "伝票番号")

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_2hop_expansion_for_api_intent(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = True

        mock_client.execute_query.side_effect = [
            {"results": [
                {"n": {"~id": "node1", "~labels": ["APIOperation"], "name": "発注API",
                       "project_id": "sample_20260519", "workbook_name": "WB1", "sheet_name": "sheet_01"}},
            ]},
            # 1-hop results
            {"results": []},
            # 2-hop results
            {"results": [
                {"n": {"~id": "node1", "~labels": ["APIOperation"], "name": "発注API"},
                 "rel1": "CALLS_API", "m": {"~id": "node2", "~labels": ["System"], "name": "奉行"},
                 "rel2": "EXTRACTED_OBJECT", "p": {"~id": "node3", "~labels": ["Field"], "name": "得意先",
                                                    "project_id": "sample_20260519",
                                                    "workbook_name": "WB1", "sheet_name": "sheet_02"}},
            ]},
        ]
        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="発注", entity_type="api", source="query", confidence=0.8)]
        result = expand_graph(entities, "api", "sample_20260519", set())

        self.assertEqual(result.expansion_hops, 2)
        self.assertTrue(len(result.candidates) > 0)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_1hop_only_for_field_intent(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.execute_query.return_value = {"results": []}
        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="COMPANY", entity_type="field", source="query", confidence=0.8)]
        result = expand_graph(entities, "field", "sample_20260519", set())

        self.assertEqual(result.expansion_hops, 1)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_max_candidates_limit(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = True

        # Return many nodes
        many_results = [
            {"n": {"~id": f"node_{i}", "~labels": ["Field"], "name": f"Field_{i}",
                   "project_id": "sample_20260519", "workbook_name": "WB1", "sheet_name": "sheet_01"}}
            for i in range(20)
        ]
        many_hop_results = [
            {"n": {"~id": f"node_{i}", "~labels": ["Field"], "name": f"Field_{i}"},
             "rel": "EXTRACTED_OBJECT",
             "m": {"~id": f"target_{i}", "~labels": ["Field"], "name": f"Target_{i}",
                   "project_id": "sample_20260519", "workbook_name": "WB1", "sheet_name": "sheet_01"}}
            for i in range(20)
        ]

        mock_client.execute_query.side_effect = [
            {"results": many_results},
        ] + [{"results": many_hop_results}] * 20

        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="Field", entity_type="field", source="query", confidence=0.8)]
        result = expand_graph(entities, "field", "sample_20260519", set())

        self.assertLessEqual(len(result.candidates), MAX_GRAPH_CANDIDATES)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_neptune_query_error(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.execute_query.side_effect = Exception("Connection timeout")
        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="テスト", entity_type="business_term", source="query", confidence=0.6)]
        result = expand_graph(entities, "api", "sample_20260519", set())

        self.assertTrue(result.neptune_available)
        self.assertEqual(result.candidates, [])

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_relation_allowlist_used_in_result(self, mock_neptune_cls):
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.execute_query.return_value = {"results": []}
        mock_neptune_cls.return_value = mock_client

        entities = [ExtractedEntity(text="テスト", entity_type="business_term", source="query", confidence=0.6)]
        result = expand_graph(entities, "mapping", "sample_20260519", set())

        self.assertEqual(result.relation_allowlist_used, INTENT_RELATION_ALLOWLISTS["mapping"])


class TestGraphCandidateResolution(unittest.TestCase):
    """Test graph-to-LanceDB chunk resolution."""

    def _make_graph_result(self, candidates):
        return GraphExpansionResult(
            candidates=candidates,
            graph_nodes_matched=[],
            graph_paths=[],
            relation_allowlist_used=["EXTRACTED_OBJECT"],
            expansion_hops=1,
            neptune_available=True,
        )

    def _make_lancedb_df(self, rows):
        return pd.DataFrame(rows)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.lancedb")
    def test_project_workbook_sheet_join(self, mock_lancedb):
        mock_db = MagicMock()
        mock_table = MagicMock()
        df = self._make_lancedb_df([{
            "id": "excel_e0e652_s03_c002",
            "text": "発注登録API仕様の詳細",
            "project_id": "sample_20260519",
            "workbook_name": "MW_IFマッピング",
            "sheet_name": "sheet_03",
            "document_id": "doc001",
            "document_name": "MW_IFマッピング",
            "document_type": "excel",
            "source_markdown_file": "/path/to/file.md",
            "evidence_path": "/evidence/path",
            "evidence_paths": "[]",
            "source_file": "/source/file.xlsx",
            "source_type": "excel",
            "parser_type": "vlm",
            "chunk_type": "api_spec",
        }])
        mock_table.to_pandas.return_value = df
        mock_db.open_table.return_value = mock_table
        mock_lancedb.connect.return_value = mock_db

        candidate = GraphCandidate(
            content="発注登録API",
            score=0.6,
            graph_node_id="node1",
            graph_node_name="発注登録API",
            graph_node_type="APIOperation",
            project_id="sample_20260519",
            workbook_name="MW_IFマッピング",
            sheet_name="sheet_03",
        )
        graph_result = self._make_graph_result([candidate])

        resolved = resolve_graph_candidates_to_chunks(
            graph_result=graph_result,
            project_id="sample_20260519",
            initial_chunk_ids=set(),
        )

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].chunk_id, "excel_e0e652_s03_c002")
        self.assertEqual(resolved[0].join_method, "project_workbook_sheet")
        self.assertEqual(resolved[0].join_confidence, 1.0)
        self.assertEqual(resolved[0].document_name, "MW_IFマッピング")

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.lancedb")
    def test_project_workbook_join_fallback(self, mock_lancedb):
        mock_db = MagicMock()
        mock_table = MagicMock()
        df = self._make_lancedb_df([{
            "id": "excel_001",
            "text": "Content",
            "project_id": "sample_20260519",
            "workbook_name": "MW_IFマッピング",
            "sheet_name": "sheet_05",  # Different sheet
            "document_id": "doc001",
            "document_name": "MW_IFマッピング",
            "document_type": "excel",
            "source_markdown_file": "",
            "evidence_path": "",
            "evidence_paths": "",
            "source_file": "",
            "source_type": "excel",
            "parser_type": "vlm",
            "chunk_type": "overview",
        }])
        mock_table.to_pandas.return_value = df
        mock_db.open_table.return_value = mock_table
        mock_lancedb.connect.return_value = mock_db

        # Candidate has workbook but different sheet (sheet_03 vs sheet_05 in LanceDB)
        candidate = GraphCandidate(
            content="テスト",
            score=0.6,
            graph_node_id="node1",
            graph_node_name="テスト",
            graph_node_type="Field",
            project_id="sample_20260519",
            workbook_name="MW_IFマッピング",
            sheet_name="sheet_03",  # Not in LanceDB
        )
        graph_result = self._make_graph_result([candidate])

        resolved = resolve_graph_candidates_to_chunks(
            graph_result=graph_result,
            project_id="sample_20260519",
            initial_chunk_ids=set(),
        )

        # Should fall back to workbook-only join
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].join_method, "project_workbook")
        self.assertEqual(resolved[0].join_confidence, 0.7)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.lancedb")
    def test_join_failure_no_candidates(self, mock_lancedb):
        mock_db = MagicMock()
        mock_table = MagicMock()
        # Empty dataframe - no matching chunks
        df = self._make_lancedb_df([{
            "id": "other_chunk",
            "text": "Unrelated content",
            "project_id": "other_project",
            "workbook_name": "Other_WB",
            "sheet_name": "sheet_99",
            "document_id": "",
            "document_name": "",
            "document_type": "",
            "source_markdown_file": "",
            "evidence_path": "",
            "evidence_paths": "",
            "source_file": "",
            "source_type": "",
            "parser_type": "",
            "chunk_type": "",
        }])
        mock_table.to_pandas.return_value = df
        mock_db.open_table.return_value = mock_table
        mock_lancedb.connect.return_value = mock_db

        candidate = GraphCandidate(
            content="テスト",
            score=0.6,
            graph_node_id="node1",
            graph_node_name="テスト",
            graph_node_type="Field",
            project_id="sample_20260519",
            workbook_name="MW_IFマッピング",
            sheet_name="sheet_03",
        )
        graph_result = self._make_graph_result([candidate])

        resolved = resolve_graph_candidates_to_chunks(
            graph_result=graph_result,
            project_id="sample_20260519",
            initial_chunk_ids=set(),
        )

        self.assertEqual(len(resolved), 0)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.lancedb")
    def test_duplicate_detection(self, mock_lancedb):
        mock_db = MagicMock()
        mock_table = MagicMock()
        df = self._make_lancedb_df([{
            "id": "existing_chunk_001",
            "text": "Already retrieved content",
            "project_id": "sample_20260519",
            "workbook_name": "WB1",
            "sheet_name": "sheet_01",
            "document_id": "doc1",
            "document_name": "WB1",
            "document_type": "excel",
            "source_markdown_file": "",
            "evidence_path": "",
            "evidence_paths": "",
            "source_file": "",
            "source_type": "",
            "parser_type": "",
            "chunk_type": "",
        }])
        mock_table.to_pandas.return_value = df
        mock_db.open_table.return_value = mock_table
        mock_lancedb.connect.return_value = mock_db

        candidate = GraphCandidate(
            content="テスト",
            score=0.6,
            graph_node_id="node1",
            graph_node_name="テスト",
            graph_node_type="Field",
            project_id="sample_20260519",
            workbook_name="WB1",
            sheet_name="sheet_01",
        )
        graph_result = self._make_graph_result([candidate])

        # This chunk is already in the initial set
        resolved = resolve_graph_candidates_to_chunks(
            graph_result=graph_result,
            project_id="sample_20260519",
            initial_chunk_ids={"existing_chunk_001"},
        )

        self.assertEqual(len(resolved), 1)
        self.assertTrue(resolved[0].already_in_initial)

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.lancedb")
    def test_metadata_preservation(self, mock_lancedb):
        mock_db = MagicMock()
        mock_table = MagicMock()
        df = self._make_lancedb_df([{
            "id": "excel_full_meta",
            "text": "Full metadata content",
            "project_id": "sample_20260519",
            "workbook_name": "WB_Full",
            "sheet_name": "sheet_02",
            "document_id": "doc_full",
            "document_name": "WB_Full_Doc",
            "document_type": "excel",
            "source_markdown_file": "/parsed/WB_Full/sheet_02.md",
            "evidence_path": "/evidence/wb_full_s02.png",
            "evidence_paths": '["path1.png", "path2.png"]',
            "source_file": "/source/WB_Full.xlsx",
            "source_type": "excel",
            "parser_type": "vlm",
            "chunk_type": "mapping_table",
        }])
        mock_table.to_pandas.return_value = df
        mock_db.open_table.return_value = mock_table
        mock_lancedb.connect.return_value = mock_db

        candidate = GraphCandidate(
            content="Full metadata test",
            score=0.6,
            graph_node_id="node_full",
            graph_node_name="Full",
            graph_node_type="MappingDefinition",
            project_id="sample_20260519",
            workbook_name="WB_Full",
            sheet_name="sheet_02",
        )
        graph_result = self._make_graph_result([candidate])

        resolved = resolve_graph_candidates_to_chunks(
            graph_result=graph_result,
            project_id="sample_20260519",
            initial_chunk_ids=set(),
        )

        self.assertEqual(len(resolved), 1)
        r = resolved[0]
        self.assertEqual(r.document_id, "doc_full")
        self.assertEqual(r.document_name, "WB_Full_Doc")
        self.assertEqual(r.document_type, "excel")
        self.assertEqual(r.source_markdown_file, "/parsed/WB_Full/sheet_02.md")
        self.assertEqual(r.evidence_path, "/evidence/wb_full_s02.png")
        self.assertEqual(r.evidence_paths, ["path1.png", "path2.png"])
        self.assertEqual(r.source_type, "excel")
        self.assertEqual(r.parser_type, "vlm")
        self.assertEqual(r.chunk_type, "mapping_table")


class TestGraphExpansionTrace(unittest.TestCase):
    """Test trace data structure and population."""

    def test_trace_dataclass_exists(self):
        trace = GraphExpansionTrace()
        self.assertFalse(trace.enabled)
        self.assertFalse(trace.neptune_available)
        self.assertEqual(trace.entities_extracted, [])
        self.assertEqual(trace.graph_candidates_new, 0)

    def test_trace_in_retrieval_trace(self):
        trace = RetrievalTrace()
        self.assertIsInstance(trace.graph_expansion, GraphExpansionTrace)
        self.assertFalse(trace.graph_expansion.enabled)

    def test_trace_fields_populated(self):
        trace = GraphExpansionTrace(
            enabled=True,
            neptune_available=True,
            entities_extracted=[{"text": "テスト", "type": "business_term", "source": "query", "confidence": 0.6}],
            relation_allowlist=["EXTRACTED_OBJECT", "HAS_SHEET"],
            expansion_hops=1,
            graph_nodes_matched=3,
            graph_paths=["A->EXTRACTED_OBJECT->B"],
            graph_candidates_count=2,
            graph_candidates_resolved=2,
            graph_candidates_new=1,
            graph_candidates_duplicate=1,
            join_methods_used={"project_workbook_sheet": 1, "project_workbook": 1},
            candidates_before_graph=8,
            candidates_after_graph=9,
        )
        self.assertEqual(trace.graph_candidates_new, 1)
        self.assertEqual(trace.candidates_before_graph, 8)
        self.assertEqual(trace.candidates_after_graph, 9)

    def test_trace_error_field(self):
        trace = GraphExpansionTrace(error="Neptune timeout")
        self.assertEqual(trace.error, "Neptune timeout")


class TestIntegration(unittest.TestCase):
    """Integration tests for the full graph expansion pipeline."""

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.lancedb")
    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_full_pipeline(self, mock_neptune_cls, mock_lancedb):
        """Full pipeline: entities -> Neptune expansion -> LanceDB join."""
        # Setup Neptune mock
        mock_client = MagicMock()
        mock_client.is_configured = True

        # The query "発注登録APIの仕様を確認" extracts multiple entities.
        # Each entity triggers a search call, then matched nodes get hop expansion.
        # Use a function to handle dynamic call count.
        search_result = {"results": [
            {"n": {"~id": "node1", "~labels": ["APIOperation"], "name": "発注登録API",
                   "project_id": "sample_20260519",
                   "workbook_name": "MW_IFマッピング定義書",
                   "sheet_name": "sheet_03", "description": "発注登録APIの仕様"}},
        ]}
        hop_result = {"results": [
            {"n": {"~id": "node1", "~labels": ["APIOperation"], "name": "発注登録API"},
             "rel": "EXTRACTED_OBJECT",
             "m": {"~id": "node2", "~labels": ["Field"], "name": "伝票番号",
                   "project_id": "sample_20260519",
                   "workbook_name": "MW_IFマッピング定義書",
                   "sheet_name": "sheet_03", "description": "伝票番号フィールド"}},
        ]}
        empty_result = {"results": []}

        call_count = [0]
        def mock_execute(cypher, parameters=None):
            call_count[0] += 1
            # First few calls are entity searches (contain "CONTAINS")
            if "CONTAINS" in cypher:
                return search_result
            # Hop expansions
            if "r1" in cypher or "r2" in cypher:
                return empty_result
            return hop_result

        mock_client.execute_query.side_effect = mock_execute
        mock_neptune_cls.return_value = mock_client

        # Setup LanceDB mock
        mock_db = MagicMock()
        mock_table = MagicMock()
        df = pd.DataFrame([{
            "id": "excel_new_chunk",
            "text": "伝票番号の定義と仕様",
            "project_id": "sample_20260519",
            "workbook_name": "MW_IFマッピング定義書",
            "sheet_name": "sheet_03",
            "document_id": "doc001",
            "document_name": "MW_IFマッピング定義書",
            "document_type": "excel",
            "source_markdown_file": "/path/sheet_03.md",
            "evidence_path": "/evidence/s03.png",
            "evidence_paths": "",
            "source_file": "/src/file.xlsx",
            "source_type": "excel",
            "parser_type": "vlm",
            "chunk_type": "api_spec",
        }])
        mock_table.to_pandas.return_value = df
        mock_db.open_table.return_value = mock_table
        mock_lancedb.connect.return_value = mock_db

        # Run entity extraction
        entities = extract_entities("発注登録APIの仕様を確認", [], [])
        self.assertTrue(len(entities) > 0)

        # Run graph expansion
        result = expand_graph(entities, "api", "sample_20260519", {"existing_chunk_001"})
        self.assertTrue(result.neptune_available)
        self.assertTrue(len(result.candidates) > 0)

        # Resolve to chunks
        resolved = resolve_graph_candidates_to_chunks(
            graph_result=result,
            project_id="sample_20260519",
            initial_chunk_ids={"existing_chunk_001"},
        )
        self.assertTrue(len(resolved) > 0)
        self.assertFalse(resolved[0].already_in_initial)
        self.assertEqual(resolved[0].chunk_id, "excel_new_chunk")

    @patch("hermes_bedrock_agent.retrieval.graph_expansion.NeptuneClient")
    def test_neptune_unavailable_preserves_existing(self, mock_neptune_cls):
        """When Neptune is unavailable, expansion returns empty with no error."""
        mock_client = MagicMock()
        mock_client.is_configured = False
        mock_neptune_cls.return_value = mock_client

        entities = extract_entities("テストクエリ", [], [])
        result = expand_graph(entities, "api", "sample_20260519", {"chunk_001"})

        self.assertFalse(result.neptune_available)
        self.assertEqual(result.candidates, [])
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
