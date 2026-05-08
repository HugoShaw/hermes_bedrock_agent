"""Tests for file router."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.s3_graph_etl.parsers.file_router import FileRouter
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType


class TestFileRouter:
    def setup_method(self):
        self.router = FileRouter()

    def test_supported_extensions(self):
        exts = self.router.supported_extensions
        assert ".txt" in exts
        assert ".md" in exts
        assert ".py" in exts
        assert ".sql" in exts
        assert ".pdf" in exts
        assert ".docx" in exts

    def test_get_parser_name_text(self):
        assert self.router.get_parser_name(Path("file.txt")) == "TextParser"
        assert self.router.get_parser_name(Path("file.md")) == "TextParser"

    def test_get_parser_name_code(self):
        assert self.router.get_parser_name(Path("file.py")) == "CodeParser"
        assert self.router.get_parser_name(Path("file.sql")) == "CodeParser"
        assert self.router.get_parser_name(Path("file.java")) == "CodeParser"

    def test_get_parser_name_pdf(self):
        assert self.router.get_parser_name(Path("file.pdf")) == "PdfTextParser"

    def test_get_parser_name_docx(self):
        assert self.router.get_parser_name(Path("file.docx")) == "DocxParser"

    def test_get_parser_name_unknown(self):
        assert self.router.get_parser_name(Path("file.xyz")) is None

    def test_route_txt_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Hello world\nThis is a test document.")
            f.flush()
            chunks = self.router.route(Path(f.name), "s3://bucket/test.txt")

        assert len(chunks) >= 1
        assert chunks[0].source_uri == "s3://bucket/test.txt"
        assert "Hello world" in chunks[0].text
        Path(f.name).unlink(missing_ok=True)

    def test_route_markdown_file(self):
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Title\n\nSome content\n\n## Section\n\nMore content")
            f.flush()
            chunks = self.router.route(Path(f.name), "s3://bucket/doc.md")

        assert len(chunks) >= 1
        Path(f.name).unlink(missing_ok=True)

    def test_route_python_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def hello():\n    return \"world\"\n\nclass Foo:\n    pass\n")
            f.flush()
            chunks = self.router.route(Path(f.name), "s3://bucket/code.py")

        assert len(chunks) >= 1
        assert chunks[0].content_type == ContentType.CODE
        Path(f.name).unlink(missing_ok=True)

    def test_route_sql_file(self):
        with tempfile.NamedTemporaryFile(suffix=".sql", mode="w", delete=False) as f:
            f.write("CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100));\n")
            f.flush()
            chunks = self.router.route(Path(f.name), "s3://bucket/schema.sql")

        assert len(chunks) >= 1
        assert chunks[0].content_type == ContentType.DDL
        Path(f.name).unlink(missing_ok=True)

    def test_route_unknown_extension_returns_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False) as f:
            f.write("some content")
            f.flush()
            chunks = self.router.route(Path(f.name), "s3://bucket/file.xyz")

        assert chunks == []
        Path(f.name).unlink(missing_ok=True)
