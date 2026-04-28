"""Tests for GraphRAG components."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from hermes_bedrock_agent.graphrag import db as db_mod
from hermes_bedrock_agent.graphrag.embedder import cosine_similarity, deserialize_embedding, serialize_embedding
from hermes_bedrock_agent.graphrag.extractor import (
    _split_into_chunks,
    extract_document,
    extract_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "graphrag.db"
    db_mod.init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# test_db_init
# ---------------------------------------------------------------------------

class TestDbInit:
    def test_tables_created(self, tmp_db: Path) -> None:
        """All four graph tables must exist after init_db."""
        with db_mod.get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        names = {row["name"] for row in rows}
        assert {"gr_documents", "gr_chunks", "gr_entities", "gr_edges"} <= names

    def test_indexes_created(self, tmp_db: Path) -> None:
        with db_mod.get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            ).fetchall()
        index_names = {row["name"] for row in rows}
        assert "idx_chunks_doc" in index_names
        assert "idx_edges_src" in index_names
        assert "idx_edges_dst" in index_names
        assert "idx_entities_name" in index_names

    def test_idempotent(self, tmp_path: Path) -> None:
        """Calling init_db twice should not raise."""
        db_path = tmp_path / "graphrag.db"
        db_mod.init_db(db_path)
        db_mod.init_db(db_path)  # second call should be a no-op

    def test_stats_empty(self, tmp_db: Path) -> None:
        with db_mod.get_connection(tmp_db) as conn:
            stats = db_mod.get_stats(conn)
        assert stats["documents"] == 0
        assert stats["chunks"] == 0
        assert stats["entities"] == 0
        assert stats["edges"] == 0
        assert stats["embedding_coverage_pct"] == 0


# ---------------------------------------------------------------------------
# test_extractor_txt
# ---------------------------------------------------------------------------

class TestExtractorTxt:
    def test_basic_extraction(self) -> None:
        content = b"Hello World.\n\nThis is a test document about Python programming."
        result = extract_document("graphrag/test.txt", content, "txt")

        assert result.doc_id  # non-empty sha256
        assert result.filename == "test.txt"
        assert result.file_type == "txt"
        assert len(result.chunks) >= 1
        assert result.char_count == len(content.decode("utf-8"))
        assert result.content_hash  # non-empty

    def test_entities_extracted(self) -> None:
        content = b"Python is a programming language. Guido van Rossum created Python in the Netherlands."
        result = extract_document("graphrag/entities.txt", content, "txt")

        entity_names = {e.name for e in result.entities}
        # At minimum our regex extractor should find some capitalized phrases
        assert len(entity_names) >= 1

    def test_doc_contains_chunk_edges(self) -> None:
        content = b"First paragraph.\n\nSecond paragraph."
        result = extract_document("graphrag/edges.txt", content, "txt")

        contains_edges = [e for e in result.edges if e.edge_type == "CONTAINS"]
        assert len(contains_edges) == len(result.chunks)
        for edge in contains_edges:
            assert edge.src_id == result.doc_id
            assert edge.src_type == "document"
            assert edge.dst_type == "chunk"

    def test_json_extraction(self) -> None:
        data = {"title": "Test Doc", "body": "Some content here"}
        content = json.dumps(data).encode()
        result = extract_document("graphrag/data.json", content, "json")
        assert len(result.chunks) >= 1

    def test_csv_extraction(self) -> None:
        content = b"name,value\nAlice,1\nBob,2\n"
        result = extract_document("graphrag/data.csv", content, "csv")
        assert len(result.chunks) >= 1
        assert "name" in result.chunks[0].text.lower() or "Alice" in result.chunks[0].text

    def test_extract_text_unsupported_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_text(b"data", "exe")


# ---------------------------------------------------------------------------
# test_extractor_chunks
# ---------------------------------------------------------------------------

class TestExtractorChunks:
    def test_chunk_overlap(self) -> None:
        """Chunks should have overlapping content when text is long."""
        # Create text long enough to require multiple chunks
        long_para = "This sentence has some words. " * 80  # ~2400 chars, ~600 tokens
        paragraphs = [long_para] * 5
        chunks = _split_into_chunks(paragraphs)

        assert len(chunks) > 1
        # The end of chunk N should appear in the beginning of chunk N+1 (overlap)
        for i in range(len(chunks) - 1):
            tail = chunks[i][-200:]
            head = chunks[i + 1][:500]
            assert any(word in head for word in tail.split()[:5]), "No overlap detected between consecutive chunks"

    def test_short_text_single_chunk(self) -> None:
        paragraphs = ["Short text."]
        chunks = _split_into_chunks(paragraphs)
        assert len(chunks) == 1

    def test_empty_paragraphs_ignored(self) -> None:
        paragraphs = ["", "  ", "Real content.", ""]
        chunks = _split_into_chunks(paragraphs)
        assert len(chunks) == 1
        assert "Real content." in chunks[0]

    def test_chunk_ids_deterministic(self) -> None:
        content = b"Deterministic chunking test."
        r1 = extract_document("graphrag/det.txt", content, "txt")
        r2 = extract_document("graphrag/det.txt", content, "txt")
        assert [c.id for c in r1.chunks] == [c.id for c in r2.chunks]

    def test_different_keys_different_ids(self) -> None:
        content = b"Same content."
        r1 = extract_document("graphrag/a.txt", content, "txt")
        r2 = extract_document("graphrag/b.txt", content, "txt")
        assert r1.doc_id != r2.doc_id
        assert [c.id for c in r1.chunks] != [c.id for c in r2.chunks]


# ---------------------------------------------------------------------------
# test_cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self) -> None:
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_vector(self) -> None:
        a = np.array([0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 2.0], dtype=np.float32)
        assert cosine_similarity(a, b) == 0.0

    def test_serialization_roundtrip(self) -> None:
        v = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        blob = serialize_embedding(v)
        v2 = deserialize_embedding(blob)
        np.testing.assert_array_almost_equal(v, v2)


# ---------------------------------------------------------------------------
# test_show_map_empty
# ---------------------------------------------------------------------------

class TestShowMapEmpty:
    def test_stats_all_zero(self, tmp_db: Path) -> None:
        """Stats on empty DB must all be zero."""
        with db_mod.get_connection(tmp_db) as conn:
            stats = db_mod.get_stats(conn)
        for key in ("documents", "chunks", "entities", "edges"):
            assert stats[key] == 0

    def test_get_all_documents_empty(self, tmp_db: Path) -> None:
        with db_mod.get_connection(tmp_db) as conn:
            docs = db_mod.get_all_documents(conn)
        assert docs == []

    def test_get_all_entities_empty(self, tmp_db: Path) -> None:
        with db_mod.get_connection(tmp_db) as conn:
            entities = db_mod.get_all_entities(conn)
        assert entities == []


# ---------------------------------------------------------------------------
# DB round-trip tests (mock-free)
# ---------------------------------------------------------------------------

class TestDbRoundTrip:
    def test_upsert_and_retrieve_document(self, tmp_db: Path) -> None:
        with db_mod.get_connection(tmp_db) as conn:
            db_mod.upsert_document(
                conn,
                doc_id="docid1",
                s3_key="graphrag/test.txt",
                filename="test.txt",
                file_type="txt",
                content_hash="abc123",
                char_count=100,
                chunk_count=2,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            )

        with db_mod.get_connection(tmp_db) as conn:
            row = db_mod.get_document_by_s3_key(conn, "graphrag/test.txt")
        assert row is not None
        assert row["id"] == "docid1"
        assert row["filename"] == "test.txt"

    def test_upsert_entity_increments_mention_count(self, tmp_db: Path) -> None:
        kwargs = dict(
            entity_id="eid1",
            name="Python",
            entity_type="CONCEPT",
            description="CONCEPT: Python",
            mention_count=2,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        with db_mod.get_connection(tmp_db) as conn:
            db_mod.upsert_entity(conn, **kwargs)
            db_mod.upsert_entity(conn, **kwargs)  # second upsert adds count

        with db_mod.get_connection(tmp_db) as conn:
            row = db_mod.get_entity_by_name(conn, "Python")
        assert row is not None
        assert row["mention_count"] == 4  # 2 + 2

    def test_delete_document_cascades(self, tmp_db: Path) -> None:
        with db_mod.get_connection(tmp_db) as conn:
            db_mod.upsert_document(
                conn,
                doc_id="d1",
                s3_key="graphrag/del.txt",
                filename="del.txt",
                file_type="txt",
                content_hash="h",
                char_count=10,
                chunk_count=1,
                created_at="t",
                updated_at="t",
            )
            db_mod.insert_chunk(
                conn,
                chunk_id="c1",
                doc_id="d1",
                chunk_index=0,
                text="hello",
                token_count=1,
                created_at="t",
            )
            db_mod.upsert_edge(
                conn,
                edge_id="e1",
                src_id="d1",
                src_type="document",
                dst_id="c1",
                dst_type="chunk",
                edge_type="CONTAINS",
                weight=1.0,
                metadata="{}",
                created_at="t",
            )
            db_mod.delete_document(conn, "d1")

        with db_mod.get_connection(tmp_db) as conn:
            chunks = db_mod.get_chunks_for_doc(conn, "d1")
            edges = db_mod.get_edges_for_node(conn, "d1")
        assert chunks == []
        assert edges == []


# ---------------------------------------------------------------------------
# S3 mock tests
# ---------------------------------------------------------------------------

class TestS3Mock:
    @patch("hermes_bedrock_agent.graphrag.s3_reader.boto3")
    def test_list_files(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        from datetime import datetime
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "graphrag/doc.txt", "Size": 100, "LastModified": datetime(2026, 1, 1)}]}
        ]

        from hermes_bedrock_agent.graphrag.s3_reader import list_files
        results = list_files("s3-hulftchina-rd", "graphrag/")
        assert len(results) == 1
        assert results[0]["key"] == "graphrag/doc.txt"

    @patch("hermes_bedrock_agent.graphrag.s3_reader.boto3")
    def test_download_file(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.get_object.return_value = {"Body": io.BytesIO(b"hello world")}

        from hermes_bedrock_agent.graphrag.s3_reader import download_file
        data = download_file("s3-hulftchina-rd", "graphrag/test.txt")
        assert data == b"hello world"


# ---------------------------------------------------------------------------
# Bedrock embedding mock tests
# ---------------------------------------------------------------------------

class TestBedrockEmbedMock:
    @patch("hermes_bedrock_agent.graphrag.embedder.boto3")
    def test_embed_text(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        fake_vector = [0.1] * 1024
        mock_client.invoke_model.return_value = {
            "body": io.BytesIO(json.dumps({"embedding": fake_vector}).encode())
        }

        from hermes_bedrock_agent.graphrag.embedder import embed_text
        result = embed_text("test text")
        assert result.shape == (1024,)
        assert result.dtype == np.float32
