"""Unit tests for the parsing pipeline: orchestrator, registry, strategy, output_writer.

Uses mocked dependencies only — no live S3, Bedrock, LanceDB, Neptune, or real parsing.
Covers: routing, parser selection, metadata/frontmatter, manifest/output, failure handling.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

from hermes_bedrock_agent.models.document import (
    DocumentRole,
    FileState,
    ParsedDocument,
    ProjectFile,
    ProjectManifest,
    SourceType,
)
from hermes_bedrock_agent.parsing.strategy import (
    SKIP_TYPES,
    VLM_TYPES,
    select_parser,
    run_strategy_selection,
)
from hermes_bedrock_agent.parsing.registry import ParserRegistry, create_default_registry
from hermes_bedrock_agent.parsing.orchestrator import (
    ParsingResult,
    _generate_frontmatter,
    _get_type_subdir,
    run_project_parsing,
    save_parsing_manifest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Strategy Selection
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategySelection(unittest.TestCase):
    """Test parser strategy routing for different file types."""

    def _make_pf(self, source_type: SourceType, relative_path: str = "test.ext",
                 role: str = "", size_bytes: int = 1000) -> ProjectFile:
        return ProjectFile(
            path=f"/tmp/{relative_path}",
            source_type=source_type,
            relative_path=relative_path,
            document_role=role,
            size_bytes=size_bytes,
        )

    def test_excel_routes_to_excel_vlm(self):
        pf = self._make_pf(SourceType.EXCEL_SHEET, "workbook.xlsx")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "excel_vlm")
        self.assertEqual(skip_reason, "")

    def test_pdf_routes_to_pdf_vlm(self):
        pf = self._make_pf(SourceType.PDF_NATIVE, "document.pdf")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "pdf_vlm")
        self.assertEqual(skip_reason, "")

    def test_docx_routes_to_docx(self):
        pf = self._make_pf(SourceType.DOCX, "document.docx")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "docx")
        self.assertEqual(skip_reason, "")

    def test_legacy_doc_routes_to_doc_vlm(self):
        pf = self._make_pf(SourceType.DOCX, "legacy.doc")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "doc_vlm")
        self.assertEqual(skip_reason, "")

    def test_csv_routes_to_csv(self):
        pf = self._make_pf(SourceType.CSV, "data.csv")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "csv")
        self.assertEqual(skip_reason, "")

    def test_mermaid_skipped(self):
        pf = self._make_pf(SourceType.MERMAID, "flow.mmd")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "mermaid")
        self.assertIn("already handled", skip_reason)

    def test_markdown_routes_to_markdown(self):
        pf = self._make_pf(SourceType.MARKDOWN, "readme.md")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "markdown")
        self.assertEqual(skip_reason, "")

    def test_html_routes_to_html(self):
        pf = self._make_pf(SourceType.HTML, "page.html")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "html")
        self.assertEqual(skip_reason, "")

    def test_image_asset_skipped(self):
        pf = self._make_pf(SourceType.IMAGE, "icon.png", role=DocumentRole.ASSET.value, size_bytes=500)
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "skip")
        self.assertIn("asset", skip_reason.lower())

    def test_image_non_asset_routes_to_image_vlm(self):
        pf = self._make_pf(SourceType.IMAGE, "diagram.png", role=DocumentRole.SCREENSHOT.value)
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "image_vlm")
        self.assertEqual(skip_reason, "")

    def test_code_routes_to_code(self):
        pf = self._make_pf(SourceType.CODE, "app.py")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "code")
        self.assertEqual(skip_reason, "")

    def test_minified_js_skipped(self):
        pf = self._make_pf(SourceType.CODE, "bundle.min.js")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "skip")
        self.assertIn("minified", skip_reason.lower())

    def test_unknown_type_skipped(self):
        pf = self._make_pf(SourceType.UNKNOWN, "random.bin")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "skip")
        self.assertIn("unknown", skip_reason.lower())

    def test_unknown_js_routes_to_code(self):
        pf = self._make_pf(SourceType.UNKNOWN, "util.js")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "code")
        self.assertEqual(skip_reason, "")

    def test_plaintext_routes_to_text(self):
        pf = self._make_pf(SourceType.PLAINTEXT, "notes.txt")
        parser_type, skip_reason = select_parser(pf)
        self.assertEqual(parser_type, "text")
        self.assertEqual(skip_reason, "")

    def test_run_strategy_selection_assigns_all(self):
        files = [
            self._make_pf(SourceType.EXCEL_SHEET, "wb.xlsx"),
            self._make_pf(SourceType.PDF_NATIVE, "doc.pdf"),
            self._make_pf(SourceType.CSV, "data.csv"),
        ]
        run_strategy_selection(files)
        self.assertEqual(files[0].parser_type, "excel_vlm")
        self.assertEqual(files[1].parser_type, "pdf_vlm")
        self.assertEqual(files[2].parser_type, "csv")


class TestSkipAndVlmSets(unittest.TestCase):
    """Verify SKIP_TYPES and VLM_TYPES constants."""

    def test_skip_types_contains_expected(self):
        self.assertIn("skip", SKIP_TYPES)
        self.assertIn("mermaid", SKIP_TYPES)

    def test_vlm_types_contains_expected(self):
        self.assertIn("pdf_vlm", VLM_TYPES)
        self.assertIn("image_vlm", VLM_TYPES)
        self.assertIn("excel_vlm", VLM_TYPES)
        self.assertIn("doc_vlm", VLM_TYPES)


# ─────────────────────────────────────────────────────────────────────────────
# Test Parser Registry
# ─────────────────────────────────────────────────────────────────────────────


class TestParserRegistry(unittest.TestCase):
    """Test parser registration and routing."""

    def test_register_and_get_parser(self):
        reg = ParserRegistry()
        mock_parser = MagicMock()
        mock_parser.name = "test_parser"
        mock_parser.can_handle.return_value = True
        reg.register(mock_parser)

        result = reg.get_parser(Path("test.txt"), SourceType.PLAINTEXT)
        self.assertEqual(result, mock_parser)

    def test_get_parser_returns_none_when_no_match(self):
        reg = ParserRegistry()
        mock_parser = MagicMock()
        mock_parser.can_handle.return_value = False
        reg.register(mock_parser)

        result = reg.get_parser(Path("test.txt"), SourceType.UNKNOWN)
        self.assertIsNone(result)

    def test_first_matching_parser_wins(self):
        reg = ParserRegistry()
        parser1 = MagicMock()
        parser1.name = "first"
        parser1.can_handle.return_value = True
        parser2 = MagicMock()
        parser2.name = "second"
        parser2.can_handle.return_value = True

        reg.register(parser1)
        reg.register(parser2)

        result = reg.get_parser(Path("test.pdf"), SourceType.PDF_NATIVE)
        self.assertEqual(result, parser1)

    def test_parsers_property(self):
        reg = ParserRegistry()
        parser1 = MagicMock()
        parser1.name = "csv_parser"
        parser2 = MagicMock()
        parser2.name = "pdf_parser"
        reg.register(parser1)
        reg.register(parser2)

        parsers = reg.parsers
        self.assertEqual(len(parsers), 2)
        self.assertIn("csv_parser", parsers)
        self.assertIn("pdf_parser", parsers)

    def test_create_default_registry_has_all_parsers(self):
        """Default registry registers all expected parser types."""
        reg = create_default_registry()
        names = set(reg.parsers.keys())
        # Should include at least the core parsers
        expected_names = {"excel_vlm_adapter", "csv_parser", "pdf_vlm_parser", "code_parser", "markdown_parser", "html_parser", "image_vlm_parser"}
        for name in expected_names:
            self.assertIn(name, names, f"Missing parser: {name}")

    def test_get_all_parsers_returns_list(self):
        reg = ParserRegistry()
        parser1 = MagicMock()
        parser1.name = "p1"
        reg.register(parser1)
        all_p = reg.get_all_parsers()
        self.assertEqual(len(all_p), 1)
        self.assertEqual(all_p[0], parser1)


# ─────────────────────────────────────────────────────────────────────────────
# Test Orchestrator Helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestratorHelpers(unittest.TestCase):
    """Test orchestrator helper functions."""

    def test_get_type_subdir_mapping(self):
        self.assertEqual(_get_type_subdir("excel_vlm"), "excel")
        self.assertEqual(_get_type_subdir("pdf_vlm"), "pdf")
        self.assertEqual(_get_type_subdir("csv"), "csv")
        self.assertEqual(_get_type_subdir("code"), "code")
        self.assertEqual(_get_type_subdir("html"), "html")
        self.assertEqual(_get_type_subdir("markdown"), "txt")
        self.assertEqual(_get_type_subdir("image_vlm"), "images")
        self.assertEqual(_get_type_subdir("docx"), "docx")
        self.assertEqual(_get_type_subdir("mermaid"), "mermaid")

    def test_get_type_subdir_unknown_defaults_to_txt(self):
        self.assertEqual(_get_type_subdir("unknown_parser"), "txt")

    def test_generate_frontmatter_basic(self):
        pf = ProjectFile(
            path="/source/test.xlsx",
            source_type=SourceType.EXCEL_SHEET,
            relative_path="test.xlsx",
            parser_type="excel_vlm",
            document_role="primary",
            size_bytes=5000,
        )
        fm = _generate_frontmatter(
            pf, "test_project", "vlm_parse", "abc123hash",
            evidence_paths=["evidence/excel/test/sheet_01/full.png"],
            document_id="doc001",
            document_name="TestWorkbook",
        )
        self.assertIn("---", fm)
        self.assertIn("source_type: excel", fm)  # Normalized from excel_sheet
        self.assertIn("project_id: test_project", fm)
        self.assertIn("document_id: \"doc001\"", fm)
        self.assertIn("document_name: \"TestWorkbook\"", fm)
        self.assertIn("content_hash: \"abc123hash\"", fm)
        self.assertIn("evidence_paths:", fm)
        self.assertIn("evidence/excel/test/sheet_01/full.png", fm)

    def test_generate_frontmatter_normalizes_excel_sheet(self):
        """source_type excel_sheet is normalized to 'excel' in frontmatter."""
        pf = ProjectFile(
            path="/source/wb.xlsx",
            source_type=SourceType.EXCEL_SHEET,
            relative_path="wb.xlsx",
            parser_type="excel_vlm",
            size_bytes=1000,
        )
        fm = _generate_frontmatter(pf, "proj1", "vlm", "hash1")
        self.assertIn("source_type: excel", fm)
        self.assertNotIn("excel_sheet", fm)

    def test_generate_frontmatter_no_evidence(self):
        pf = ProjectFile(
            path="/source/readme.md",
            source_type=SourceType.MARKDOWN,
            relative_path="readme.md",
            parser_type="markdown",
            size_bytes=200,
        )
        fm = _generate_frontmatter(pf, "proj1", "passthrough", "hash2")
        self.assertNotIn("evidence_paths:", fm)

    def test_parsing_result_to_dict(self):
        result = ParsingResult()
        result.files_scanned = 10
        result.files_parsed = 7
        result.files_skipped = 2
        result.files_failed = 1
        result.duration_seconds = 12.345
        d = result.to_dict()
        self.assertEqual(d["files_scanned"], 10)
        self.assertEqual(d["files_parsed"], 7)
        self.assertEqual(d["duration_seconds"], 12.3)


# ─────────────────────────────────────────────────────────────────────────────
# Test Orchestrator (with mocked parsing)
# ─────────────────────────────────────────────────────────────────────────────


class TestOrchestrator(unittest.TestCase):
    """Test the orchestrator end-to-end with mocked parsers."""

    def _make_manifest(self, files: list[ProjectFile]) -> ProjectManifest:
        return ProjectManifest(
            project_id="test_project",
            display_name="Test Project",
            source_location="/source",
            files=files,
        )

    def test_dry_run_classifies_without_parsing(self):
        """Dry run mode classifies files but does not call parsers."""
        pf = ProjectFile(
            path="/tmp/test.csv",
            source_type=SourceType.CSV,
            relative_path="test.csv",
            size_bytes=100,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            result = run_project_parsing(
                "test_project", manifest, Path(td), dry_run=True
            )

        self.assertEqual(result.files_scanned, 1)
        self.assertEqual(result.files_parsed, 1)  # counted as "would be parsed"
        self.assertEqual(result.by_parser.get("csv"), 1)

    def test_skipped_files_counted(self):
        """Files with skip strategy are counted as skipped."""
        pf = ProjectFile(
            path="/tmp/flow.mmd",
            source_type=SourceType.MERMAID,
            relative_path="flow.mmd",
            size_bytes=50,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            result = run_project_parsing(
                "test_project", manifest, Path(td), dry_run=True
            )

        self.assertEqual(result.files_skipped, 1)
        self.assertEqual(result.files_parsed, 0)

    def test_vlm_skip_flag_honored(self):
        """skip_vlm=True causes VLM files to be skipped."""
        pf = ProjectFile(
            path="/tmp/doc.pdf",
            source_type=SourceType.PDF_NATIVE,
            relative_path="doc.pdf",
            size_bytes=10000,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            result = run_project_parsing(
                "test_project", manifest, Path(td), skip_vlm=True
            )

        self.assertEqual(result.files_skipped, 1)
        self.assertIn("vlm_skipped_by_flag", result.skip_reasons)

    @patch("hermes_bedrock_agent.parsing.orchestrator.create_default_registry")
    def test_parser_failure_recorded(self, mock_create_reg):
        """Parser exceptions are caught and recorded as failures."""
        mock_registry = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = RuntimeError("VLM timeout")
        mock_parser.can_handle.return_value = True
        mock_registry.get_parser.return_value = mock_parser
        mock_create_reg.return_value = mock_registry

        pf = ProjectFile(
            path="/tmp/test.csv",
            source_type=SourceType.CSV,
            relative_path="test.csv",
            size_bytes=100,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            # Create the file so content_hash doesn't fail
            (Path(td) / "tmp").mkdir(parents=True, exist_ok=True)
            Path("/tmp/test.csv").write_text("a,b\n1,2")
            result = run_project_parsing("test_project", manifest, Path(td))

        self.assertEqual(result.files_failed, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("VLM timeout", result.errors[0]["error"])

    @patch("hermes_bedrock_agent.parsing.orchestrator.create_default_registry")
    def test_successful_parse_writes_output(self, mock_create_reg):
        """Successful parse writes markdown with frontmatter."""
        mock_registry = MagicMock()
        mock_parser = MagicMock()
        mock_parser.can_handle.return_value = True
        mock_parser.parse.return_value = [
            ParsedDocument(
                doc_id="doc001",
                project_id="test_project",
                source_path="/tmp/test.csv",
                source_type=SourceType.CSV,
                title="TestDoc",
                content_markdown="# Parsed Content\nHello world",
                parse_method="test_parse",
                content_hash="testhash",
                evidence_paths=["evidence/csv/test/img.png"],
                metadata={"estimated_cost_usd": 0.01},
            )
        ]
        mock_registry.get_parser.return_value = mock_parser
        mock_create_reg.return_value = mock_registry

        pf = ProjectFile(
            path="/tmp/test.csv",
            source_type=SourceType.CSV,
            relative_path="test.csv",
            size_bytes=100,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            Path("/tmp/test.csv").write_text("a,b\n1,2")
            result = run_project_parsing("test_project", manifest, Path(td))

            self.assertEqual(result.files_parsed, 1)
            self.assertEqual(result.files_failed, 0)

            # Check output file exists with frontmatter
            output_files = list(Path(td).rglob("*.md"))
            self.assertTrue(len(output_files) > 0)
            content = output_files[0].read_text()
            self.assertIn("---", content)
            self.assertIn("project_id: test_project", content)
            self.assertIn("# Parsed Content", content)

    @patch("hermes_bedrock_agent.parsing.orchestrator.create_default_registry")
    def test_no_parser_available(self, mock_create_reg):
        """When no parser matches, file is marked as failed."""
        mock_registry = MagicMock()
        mock_registry.get_parser.return_value = None
        mock_create_reg.return_value = mock_registry

        pf = ProjectFile(
            path="/tmp/mystery.xyz",
            source_type=SourceType.PLAINTEXT,
            relative_path="mystery.xyz",
            size_bytes=100,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            Path("/tmp/mystery.xyz").write_text("hello")
            result = run_project_parsing("test_project", manifest, Path(td))

        self.assertEqual(result.files_failed, 1)
        self.assertIn("no_parser_available", result.errors[0]["error"])

    @patch("hermes_bedrock_agent.parsing.orchestrator.create_default_registry")
    def test_empty_parser_return_recorded(self, mock_create_reg):
        """When parser returns empty list, file is marked as failed."""
        mock_registry = MagicMock()
        mock_parser = MagicMock()
        mock_parser.can_handle.return_value = True
        mock_parser.parse.return_value = []  # Empty result
        mock_registry.get_parser.return_value = mock_parser
        mock_create_reg.return_value = mock_registry

        pf = ProjectFile(
            path="/tmp/empty.csv",
            source_type=SourceType.CSV,
            relative_path="empty.csv",
            size_bytes=10,
        )
        manifest = self._make_manifest([pf])

        with tempfile.TemporaryDirectory() as td:
            Path("/tmp/empty.csv").write_text("")
            result = run_project_parsing("test_project", manifest, Path(td))

        self.assertEqual(result.files_failed, 1)
        self.assertIn("parser_returned_empty", result.errors[0]["error"])

    def test_limit_parameter_caps_candidates(self):
        """limit=N processes at most N parseable files."""
        files = [
            ProjectFile(path=f"/tmp/f{i}.csv", source_type=SourceType.CSV,
                       relative_path=f"f{i}.csv", size_bytes=100)
            for i in range(10)
        ]
        manifest = self._make_manifest(files)

        with tempfile.TemporaryDirectory() as td:
            result = run_project_parsing(
                "test_project", manifest, Path(td), dry_run=True, limit=3
            )

        self.assertEqual(result.files_parsed, 3)


# ─────────────────────────────────────────────────────────────────────────────
# Test Manifest Saving
# ─────────────────────────────────────────────────────────────────────────────


class TestManifestSaving(unittest.TestCase):
    """Test parsing manifest output."""

    def test_save_parsing_manifest_writes_json(self):
        manifest = ProjectManifest(
            project_id="test_proj",
            display_name="Test",
            source_location="/src",
            files=[
                ProjectFile(
                    path="/src/doc.pdf",
                    source_type=SourceType.PDF_NATIVE,
                    relative_path="doc.pdf",
                    parser_type="pdf_vlm",
                    state=FileState.PARSED,
                )
            ],
        )
        result = ParsingResult()
        result.files_scanned = 1
        result.files_parsed = 1

        with tempfile.TemporaryDirectory() as td:
            out_path = save_parsing_manifest(manifest, result, Path(td))
            self.assertTrue(out_path.exists())
            data = json.loads(out_path.read_text())
            self.assertIn("parsing_run", data)
            self.assertEqual(data["manifest_version"], "2.1")
            self.assertEqual(data["parsing_run"]["result"]["files_parsed"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Test Output Writer
# ─────────────────────────────────────────────────────────────────────────────


class TestOutputWriter(unittest.TestCase):
    """Test UnifiedOutputWriter setup and reorganization."""

    def test_setup_workbook_creates_dirs(self):
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        with tempfile.TemporaryDirectory() as td:
            writer = UnifiedOutputWriter(Path(td), "test_proj")
            wb_paths = writer.setup_workbook("債務_APIデータ形式")

            self.assertTrue(wb_paths.pdf_staging.exists())
            self.assertTrue(wb_paths.image_staging.exists())
            self.assertTrue(wb_paths.vlm_staging.exists())
            self.assertTrue(wb_paths.parsed_dir.exists())
            self.assertTrue(wb_paths.evidence_dir.exists())
            self.assertTrue(wb_paths.legacy_dir.exists())

    def test_setup_workbook_preserves_japanese_names(self):
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        with tempfile.TemporaryDirectory() as td:
            writer = UnifiedOutputWriter(Path(td), "test_proj")
            wb_paths = writer.setup_workbook("FY2024_HULFT_債務奉行")

            # Japanese characters preserved in path
            self.assertIn("FY2024_HULFT_債務奉行", str(wb_paths.parsed_dir))
            self.assertEqual(wb_paths.workbook_name, "FY2024_HULFT_債務奉行")

    def test_writer_paths_under_correct_hierarchy(self):
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        with tempfile.TemporaryDirectory() as td:
            writer = UnifiedOutputWriter(Path(td), "test_proj")
            wb_paths = writer.setup_workbook("TestWB")

            # Canonical structure: parsed/excel/<name>, evidence/excel/<name>
            self.assertIn("parsed/excel/TestWB", str(wb_paths.parsed_dir))
            self.assertIn("evidence/excel/TestWB", str(wb_paths.evidence_dir))
            self.assertIn("legacy_compat/TestWB", str(wb_paths.legacy_dir))


if __name__ == "__main__":
    unittest.main()
