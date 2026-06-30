"""Tests for type-aware routing: plaintext→txt, PDF→pdf, no-docs canonical output.

Validates the routing fixes:
1. .txt / SourceType.PLAINTEXT → parser_type="text" → parsed/txt/
2. .pdf / SourceType.PDF_NATIVE → parser_type="pdf_vlm" → parsed/pdf/
3. No canonical output uses parsed/docs/
4. CodeParser no longer handles plaintext files
"""

import json
import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.models.document import ProjectFile, SourceType
from hermes_bedrock_agent.parsing.strategy import select_parser
from hermes_bedrock_agent.parsing.orchestrator import _TYPE_SUBDIR_MAP, _get_type_subdir
from hermes_bedrock_agent.parsing.code_parser import CodeParser
from hermes_bedrock_agent.parsing.text_parser import TextParser
from hermes_bedrock_agent.parsing.registry import create_default_registry
from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir
from hermes_bedrock_agent.config import Config


# ─── Plaintext routing ──────────────────────────────────────────────────────


class TestPlaintextRoutesToTxt:
    """Verify .txt files route to parsed/txt/ via parser_type='text'."""

    def test_strategy_selects_text_parser_for_plaintext(self):
        """select_parser returns parser_type='text' for SourceType.PLAINTEXT."""
        pf = ProjectFile(
            path="/tmp/readme.txt",
            relative_path="readme.txt",
            source_type=SourceType.PLAINTEXT,
            size_bytes=200,
        )
        parser_type, reason = select_parser(pf)
        assert parser_type == "text"
        assert reason == ""

    def test_strategy_selects_text_parser_for_log_files(self):
        """select_parser returns parser_type='text' for .log files (PLAINTEXT)."""
        pf = ProjectFile(
            path="/tmp/app.log",
            relative_path="app.log",
            source_type=SourceType.PLAINTEXT,
            size_bytes=5000,
        )
        parser_type, reason = select_parser(pf)
        assert parser_type == "text"

    def test_type_subdir_map_routes_text_to_txt(self):
        """_TYPE_SUBDIR_MAP maps 'text' → 'txt'."""
        assert _get_type_subdir("text") == "txt"

    def test_no_plaintext_in_code_directory(self):
        """After parsing, plaintext files must NOT appear in parsed/code/."""
        pf = ProjectFile(
            path="/tmp/setup.txt",
            relative_path="setup.txt",
            source_type=SourceType.PLAINTEXT,
            size_bytes=300,
        )
        parser_type, _ = select_parser(pf)
        subdir = _get_type_subdir(parser_type)
        assert subdir == "txt", f"Plaintext routed to '{subdir}' instead of 'txt'"
        assert subdir != "code", "Plaintext must not route to code/"

    def test_text_parser_can_handle_plaintext(self):
        """TextParser.can_handle returns True for PLAINTEXT."""
        tp = TextParser()
        assert tp.can_handle(Path("test.txt"), SourceType.PLAINTEXT)
        assert tp.can_handle(Path("app.log"), SourceType.PLAINTEXT)

    def test_text_parser_cannot_handle_code(self):
        """TextParser.can_handle returns False for CODE."""
        tp = TextParser()
        assert not tp.can_handle(Path("main.java"), SourceType.CODE)

    def test_code_parser_cannot_handle_plaintext(self):
        """CodeParser.can_handle returns False for PLAINTEXT."""
        cp = CodeParser()
        assert not cp.can_handle(Path("readme.txt"), SourceType.PLAINTEXT)

    def test_code_parser_still_handles_code(self):
        """CodeParser.can_handle returns True for CODE."""
        cp = CodeParser()
        assert cp.can_handle(Path("Main.java"), SourceType.CODE)

    def test_registry_resolves_text_parser_for_txt(self):
        """Registry returns TextParser for .txt + PLAINTEXT."""
        reg = create_default_registry()
        parser = reg.get_parser(Path("readme.txt"), SourceType.PLAINTEXT)
        assert parser is not None
        assert parser.name == "text_parser"

    def test_text_parser_output_no_code_fence(self):
        """TextParser output must NOT wrap content in code fences."""
        tp = TextParser()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello world\nLine 2\n")
            f.flush()
            docs = tp.parse(Path(f.name), "test_project")
        assert len(docs) == 1
        content = docs[0].content_markdown
        assert "```" not in content, "TextParser output must not contain code fences"
        assert "Hello world" in content

    def test_text_parser_output_has_heading(self):
        """TextParser output starts with a heading."""
        tp = TextParser()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Sample content\n")
            f.flush()
            docs = tp.parse(Path(f.name), "test_project")
        content = docs[0].content_markdown
        assert content.startswith("# ")

    def test_end_to_end_plaintext_chunking(self):
        """Plaintext files in parsed/txt/ are discovered and chunked correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            parsed_dir = Path(tmp)
            txt_dir = parsed_dir / "txt"
            txt_dir.mkdir(parents=True)

            # Content must exceed chunk_min_chars (100) after frontmatter stripping
            body = "This is a comprehensive setup guide for the system.\n" * 5
            content = f"---\nsource_type: plaintext\nparser_type: text\n---\n\n# Guide\n\n{body}"
            (txt_dir / "guide.md").write_text(content)

            cfg = Config()
            chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test", cfg=cfg)
            assert len(chunks) == 1
            assert chunks[0].source_type == "plaintext"
            assert "setup guide" in chunks[0].content.lower()


# ─── PDF routing ────────────────────────────────────────────────────────────


class TestPdfRoutesToPdf:
    """Verify .pdf files route to parsed/pdf/ via parser_type='pdf_vlm'."""

    def test_strategy_selects_pdf_vlm_for_pdf(self):
        """select_parser returns parser_type='pdf_vlm' for SourceType.PDF_NATIVE."""
        pf = ProjectFile(
            path="/tmp/spec.pdf",
            relative_path="spec.pdf",
            source_type=SourceType.PDF_NATIVE,
            size_bytes=100000,
        )
        parser_type, reason = select_parser(pf)
        assert parser_type == "pdf_vlm"
        assert reason == ""

    def test_type_subdir_map_routes_pdf_vlm_to_pdf(self):
        """_TYPE_SUBDIR_MAP maps 'pdf_vlm' → 'pdf'."""
        assert _get_type_subdir("pdf_vlm") == "pdf"

    def test_type_subdir_map_routes_doc_vlm_to_pdf(self):
        """_TYPE_SUBDIR_MAP maps 'doc_vlm' → 'pdf' (legacy .doc → LibreOffice → PDF → VLM)."""
        assert _get_type_subdir("doc_vlm") == "pdf"

    def test_pdf_output_directory_not_docs(self):
        """PDF must route to parsed/pdf/, not parsed/docs/."""
        pf = ProjectFile(
            path="/tmp/report.pdf",
            relative_path="report.pdf",
            source_type=SourceType.PDF_NATIVE,
            size_bytes=200000,
        )
        parser_type, _ = select_parser(pf)
        subdir = _get_type_subdir(parser_type)
        assert subdir == "pdf"
        assert subdir != "docs"

    def test_pdf_chunker_discovery(self):
        """Chunks from parsed/pdf/ are discovered correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            parsed_dir = Path(tmp)
            pdf_dir = parsed_dir / "pdf"
            pdf_dir.mkdir(parents=True)

            # Content must exceed chunk_min_chars (100) after frontmatter stripping
            body = "This is page 1 of the report with detailed specifications.\n" * 5
            content = f"---\nsource_type: pdf_native\nparser_type: pdf_vlm\n---\n\n# Report\n\n{body}"
            (pdf_dir / "report_pdf.md").write_text(content)

            cfg = Config()
            chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test", cfg=cfg)
            assert len(chunks) == 1
            assert chunks[0].source_type == "pdf_native"

    def test_pdf_vlm_full_regression_skipped_note(self):
        """Document: full PDF VLM parsing requires Bedrock VLM API access.

        This test documents that the routing logic is verified via unit test,
        but full end-to-end PDF VLM parsing cannot run without API credentials.
        The routing chain is: .pdf → SourceType.PDF_NATIVE → pdf_vlm → parsed/pdf/
        """
        # This is a documentation test — the assertion is the routing test above
        assert _get_type_subdir("pdf_vlm") == "pdf"


# ─── No docs canonical output ──────────────────────────────────────────────


class TestNoDocsCanonicalOutput:
    """Verify 'docs' is not a canonical output directory."""

    def test_no_docs_in_type_subdir_map_values(self):
        """'docs' must not appear as a value in _TYPE_SUBDIR_MAP."""
        assert "docs" not in _TYPE_SUBDIR_MAP.values(), (
            f"Found 'docs' in map values: {_TYPE_SUBDIR_MAP}"
        )

    def test_no_docs_for_any_parser_type(self):
        """No parser_type routes to 'docs'."""
        all_types = [
            "docx", "doc_vlm", "pdf_vlm", "html", "text", "markdown",
            "csv", "image_vlm", "code", "excel_vlm", "mermaid", "mermaid_v2",
        ]
        for pt in all_types:
            subdir = _get_type_subdir(pt)
            assert subdir != "docs", f"parser_type={pt} routes to 'docs'"

    def test_canonical_subdirs_are_explicit_types(self):
        """All canonical subdirs must be explicit type names."""
        expected_subdirs = {"excel", "mermaid", "csv", "code", "pdf", "docx", "html", "txt", "images"}
        actual_subdirs = set(_TYPE_SUBDIR_MAP.values())
        assert actual_subdirs.issubset(expected_subdirs), (
            f"Unexpected subdirs: {actual_subdirs - expected_subdirs}"
        )

    def test_legacy_docs_dir_still_readable_by_chunker(self):
        """If a legacy run left parsed/docs/, the chunker still reads it."""
        with tempfile.TemporaryDirectory() as tmp:
            parsed_dir = Path(tmp)
            # Create legacy docs/ dir
            docs_dir = parsed_dir / "docs"
            docs_dir.mkdir(parents=True)
            # Content must exceed chunk_min_chars (100) after frontmatter stripping
            body = "This is a legacy document with enough content for chunking.\n" * 5
            content = f"---\nsource_type: docx\nparser_type: docx\n---\n\n# Legacy Doc\n\n{body}"
            (docs_dir / "old_doc.md").write_text(content)

            cfg = Config()
            chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test", cfg=cfg)
            assert len(chunks) == 1
            assert "Legacy Doc" in chunks[0].content or "legacy document" in chunks[0].content

    def test_docx_routes_to_docx_not_docs(self):
        """DOCX files must route to parsed/docx/, not parsed/docs/."""
        pf = ProjectFile(
            path="/tmp/spec.docx",
            relative_path="spec.docx",
            source_type=SourceType.DOCX,
            size_bytes=50000,
        )
        parser_type, _ = select_parser(pf)
        subdir = _get_type_subdir(parser_type)
        assert subdir == "docx"
        assert subdir != "docs"

    def test_html_routes_to_html_not_docs(self):
        """HTML files must route to parsed/html/, not parsed/docs/."""
        pf = ProjectFile(
            path="/tmp/page.html",
            relative_path="page.html",
            source_type=SourceType.HTML,
            size_bytes=3000,
        )
        parser_type, _ = select_parser(pf)
        subdir = _get_type_subdir(parser_type)
        assert subdir == "html"
        assert subdir != "docs"
