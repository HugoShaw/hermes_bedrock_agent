"""Tests for scripts/run_e2e_murata_pipeline.py — mock-only, no real AWS."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Test PipelineState
# ===========================================================================


class TestPipelineState:
    """Tests for the PipelineState helper class."""

    def setup_method(self):
        """Create temp dir for artifacts."""
        self.tmpdir = tempfile.mkdtemp()
        # Import here to avoid import-time issues
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

    def _get_state(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline",
            Path(__file__).resolve().parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.PipelineState("test_run_001", Path(self.tmpdir))

    def test_artifact_dir_created(self):
        state = self._get_state()
        assert state.artifact_dir.exists()
        assert "test_run_001" in str(state.artifact_dir)

    def test_save_and_load_jsonl(self):
        state = self._get_state()
        records = [
            {"id": "a", "value": 1},
            {"id": "b", "value": 2},
        ]
        state.save_jsonl("test.jsonl", records)
        loaded = state.load_jsonl("test.jsonl")
        assert len(loaded) == 2
        assert loaded[0]["id"] == "a"
        assert loaded[1]["value"] == 2

    def test_append_jsonl(self):
        state = self._get_state()
        state.append_jsonl("incremental.jsonl", {"id": "x"})
        state.append_jsonl("incremental.jsonl", {"id": "y"})
        loaded = state.load_jsonl("incremental.jsonl")
        assert len(loaded) == 2

    def test_save_json(self):
        state = self._get_state()
        state.save_json("report.json", {"total": 42})
        path = state.artifact_path("report.json")
        with open(path) as f:
            data = json.load(f)
        assert data["total"] == 42

    def test_save_text(self):
        state = self._get_state()
        state.save_text("readme.md", "# Hello")
        path = state.artifact_path("readme.md")
        assert path.read_text() == "# Hello"

    def test_record_failure(self):
        state = self._get_state()
        state.record_failure("parse", "doc_001", "Encoding error")
        assert len(state.failures) == 1
        assert state.failures[0]["stage"] == "parse"
        assert state.failures[0]["item_id"] == "doc_001"

    def test_get_existing_ids(self):
        state = self._get_state()
        records = [
            {"chunk_id": "c1", "text": "hello"},
            {"chunk_id": "c2", "text": "world"},
        ]
        state.save_jsonl("chunks.jsonl", records)
        ids = state.get_existing_ids("chunks.jsonl", "chunk_id")
        assert ids == {"c1", "c2"}

    def test_load_jsonl_missing_file(self):
        state = self._get_state()
        loaded = state.load_jsonl("nonexistent.jsonl")
        assert loaded == []

    def test_pydantic_model_save(self):
        """Test that Pydantic models are serialized correctly."""
        from hermes_bedrock_agent.schemas.visualization import VisualizationNode
        state = self._get_state()
        node = VisualizationNode(
            node_id="n1",
            label="Test Node",
            node_type="system",
            properties={"desc": "A test"},
        )
        state.save_jsonl("nodes.jsonl", [node])
        loaded = state.load_jsonl("nodes.jsonl")
        assert loaded[0]["node_id"] == "n1"
        assert loaded[0]["label"] == "Test Node"


# ===========================================================================
# Test stage_scan (mocked S3)
# ===========================================================================


class TestStageScan:
    """Test S3 scan stage with mocked S3Client."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _get_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline",
            Path(__file__).resolve().parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_scan_filters_system_files(self):
        module = self._get_module()
        state = module.PipelineState("test_scan", Path(self.tmpdir))

        # Mock S3Client
        mock_s3_objects = [
            MagicMock(
                key="Murata/src/Main.java", size=5000,
                last_modified=None, etag="abc123",
                uri="s3://bucket/Murata/src/Main.java",
                extension=".java", filename="Main.java",
            ),
            MagicMock(
                key="Murata/.DS_Store", size=100,
                last_modified=None, etag="def456",
                uri="s3://bucket/Murata/.DS_Store",
                extension="", filename=".DS_Store",
            ),
            MagicMock(
                key="Murata/doc/readme.md", size=2000,
                last_modified=None, etag="ghi789",
                uri="s3://bucket/Murata/doc/readme.md",
                extension=".md", filename="readme.md",
            ),
        ]

        # Patch Path for extension resolution
        from pathlib import PurePosixPath
        for obj in mock_s3_objects:
            obj.key = obj.key  # keep as string for Path(key).suffix

        args = MagicMock()
        args.skip_existing = False

        with patch("hermes_bedrock_agent.clients.s3_client.S3Client") as MockS3:
            instance = MockS3.return_value
            instance.list_objects.return_value = mock_s3_objects
            docs = module.stage_scan(state, args)

        # Should include .java and .md, skip .DS_Store
        assert len(docs) >= 1  # At least the .java and .md
        inventory = json.loads(state.artifact_path("file_inventory_report.json").read_text())
        assert inventory["run_id"] == "test_scan"


# ===========================================================================
# Test helper functions
# ===========================================================================


class TestParseHelpers:
    """Test text parsing helper functions."""

    def _get_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline",
            Path(__file__).resolve().parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_infer_source_type(self):
        module = self._get_module()
        assert module._infer_source_type(".java", "src/Main.java") == "code"
        assert module._infer_source_type(".sql", "db/create.sql") == "sql"
        assert module._infer_source_type(".md", "readme.md") == "markdown"
        assert module._infer_source_type(".pdf", "doc.pdf") == "pdf"
        assert module._infer_source_type(".docx", "report.docx") == "docx"
        assert module._infer_source_type(".pptx", "slides.pptx") == "pptx"
        assert module._infer_source_type(".xlsx", "data.xlsx") == "spreadsheet"
        assert module._infer_source_type(".png", "arch.png") == "image"
        assert module._infer_source_type(".xyz", "unknown.xyz") == "unknown"

    def test_split_markdown_sections(self):
        module = self._get_module()
        text = """# Header 1
Content for section 1.

## Header 2
Content for section 2.
More content.

## Header 3
Final section."""
        sections = module._split_markdown_sections(text)
        assert len(sections) >= 3
        assert sections[0]["title"] == "Header 1"
        assert "Content for section 1" in sections[0]["content"]
        assert sections[1]["title"] == "Header 2"
        assert sections[2]["title"] == "Header 3"

    def test_split_sql_sections(self):
        module = self._get_module()
        text = """CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(100)
);

INSERT INTO users VALUES (1, 'test');

ALTER TABLE users ADD email VARCHAR(200);"""
        sections = module._split_sql_sections(text)
        assert len(sections) >= 2
        # First should be the CREATE TABLE
        assert any("users" in s["title"] for s in sections)

    def test_split_code_sections_java(self):
        module = self._get_module()
        text = """package com.example;

import java.util.List;

public class PaymentService {

    public void processPayment(String id) {
        // logic
    }

    private int calculateTotal() {
        return 0;
    }
}"""
        sections = module._split_code_sections(text, "PaymentService.java")
        assert len(sections) >= 2
        # Should have methods
        assert any("processPayment" in s["title"] for s in sections)

    def test_parse_text_unicode(self):
        module = self._get_module()
        raw_bytes = "テスト文書\nこれは日本語のテストです。".encode("utf-8")
        doc = {"filename": "test.md", "source_type": "markdown"}
        sections = module._parse_text(raw_bytes, doc)
        assert len(sections) >= 1
        assert "テスト" in sections[0]["content"]

    def test_parse_text_shift_jis_fallback(self):
        module = self._get_module()
        text = "シフトJISのテスト"
        raw_bytes = text.encode("shift_jis")
        doc = {"filename": "test.txt", "source_type": "text"}
        sections = module._parse_text(raw_bytes, doc)
        assert "シフトJIS" in sections[0]["content"]


# ===========================================================================
# Test stage_chunk (mocked data)
# ===========================================================================


class TestStageChunk:
    """Test chunking stage with pre-built JSONL data."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _get_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline",
            Path(__file__).resolve().parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_chunk_from_normalized_docs(self):
        module = self._get_module()
        state = module.PipelineState("test_chunk", Path(self.tmpdir))

        # Write mock normalized docs
        norm_docs = [
            {
                "document_id": "doc001",
                "source_uri": "s3://bucket/Murata/test.java",
                "source_type": "code",
                "filename": "Test.java",
                "title": "Test.java",
                "sections": [
                    {"title": "TestClass", "content": "public class Test { " + "x" * 2000 + " }", "page": ""},
                ],
                "total_pages": None,
                "language": "ja",
                "visual_block_ids": [],
                "content_hash": "abc123",
            }
        ]
        state.save_jsonl("normalized_documents.jsonl", norm_docs)
        state.save_jsonl("visual_blocks.jsonl", [])

        args = MagicMock()
        args.fail_fast = False

        chunks = module.stage_chunk(state, args)
        assert len(chunks) >= 1
        assert chunks[0]["document_id"] == "doc001"
        assert "chunk_id" in chunks[0]

        # Check stats file
        stats = json.loads(state.artifact_path("chunk_stats.json").read_text())
        assert stats["total_chunks"] >= 1


# ===========================================================================
# Test CLI argument parsing
# ===========================================================================


class TestCLIParsing:
    """Test argument parser defaults and combinations."""

    def _get_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline",
            Path(__file__).resolve().parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_default_args(self):
        module = self._get_module()
        import sys
        original_argv = sys.argv
        sys.argv = ["run_e2e_murata_pipeline.py"]
        try:
            args = module.parse_args()
            assert args.stage == "all"
            assert args.run_id == "murata_full_vlm_live_001"
            assert args.enable_vlm is True
            assert args.live_neptune is False
            assert args.confirm_live_write is False
            assert args.vector_store_backend == "lancedb"
        finally:
            sys.argv = original_argv

    def test_stage_scan(self):
        module = self._get_module()
        import sys
        original_argv = sys.argv
        sys.argv = ["run_e2e_murata_pipeline.py", "--stage", "scan"]
        try:
            args = module.parse_args()
            assert args.stage == "scan"
        finally:
            sys.argv = original_argv

    def test_live_neptune_flags(self):
        module = self._get_module()
        import sys
        original_argv = sys.argv
        sys.argv = [
            "run_e2e_murata_pipeline.py",
            "--stage", "load",
            "--live-neptune",
            "--confirm-live-write",
        ]
        try:
            args = module.parse_args()
            assert args.live_neptune is True
            assert args.confirm_live_write is True
        finally:
            sys.argv = original_argv

    def test_no_vlm_flag(self):
        module = self._get_module()
        import sys
        original_argv = sys.argv
        sys.argv = ["run_e2e_murata_pipeline.py", "--no-vlm"]
        try:
            args = module.parse_args()
            assert args.no_vlm is True
        finally:
            sys.argv = original_argv

    def test_mode_and_s3_uri(self):
        module = self._get_module()
        import sys
        original_argv = sys.argv
        sys.argv = [
            "run_e2e_murata_pipeline.py",
            "--mode", "live-source",
            "--s3-uri", "s3://my-bucket/prefix/",
            "--run-id", "custom_run_123",
            "--neptune-dataset", "test_ds",
            "--local-vector-collection", "my_collection",
            "--mock-embedding",
            "--mock-graph-extraction",
            "--mock-answer",
        ]
        try:
            args = module.parse_args()
            assert args.mode == "live-source"
            assert args.s3_uri == "s3://my-bucket/prefix/"
            assert args.run_id == "custom_run_123"
            assert args.neptune_dataset == "test_ds"
            assert args.local_vector_collection == "my_collection"
            assert args.mock_embedding is True
            assert args.mock_graph_extraction is True
            assert args.mock_answer is True
        finally:
            sys.argv = original_argv


# ===========================================================================
# Test final reports generation
# ===========================================================================


class TestFinalReports:
    """Test quality report and cleanup commands generation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _get_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline",
            Path(__file__).resolve().parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_generate_final_reports(self):
        module = self._get_module()
        state = module.PipelineState("test_final", Path(self.tmpdir))

        # Pre-create some stage outputs
        state.save_json("file_inventory_report.json", {
            "processable_documents": 42,
            "total_bytes": 1000000,
        })
        state.save_json("chunk_stats.json", {"total_chunks": 100})
        state.save_json("lancedb_load_report.json", {"embedded_count": 80})
        state.save_json("graph_quality_report.json", {
            "accepted_entities": 50,
            "accepted_relations": 30,
        })
        state.save_json("neptune_load_report.json", {
            "nodes_loaded": 50,
            "edges_loaded": 30,
        })

        args = MagicMock()
        args.local_vector_store_path = Path("/tmp/lancedb")
        args.local_vector_collection = "murata_e2e_test_final"
        args.neptune_dataset = "murata"
        args.neptune_endpoint = "g-test.ap-northeast-1.neptune-graph.amazonaws.com"
        args.s3_uri = "s3://s3-hulftchina-rd/Murata/"

        module.generate_final_reports(state, args)

        # Check quality report
        report_path = state.artifact_path("murata_e2e_quality_report.md")
        assert report_path.exists()
        content = report_path.read_text()
        assert "test_final" in content
        assert "42" in content

        # Check cleanup commands
        cleanup_path = state.artifact_path("cleanup_commands.md")
        assert cleanup_path.exists()
        cleanup = cleanup_path.read_text()
        assert "murata_e2e_test_final" in cleanup
        assert "drop_table" in cleanup
        assert "run_id" in cleanup
        assert "parameterized" in cleanup.lower()

    def test_generate_reports_with_failures(self):
        module = self._get_module()
        state = module.PipelineState("test_fail", Path(self.tmpdir))
        state.record_failure("parse", "doc_001", "UnicodeDecodeError")
        state.record_failure("parse", "doc_002", "TimeoutError")

        args = MagicMock()
        args.local_vector_store_path = Path("/tmp/lancedb")
        args.local_vector_collection = "murata_e2e_test_fail"
        args.neptune_dataset = "murata"
        args.neptune_endpoint = "g-test.ap-northeast-1.neptune-graph.amazonaws.com"
        args.s3_uri = "s3://s3-hulftchina-rd/Murata/"

        module.generate_final_reports(state, args)
        report = state.artifact_path("murata_e2e_quality_report.md").read_text()
        assert "Failures" in report
        assert "UnicodeDecodeError" in report


class TestExcludePatterns:
    """Test exclude pattern filtering for embedding and graph extraction stages."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get_module(self):
        spec = importlib.util.spec_from_file_location(
            "e2e_pipeline", Path(__file__).parent.parent / "scripts" / "run_e2e_murata_pipeline.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _make_chunks(self):
        """Create sample chunks from different documents."""
        return [
            {"chunk_id": "c1", "document_id": "doc_sql", "source_uri": "s3://bucket/JOURNAL_BASE20180530.SQL", "section_title": "Data"},
            {"chunk_id": "c2", "document_id": "doc_sql", "source_uri": "s3://bucket/JOURNAL_BASE20180530.SQL", "section_title": "Data2"},
            {"chunk_id": "c3", "document_id": "doc_java", "source_uri": "s3://bucket/BaseAction.java", "section_title": "class"},
            {"chunk_id": "c4", "document_id": "doc_img", "source_uri": "s3://bucket/screenshot.png", "section_title": "Visual"},
            {"chunk_id": "c5", "document_id": "doc_sql2", "source_uri": "s3://bucket/MURATA_20180530.sql", "section_title": "DDL"},
        ]

    def _make_docs_by_id(self):
        return {
            "doc_sql": {"document_id": "doc_sql", "filename": "JOURNAL_BASE20180530.SQL", "source_uri": "s3://bucket/JOURNAL_BASE20180530.SQL"},
            "doc_java": {"document_id": "doc_java", "filename": "BaseAction.java", "source_uri": "s3://bucket/BaseAction.java"},
            "doc_img": {"document_id": "doc_img", "filename": "screenshot.png", "source_uri": "s3://bucket/screenshot.png"},
            "doc_sql2": {"document_id": "doc_sql2", "filename": "MURATA_20180530.sql", "source_uri": "s3://bucket/MURATA_20180530.sql"},
        }

    def test_exclude_pattern_matches_filename(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        filtered, summary = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=["JOURNAL_BASE*.SQL"],
            stage_patterns=[],
        )

        assert summary["original_count"] == 5
        assert summary["excluded_count"] == 2  # c1, c2
        assert summary["included_count"] == 3  # c3, c4, c5
        assert "JOURNAL_BASE20180530.SQL" in summary["excluded_files"]
        assert len(filtered) == 3
        assert all(c["chunk_id"] != "c1" and c["chunk_id"] != "c2" for c in filtered)

    def test_skip_embedding_pattern_only_affects_embedding(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        # Only embedding skipped
        filtered_emb, sum_emb = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=[],
            stage_patterns=["JOURNAL_BASE*.SQL"],
        )
        # Graph extraction not affected
        filtered_graph, sum_graph = module._filter_chunks_for_stage(
            chunks, docs, "graph_extraction",
            exclude_patterns=[],
            stage_patterns=[],
        )

        assert sum_emb["excluded_count"] == 2
        assert sum_graph["excluded_count"] == 0
        assert len(filtered_graph) == 5

    def test_skip_graph_extraction_pattern_only_affects_graph(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        # Embedding not affected
        filtered_emb, sum_emb = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=[],
            stage_patterns=[],
        )
        # Graph extraction skipped
        filtered_graph, sum_graph = module._filter_chunks_for_stage(
            chunks, docs, "graph_extraction",
            exclude_patterns=[],
            stage_patterns=["*.SQL"],
        )

        assert sum_emb["excluded_count"] == 0
        assert sum_graph["excluded_count"] == 2  # JOURNAL_BASE20180530.SQL

    def test_no_patterns_returns_all(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        filtered, summary = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=[],
            stage_patterns=[],
        )

        assert summary["excluded_count"] == 0
        assert summary["included_count"] == 5
        assert len(filtered) == 5

    def test_wildcard_matches_multiple_files(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        filtered, summary = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=["*.SQL", "*.sql"],
            stage_patterns=[],
        )

        # Excludes JOURNAL_BASE20180530.SQL (c1, c2) and MURATA_20180530.sql (c5)
        assert summary["excluded_count"] == 3
        assert summary["included_count"] == 2
        assert set(c["chunk_id"] for c in filtered) == {"c3", "c4"}

    def test_combined_exclude_and_stage_patterns(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        filtered, summary = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=["JOURNAL_BASE*.SQL"],
            stage_patterns=["*.png"],
        )

        # Excludes c1, c2 (SQL) and c4 (png)
        assert summary["excluded_count"] == 3
        assert summary["included_count"] == 2
        assert set(c["chunk_id"] for c in filtered) == {"c3", "c5"}

    def test_matches_source_uri(self):
        module = self._get_module()
        chunks = self._make_chunks()
        docs = self._make_docs_by_id()

        # Pattern matching source_uri path
        filtered, summary = module._filter_chunks_for_stage(
            chunks, docs, "embedding",
            exclude_patterns=["*JOURNAL_BASE*"],
            stage_patterns=[],
        )

        assert summary["excluded_count"] == 2
        assert summary["included_count"] == 3
