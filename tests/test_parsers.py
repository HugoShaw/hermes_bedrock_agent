"""Tests for individual parsers."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.s3_graph_etl.parsers.text_parser import TextParser
from hermes_bedrock_agent.s3_graph_etl.parsers.code_parser import CodeParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, ParserType


class TestTextParser:
    def setup_method(self):
        self.parser = TextParser()

    def test_supported_extensions(self):
        assert ".txt" in self.parser.supported_extensions
        assert ".md" in self.parser.supported_extensions

    def test_parse_simple_text(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Hello world. This is a test.")
            f.flush()
            chunks = self.parser.parse(Path(f.name), "s3://b/test.txt")

        assert len(chunks) == 1
        assert chunks[0].text == "Hello world. This is a test."
        assert chunks[0].parser_type == ParserType.PYTHON_PARSER
        Path(f.name).unlink(missing_ok=True)

    def test_parse_markdown_with_headings(self):
        content = "# Title\n\nIntro paragraph.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(content)
            f.flush()
            chunks = self.parser.parse(Path(f.name), "s3://b/doc.md")

        assert len(chunks) >= 2
        # Should split by headings
        titles = [c.title for c in chunks if c.title]
        assert any("Title" in t or "Section" in t for t in titles)
        Path(f.name).unlink(missing_ok=True)

    def test_chunk_id_deterministic(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("test content")
            f.flush()
            chunks1 = self.parser.parse(Path(f.name), "s3://b/test.txt")
            chunks2 = self.parser.parse(Path(f.name), "s3://b/test.txt")

        assert chunks1[0].id == chunks2[0].id
        Path(f.name).unlink(missing_ok=True)


class TestCodeParser:
    def setup_method(self):
        self.parser = CodeParser()

    def test_supported_extensions(self):
        exts = self.parser.supported_extensions
        assert ".py" in exts
        assert ".java" in exts
        assert ".sql" in exts

    def test_parse_python(self):
        code = """def hello():
    return "world"

class MyClass:
    def method(self):
        pass
"""
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            f.flush()
            chunks = self.parser.parse(Path(f.name), "s3://b/code.py")

        assert len(chunks) >= 2
        assert all(c.content_type == ContentType.CODE for c in chunks)
        Path(f.name).unlink(missing_ok=True)

    def test_parse_sql(self):
        sql = """CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(100)
);

CREATE TABLE orders (
    id INT PRIMARY KEY,
    user_id INT REFERENCES users(id)
);
"""
        with tempfile.NamedTemporaryFile(suffix=".sql", mode="w", delete=False) as f:
            f.write(sql)
            f.flush()
            chunks = self.parser.parse(Path(f.name), "s3://b/schema.sql")

        assert len(chunks) >= 2
        assert all(c.content_type == ContentType.DDL for c in chunks)
        Path(f.name).unlink(missing_ok=True)
