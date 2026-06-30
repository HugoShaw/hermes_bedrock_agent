"""Tests for qa_terminal.py — Phase 11A.1 GraphRAG QA Debug Console.

Covers:
1. CLI argument parsing (defaults, neptune-graph-id, no-color)
2. View mode formatting (simple/debug/full output structure)
3. Enrichment file not found → fallback (no crash)
4. Mock retriever + mock answer completes full cycle
5. Interactive commands (:quit, :help, :examples)
6. --mock-answer does NOT call any LLM
7. Default is read-only (no writes)
8. Language auto-detection
9. Neptune graph_id inference from endpoint
10. Score/URI display helpers
11. Rich renderer modes
12. --no-color fallback
13. Graph disabled when no graph_id
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# 1. CLI argument parsing
# ---------------------------------------------------------------------------

class TestCLIParsing:
    """Verify all default values and argument handling."""

    def test_defaults(self):
        from qa_terminal import parse_args

        args = parse_args([])
        assert args.run_id == "murata_live_v1"
        assert args.dataset == "murata"
        assert args.vector_store_backend == "lancedb"
        assert args.local_vector_collection == "murata_e2e_murata_live_v1"
        assert args.top_k_text == 10
        assert args.top_k_graph == 10
        assert args.fusion_top_k == 20
        assert args.graph_depth == 2
        assert args.max_edges_per_node == 30
        assert args.lang == "auto"
        assert args.label_mode == "mixed"
        assert args.view == "debug"
        assert args.mock_answer is False
        assert args.use_enrichment is False
        assert args.show_prompt is False
        assert args.no_color is False
        assert args.neptune_endpoint == "g-example01.ap-northeast-1.neptune-graph.amazonaws.com"

    def test_neptune_graph_id_cli(self):
        from qa_terminal import parse_args

        args = parse_args(["--neptune-graph-id", "g-test123"])
        assert args.neptune_graph_id == "g-test123"

    def test_neptune_graph_id_from_env(self, monkeypatch):
        from qa_terminal import parse_args

        monkeypatch.setenv("NEPTUNE_GRAPH_ID", "g-envtest")
        args = parse_args([])
        assert args.neptune_graph_id == "g-envtest"

    def test_neptune_graph_id_inferred_from_endpoint(self, monkeypatch):
        from qa_terminal import parse_args

        # Clear env so inference kicks in
        monkeypatch.delenv("NEPTUNE_GRAPH_ID", raising=False)
        args = parse_args([
            "--neptune-endpoint", "g-abc123.us-east-1.neptune-graph.amazonaws.com",
        ])
        assert args.neptune_graph_id == "g-abc123"

    def test_neptune_graph_id_default_inferred(self):
        """Default endpoint should yield g-example01."""
        from qa_terminal import parse_args

        # If env has NEPTUNE_GRAPH_ID, CLI infers from env first
        # Test just the extraction function directly
        from qa_terminal import extract_graph_id_from_endpoint

        assert extract_graph_id_from_endpoint(
            "g-example01.ap-northeast-1.neptune-graph.amazonaws.com"
        ) == "g-example01"

    def test_mock_answer_flag(self):
        from qa_terminal import parse_args

        args = parse_args(["--mock-answer"])
        assert args.mock_answer is True

    def test_no_color_flag(self):
        from qa_terminal import parse_args

        args = parse_args(["--no-color"])
        assert args.no_color is True

    def test_use_enrichment_flag(self):
        from qa_terminal import parse_args

        args = parse_args(["--use-enrichment"])
        assert args.use_enrichment is True

    def test_custom_top_k(self):
        from qa_terminal import parse_args

        args = parse_args(["--top-k-text", "20", "--top-k-graph", "15"])
        assert args.top_k_text == 20
        assert args.top_k_graph == 15

    def test_view_choices(self):
        from qa_terminal import parse_args

        for mode in ("simple", "debug", "full"):
            args = parse_args(["--view", mode])
            assert args.view == mode


# ---------------------------------------------------------------------------
# 2. Graph ID extraction from endpoint
# ---------------------------------------------------------------------------

class TestGraphIdExtraction:
    """Test extract_graph_id_from_endpoint helper."""

    def test_standard_endpoint(self):
        from qa_terminal import extract_graph_id_from_endpoint

        assert extract_graph_id_from_endpoint(
            "g-testnode01.ap-northeast-1.neptune-graph.amazonaws.com"
        ) == "g-testnode01"

    def test_different_region(self):
        from qa_terminal import extract_graph_id_from_endpoint

        assert extract_graph_id_from_endpoint(
            "g-xyz789abc.us-west-2.neptune-graph.amazonaws.com"
        ) == "g-xyz789abc"

    def test_empty_endpoint(self):
        from qa_terminal import extract_graph_id_from_endpoint

        assert extract_graph_id_from_endpoint("") == ""

    def test_non_neptune_endpoint(self):
        from qa_terminal import extract_graph_id_from_endpoint

        assert extract_graph_id_from_endpoint("example.com") == ""

    def test_missing_prefix(self):
        from qa_terminal import extract_graph_id_from_endpoint

        assert extract_graph_id_from_endpoint("ap-northeast-1.neptune.com") == ""


# ---------------------------------------------------------------------------
# 3. URI shortening and preview cleaning
# ---------------------------------------------------------------------------

class TestDisplayHelpers:
    """Test shorten_uri and clean_preview."""

    def test_shorten_uri_short_string(self):
        from qa_terminal import shorten_uri

        assert shorten_uri("s3://b/file.pdf") == "s3://b/file.pdf"

    def test_shorten_uri_long_path(self):
        from qa_terminal import shorten_uri

        uri = "s3://my-bucket/Murata/docs/subsystem/module/JournalBaseService.java"
        short = shorten_uri(uri, max_len=40)
        assert "JournalBaseService.java" in short
        assert "..." in short
        assert len(short) < len(uri)

    def test_shorten_uri_empty(self):
        from qa_terminal import shorten_uri

        assert shorten_uri("") == ""

    def test_clean_preview_basic(self):
        from qa_terminal import clean_preview

        text = "line1\n\nline2\n\n\nline3"
        cleaned = clean_preview(text)
        assert "\n" not in cleaned
        assert "line1" in cleaned

    def test_clean_preview_truncation(self):
        from qa_terminal import clean_preview

        text = "x" * 500
        cleaned = clean_preview(text, max_chars=100)
        assert len(cleaned) <= 101  # 100 + "…"
        assert cleaned.endswith("…")

    def test_clean_preview_empty(self):
        from qa_terminal import clean_preview

        assert clean_preview("") == ""


# ---------------------------------------------------------------------------
# 4. View mode formatting (plain text)
# ---------------------------------------------------------------------------

class TestFormatting:
    """Verify output format for each view mode."""

    @pytest.fixture
    def sample_result(self):
        return {
            "question": "テスト質問",
            "detected_language": "ja",
            "entity_mentions": [
                {"surface_form": "JOURNAL_BASE", "matched_entity": "journal_base",
                 "entity_type": "table", "confidence": 0.95, "source": "alias"}
            ],
            "graph_search_terms": ["journal_base", "journalbase"],
            "matched_entities": [
                {"matched_entity_name": "journal_base",
                 "entity_type": "table", "confidence": 0.95}
            ],
            "text_evidence": [],
            "graph_evidence": [],
            "graph_disabled": False,
            "fused_context": MagicMock(text_evidence=[], graph_evidence=[]),
            "context_str": "Some context here",
            "prompt": "SYSTEM:\nYou are...\nUSER:\nAnswer this...",
            "answer": "This is the answer.",
            "citations": [
                {"chunk_id": "chunk_001", "source_uri": "s3://bucket/doc.pdf",
                 "page": 1, "section_title": "Section A"}
            ],
            "timings": {
                "entity_extraction_ms": 5,
                "embedding_ms": 50,
                "vector_search_ms": 120,
                "graph_search_ms": 200,
                "fusion_ms": 2,
                "answer_ms": 50,
                "total_ms": 427,
            },
        }

    def test_simple_format_shows_answer(self, sample_result):
        from qa_terminal import format_result

        output = format_result(sample_result, "simple")
        assert "This is the answer." in output
        assert "chunk_001" in output
        # Should NOT show entity_mentions or timings sections
        assert "[C]" not in output
        assert "[K]" not in output

    def test_debug_format_shows_sections(self, sample_result):
        from qa_terminal import format_result

        output = format_result(sample_result, "debug")
        assert "[A] Question:" in output
        assert "[B] Detected language:" in output
        assert "[C] Extracted entity mentions" in output
        assert "[D] Graph search terms" in output
        assert "[I] Answer:" in output
        assert "[K] Latency:" in output

    def test_full_format_includes_context(self, sample_result):
        from qa_terminal import format_result

        output = format_result(sample_result, "full", show_prompt=True)
        assert "[FULL] Raw fused context:" in output
        assert "Some context here" in output
        assert "[FULL] Assembled prompt:" in output


# ---------------------------------------------------------------------------
# 5. Enrichment fallback
# ---------------------------------------------------------------------------

class TestEnrichmentFallback:
    """i18n enrichment file not found must not crash."""

    def test_missing_enrichment_file_no_crash(self, tmp_path):
        from qa_terminal import QASession, parse_args
        from rich.console import Console

        entities_path = tmp_path / "entities.jsonl"
        entities_path.write_text(json.dumps({
            "entity_id": "ent_001", "entity_type": "table",
            "canonical_name": "journal_base", "name": "JOURNAL_BASE",
            "aliases": ["仕訳基礎"],
        }) + "\n")

        args = parse_args([
            "--artifacts-dir", str(tmp_path),
            "--use-enrichment",
            "--i18n-entities-file", str(tmp_path / "nonexistent.jsonl"),
            "--mock-answer",
            "--local-vector-store-path", str(tmp_path / "lancedb"),
            "--local-vector-collection", "test",
            "--neptune-graph-id", "",
        ])
        # Clear graph_id to force disabled state
        args.neptune_graph_id = ""

        console = Console(quiet=True)
        session = QASession(args, console)

        with patch(
            "hermes_bedrock_agent.vector_store.lancedb_store.LanceDBStore.__init__",
            side_effect=Exception("no lancedb"),
        ):
            session.initialize()

        assert session._initialized is True
        assert session._entity_index is not None
        assert session._graph_enabled is False


# ---------------------------------------------------------------------------
# 6. Mock full cycle
# ---------------------------------------------------------------------------

class TestMockFullCycle:
    """Mock answer mode completes a full ask() cycle."""

    def test_mock_answer_returns_result(self, tmp_path):
        from qa_terminal import QASession, parse_args
        from rich.console import Console
        from hermes_bedrock_agent.retrieval.query_entity_extractor import (
            EntityIndex, QueryEntityExtractor,
        )
        from hermes_bedrock_agent.retrieval.context_builder import ContextBuilder

        entities_path = tmp_path / "entities.jsonl"
        entities_path.write_text(json.dumps({
            "entity_id": "ent_001", "entity_type": "table",
            "canonical_name": "journal_base", "name": "JOURNAL_BASE",
            "aliases": ["仕訳基礎"], "description": "Main journal table",
        }) + "\n")

        args = parse_args(["--artifacts-dir", str(tmp_path), "--mock-answer"])
        console = Console(quiet=True)
        session = QASession(args, console)

        entity_index = EntityIndex()
        entity_index.load_from_jsonl(str(entities_path))
        session._query_extractor = QueryEntityExtractor(entity_index)
        session._context_builder = ContextBuilder()
        session._initialized = True

        result = session.ask("仕訳基礎とは何ですか？")

        assert result["question"] == "仕訳基礎とは何ですか？"
        assert result["detected_language"] in ("ja", "zh")
        assert "[MOCK]" in result["answer"]
        assert "total_ms" in result["timings"]
        if result["entity_mentions"]:
            m = result["entity_mentions"][0]
            assert "surface_form" in m

    def test_mock_answer_no_llm_call(self, tmp_path):
        """--mock-answer must NOT call Bedrock."""
        from qa_terminal import QASession, parse_args
        from rich.console import Console
        from hermes_bedrock_agent.retrieval.query_entity_extractor import (
            EntityIndex, QueryEntityExtractor,
        )
        from hermes_bedrock_agent.retrieval.context_builder import ContextBuilder

        entities_path = tmp_path / "entities.jsonl"
        entities_path.write_text(json.dumps({
            "entity_id": "ent_001", "entity_type": "table",
            "canonical_name": "test", "name": "TEST",
        }) + "\n")

        args = parse_args(["--artifacts-dir", str(tmp_path), "--mock-answer"])
        console = Console(quiet=True)
        session = QASession(args, console)

        entity_index = EntityIndex()
        entity_index.load_from_jsonl(str(entities_path))
        session._query_extractor = QueryEntityExtractor(entity_index)
        session._context_builder = ContextBuilder()
        session._initialized = True

        with patch("hermes_bedrock_agent.clients.bedrock_client.get_bedrock_client") as mock_bedrock:
            result = session.ask("what is TEST?")
            mock_bedrock.assert_not_called()

        assert "[MOCK]" in result["answer"]


# ---------------------------------------------------------------------------
# 7. Interactive commands
# ---------------------------------------------------------------------------

class TestInteractiveCommands:
    """Verify command parsing logic."""

    def test_quit_command(self):
        from qa_terminal import run_interactive, QASession, parse_args
        from rich.console import Console

        args = parse_args(["--mock-answer", "--no-color"])
        console = Console(quiet=True)
        session = QASession(args, console)
        session._initialized = True

        with patch("builtins.input", side_effect=[":quit"]):
            run_interactive(session, args)

    def test_exit_command(self):
        from qa_terminal import run_interactive, QASession, parse_args
        from rich.console import Console

        args = parse_args(["--mock-answer", "--no-color"])
        console = Console(quiet=True)
        session = QASession(args, console)
        session._initialized = True

        with patch("builtins.input", side_effect=[":exit"]):
            run_interactive(session, args)

    def test_help_command(self, capsys):
        from qa_terminal import run_interactive, QASession, parse_args
        from rich.console import Console

        args = parse_args(["--mock-answer", "--no-color"])
        console = Console(force_terminal=False, no_color=True)
        session = QASession(args, console)
        session._initialized = True

        with patch("builtins.input", side_effect=[":help", ":quit"]):
            run_interactive(session, args)

        captured = capsys.readouterr()
        assert "Commands" in captured.out or ":quit" in captured.out

    def test_examples_command(self, capsys):
        from qa_terminal import run_interactive, QASession, parse_args
        from rich.console import Console

        args = parse_args(["--mock-answer", "--no-color"])
        console = Console(force_terminal=False, no_color=True)
        session = QASession(args, console)
        session._initialized = True

        with patch("builtins.input", side_effect=[":examples", ":quit"]):
            run_interactive(session, args)

        captured = capsys.readouterr()
        assert "仕訳基礎" in captured.out

    def test_mode_command(self, capsys):
        from qa_terminal import run_interactive, QASession, parse_args
        from rich.console import Console

        args = parse_args(["--mock-answer", "--no-color"])
        console = Console(force_terminal=False, no_color=True)
        session = QASession(args, console)
        session._initialized = True

        with patch("builtins.input", side_effect=[":mode simple", ":quit"]):
            run_interactive(session, args)

        captured = capsys.readouterr()
        assert "simple" in captured.out


# ---------------------------------------------------------------------------
# 8. Safety checks
# ---------------------------------------------------------------------------

class TestSafety:
    """Verify no writes and correct mock behavior."""

    def test_qa_session_has_no_write_methods(self):
        from qa_terminal import QASession

        write_patterns = ["write", "upsert", "insert", "delete", "update", "put", "create_table"]
        methods = [m for m in dir(QASession) if not m.startswith("_")]
        for method in methods:
            for pattern in write_patterns:
                assert pattern not in method.lower(), (
                    f"QASession has suspicious write-like method: {method}"
                )

    def test_mock_flag_prevents_llm(self):
        from qa_terminal import parse_args

        args = parse_args(["--mock-answer"])
        assert args.mock_answer is True

    def test_graph_disabled_no_crash(self, tmp_path):
        """If graph_id is empty, session still works without graph retrieval."""
        from qa_terminal import QASession, parse_args
        from rich.console import Console
        from hermes_bedrock_agent.retrieval.query_entity_extractor import (
            EntityIndex, QueryEntityExtractor,
        )
        from hermes_bedrock_agent.retrieval.context_builder import ContextBuilder

        entities_path = tmp_path / "entities.jsonl"
        entities_path.write_text(json.dumps({
            "entity_id": "ent_001", "entity_type": "table",
            "canonical_name": "test", "name": "TEST",
        }) + "\n")

        args = parse_args(["--artifacts-dir", str(tmp_path), "--mock-answer"])
        args.neptune_graph_id = ""  # Force no graph
        console = Console(quiet=True)
        session = QASession(args, console)

        entity_index = EntityIndex()
        entity_index.load_from_jsonl(str(entities_path))
        session._query_extractor = QueryEntityExtractor(entity_index)
        session._context_builder = ContextBuilder()
        session._graph_enabled = False
        session._initialized = True

        result = session.ask("test query")
        assert result["graph_disabled"] is True
        assert result["graph_evidence"] == []
        assert "[MOCK]" in result["answer"]


# ---------------------------------------------------------------------------
# 9. Language auto-detection
# ---------------------------------------------------------------------------

class TestLanguageDetection:
    """Verify auto language detection."""

    def test_japanese_hiragana(self):
        from qa_terminal import detect_language

        assert detect_language("仕訳基礎とは何ですか？") == "ja"

    def test_japanese_katakana(self):
        from qa_terminal import detect_language

        assert detect_language("テーブル構造") == "ja"

    def test_chinese(self):
        from qa_terminal import detect_language

        assert detect_language("付款申请相关表有哪些？") == "zh"

    def test_english(self):
        from qa_terminal import detect_language

        assert detect_language("What is JOURNAL_BASE?") == "en"

    def test_mixed_ja(self):
        from qa_terminal import detect_language

        assert detect_language("JOURNAL_BASEはどの機能から参照されていますか？") == "ja"


# ---------------------------------------------------------------------------
# 10. Rich renderer modes
# ---------------------------------------------------------------------------

class TestRichRenderer:
    """Test QATerminalRenderer output modes."""

    @pytest.fixture
    def console_and_renderer(self):
        from qa_terminal import QATerminalRenderer
        from rich.console import Console
        from io import StringIO

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        renderer = QATerminalRenderer(console, view="debug")
        return console, renderer, buf

    @pytest.fixture
    def sample_result(self):
        return {
            "question": "テスト",
            "detected_language": "ja",
            "entity_mentions": [
                {"surface_form": "TEST", "matched_entity": "test_entity",
                 "entity_type": "table", "confidence": 0.9, "source": "alias"}
            ],
            "graph_search_terms": ["test_entity"],
            "matched_entities": [{"matched_entity_name": "test_entity", "entity_type": "table", "confidence": 0.9}],
            "text_evidence": [],
            "graph_evidence": [],
            "graph_disabled": False,
            "fused_context": MagicMock(text_evidence=[], graph_evidence=[]),
            "context_str": "context",
            "prompt": "prompt text",
            "answer": "The answer is 42.",
            "citations": [],
            "timings": {"entity_extraction_ms": 5, "total_ms": 5},
        }

    def test_debug_mode_renders(self, console_and_renderer, sample_result):
        console, renderer, buf = console_and_renderer
        renderer.view = "debug"
        renderer.render(sample_result)
        output = buf.getvalue()
        assert "Question" in output
        assert "Entity Extraction" in output
        assert "answer" in output.lower() or "Answer" in output

    def test_simple_mode_renders(self, console_and_renderer, sample_result):
        console, renderer, buf = console_and_renderer
        renderer.view = "simple"
        renderer.render(sample_result)
        output = buf.getvalue()
        assert "Answer" in output
        # Should not show entity extraction table
        assert "Entity Extraction" not in output

    def test_full_mode_renders_context(self, console_and_renderer, sample_result):
        console, renderer, buf = console_and_renderer
        renderer.view = "full"
        renderer.show_prompt = True
        renderer.render(sample_result)
        output = buf.getvalue()
        assert "context" in output.lower()


# ---------------------------------------------------------------------------
# 11. Example questions constant
# ---------------------------------------------------------------------------

class TestExampleQuestions:
    """Verify example questions are correctly defined."""

    def test_examples_exist(self):
        from qa_terminal import EXAMPLE_QUESTIONS

        assert len(EXAMPLE_QUESTIONS) == 7

    def test_examples_are_strings(self):
        from qa_terminal import EXAMPLE_QUESTIONS

        for q in EXAMPLE_QUESTIONS:
            assert isinstance(q, str)
            assert len(q) > 5


# ---------------------------------------------------------------------------
# 12. No-color mode
# ---------------------------------------------------------------------------

class TestNoColor:
    """Verify --no-color disables rich formatting."""

    def test_no_color_uses_plain_format(self, tmp_path):
        from qa_terminal import QASession, parse_args
        from rich.console import Console
        from hermes_bedrock_agent.retrieval.query_entity_extractor import (
            EntityIndex, QueryEntityExtractor,
        )
        from hermes_bedrock_agent.retrieval.context_builder import ContextBuilder

        entities_path = tmp_path / "entities.jsonl"
        entities_path.write_text(json.dumps({
            "entity_id": "ent_001", "entity_type": "table",
            "canonical_name": "test", "name": "TEST",
        }) + "\n")

        args = parse_args(["--artifacts-dir", str(tmp_path), "--mock-answer", "--no-color"])
        console = Console(no_color=True, quiet=True)
        session = QASession(args, console)

        entity_index = EntityIndex()
        entity_index.load_from_jsonl(str(entities_path))
        session._query_extractor = QueryEntityExtractor(entity_index)
        session._context_builder = ContextBuilder()
        session._initialized = True

        # In no-color mode, run_interactive uses format_result (plain text)
        from qa_terminal import format_result
        result = session.ask("what is test?")
        output = format_result(result, "debug")
        assert "[A]" in output  # Plain text markers
        assert "\x1b" not in output  # No ANSI escape codes


# ---------------------------------------------------------------------------
# 14. Graph expansion trace display
# ---------------------------------------------------------------------------

class TestGraphExpansionTraceDisplay:
    """Verify _print_graph_expansion_trace renders without error."""

    def test_disabled_trace_prints_nothing(self, capsys):
        from hermes_bedrock_agent.retrieval.trace import RetrievalTrace
        from hermes_bedrock_agent.qa.terminal import _print_graph_expansion_trace

        trace = RetrievalTrace(enabled=True)
        # graph_expansion.enabled defaults to False → should print nothing
        _print_graph_expansion_trace(trace)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_enabled_trace_prints_sections(self, capsys):
        from hermes_bedrock_agent.retrieval.trace import RetrievalTrace, GraphExpansionTrace
        from hermes_bedrock_agent.qa.terminal import _print_graph_expansion_trace

        trace = RetrievalTrace(enabled=True)
        trace.graph_expansion = GraphExpansionTrace(
            enabled=True,
            neptune_available=True,
            entities_extracted=[
                {"text": "発注登録API", "type": "api_name", "confidence": 0.8},
                {"text": "債務奉行", "type": "system_name", "confidence": 0.7},
            ],
            relation_allowlist=["CALLS_API", "HAS_PARAMETER", "NEXT_STEP"],
            expansion_hops=2,
            graph_nodes_matched=3,
            graph_paths=["発注登録API-CALLS_API->PostOrder", "PostOrder-HAS_PARAMETER->item_code"],
            graph_candidates_count=5,
            graph_candidates_resolved=4,
            graph_candidates_new=2,
            graph_candidates_duplicate=2,
            join_methods_used={"project_workbook_sheet": 3, "project_workbook": 1},
            candidates_before_graph=10,
            candidates_after_graph=12,
            graph_candidates_survived_rerank=1,
            candidates=[
                {
                    "chunk_id": "excel_abc123_s03_c002",
                    "graph_node_name": "PostOrder",
                    "graph_node_type": "API",
                    "join_method": "project_workbook_sheet",
                    "join_confidence": 1.0,
                    "already_in_initial": False,
                    "document_name": "WB_Mapping",
                },
                {
                    "chunk_id": "excel_def456_s01_c001",
                    "graph_node_name": "item_code",
                    "graph_node_type": "Field",
                    "join_method": "project_workbook",
                    "join_confidence": 0.7,
                    "already_in_initial": True,
                    "document_name": "WB_Fields",
                },
            ],
        )

        _print_graph_expansion_trace(trace)
        captured = capsys.readouterr()
        output = captured.out

        # Verify key sections are present
        assert "Graph Expansion" in output
        assert "Neptune" in output
        assert "発注登録API" in output
        assert "CALLS_API" in output
        assert "Nodes matched" in output
        assert "3" in output
        assert "project_workbook_sheet" in output
        assert "Survived rerank" in output
        assert "PostOrder" in output
        assert "DUP" in output  # for already_in_initial

    def test_error_trace_prints_error(self, capsys):
        from hermes_bedrock_agent.retrieval.trace import RetrievalTrace, GraphExpansionTrace
        from hermes_bedrock_agent.qa.terminal import _print_graph_expansion_trace

        trace = RetrievalTrace(enabled=True)
        trace.graph_expansion = GraphExpansionTrace(
            enabled=True,
            neptune_available=False,
            error="Connection timed out",
        )

        _print_graph_expansion_trace(trace)
        captured = capsys.readouterr()
        assert "UNAVAILABLE" in captured.out
        assert "Connection timed out" in captured.out
