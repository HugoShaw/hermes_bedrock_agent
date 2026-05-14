"""Tests for utils module — json_utils, timing."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from hermes_bedrock_agent.schemas.document import SourceDocument, SourceType
from hermes_bedrock_agent.utils.json_utils import (
    count_jsonl,
    read_jsonl,
    stream_jsonl,
    write_jsonl,
)
from hermes_bedrock_agent.utils.timing import Timer, timed


# ---------------------------------------------------------------------------
# JSONL utilities
# ---------------------------------------------------------------------------


class TestJsonlReadWrite:
    def test_write_and_read_roundtrip(self, tmp_path: Path):
        docs = [
            SourceDocument(
                document_id=f"doc_{i}",
                source_uri=f"s3://bucket/file_{i}.pdf",
                source_type=SourceType.PDF,
            )
            for i in range(5)
        ]
        output = tmp_path / "test.jsonl"
        written = write_jsonl(output, docs)
        assert written == 5
        assert output.exists()

        restored = read_jsonl(output, SourceDocument)
        assert len(restored) == 5
        assert restored[0].document_id == "doc_0"
        assert restored[4].source_type == SourceType.PDF

    def test_append_mode(self, tmp_path: Path):
        output = tmp_path / "append.jsonl"
        doc1 = SourceDocument(document_id="d1", source_uri="s3://b/1")
        doc2 = SourceDocument(document_id="d2", source_uri="s3://b/2")

        write_jsonl(output, [doc1])
        write_jsonl(output, [doc2], append=True)

        all_docs = read_jsonl(output, SourceDocument)
        assert len(all_docs) == 2

    def test_stream_jsonl(self, tmp_path: Path):
        docs = [
            SourceDocument(document_id=f"doc_{i}", source_uri=f"s3://b/{i}")
            for i in range(10)
        ]
        output = tmp_path / "stream.jsonl"
        write_jsonl(output, docs)

        streamed = list(stream_jsonl(output, SourceDocument))
        assert len(streamed) == 10

    def test_count_jsonl(self, tmp_path: Path):
        docs = [
            SourceDocument(document_id=f"doc_{i}", source_uri=f"s3://b/{i}")
            for i in range(7)
        ]
        output = tmp_path / "count.jsonl"
        write_jsonl(output, docs)
        assert count_jsonl(output) == 7

    def test_count_nonexistent(self, tmp_path: Path):
        assert count_jsonl(tmp_path / "missing.jsonl") == 0


# ---------------------------------------------------------------------------
# Timing utilities
# ---------------------------------------------------------------------------


class TestTimer:
    def test_basic_timing(self):
        with Timer("test") as t:
            time.sleep(0.01)
        assert t.elapsed_ms >= 10
        assert t.elapsed_s >= 0.01

    def test_repr(self):
        with Timer("my_op") as t:
            pass
        assert "my_op" in repr(t)


class TestTimedDecorator:
    def test_sync_function(self):
        @timed
        def slow_fn():
            time.sleep(0.01)
            return 42

        result = slow_fn()
        assert result == 42

    def test_preserves_exceptions(self):
        @timed
        def failing_fn():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_fn()
