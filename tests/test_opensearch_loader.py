"""Tests for embedding/opensearch_loader.py — record building, mapping, bulk indexing.

All tests use mock OpenSearch client. No real OpenSearch calls.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_bedrock_agent.embedding.opensearch_loader import (
    build_bulk_records,
    build_index_mapping,
    build_opensearch_record,
    bulk_index_chunks,
    create_index_if_not_exists,
    write_opensearch_bulk_jsonl,
    _build_bulk_body,
)
from hermes_bedrock_agent.knowledge_store.jsonl_store import read_jsonl
from hermes_bedrock_agent.schemas.chunk import ChunkEmbedding, ChunkType


def _make_embedding(
    chunk_id: str = "chunk_test_001",
    document_id: str = "doc_001",
    content: str = "Embedded text content",
    embedding: list[float] | None = None,
    embedding_model: str = "amazon.titan-embed-text-v2:0",
    embedding_dimension: int = 1024,
    source_uri: str = "s3://bucket/test.md",
    source_type: str = "markdown",
    page: int | None = 1,
    section_title: str = "Introduction",
    visual_block_ids: list[str] | None = None,
    acl: list[str] | None = None,
    content_hash: str = "hash_xyz",
    metadata: dict | None = None,
) -> ChunkEmbedding:
    return ChunkEmbedding(
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        embedding=embedding or [0.1] * embedding_dimension,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        source_uri=source_uri,
        source_type=source_type,
        page=page,
        section_title=section_title,
        visual_block_ids=visual_block_ids or [],
        acl=acl or ["team-a"],
        content_hash=content_hash,
        metadata=metadata or {"chunk_index": 0},
    )


# ---- build_opensearch_record tests ----


class TestBuildOpensearchRecord:
    def test_basic_record(self):
        """Build record with all expected fields."""
        emb = _make_embedding()
        record = build_opensearch_record(emb)

        assert record["chunk_id"] == "chunk_test_001"
        assert record["document_id"] == "doc_001"
        assert record["text"] == "Embedded text content"
        assert len(record["embedding"]) == 1024
        assert record["source_uri"] == "s3://bucket/test.md"
        assert record["source_type"] == "markdown"
        assert record["page"] == 1
        assert record["section_title"] == "Introduction"
        assert record["visual_block_ids"] == []
        assert record["acl"] == ["team-a"]
        assert record["content_hash"] == "hash_xyz"
        assert record["embedding_model"] == "amazon.titan-embed-text-v2:0"

    def test_no_image_base64_in_record(self):
        """OpenSearch record never contains image_base64."""
        emb = _make_embedding()
        record = build_opensearch_record(emb)

        # Flatten all values to check no base64 leakage
        record_str = json.dumps(record)
        assert "image_base64" not in record_str

    def test_metadata_included(self):
        """Metadata dict is included in record."""
        emb = _make_embedding(metadata={"chunk_index": 5, "token_count": 120})
        record = build_opensearch_record(emb)

        assert record["metadata"]["chunk_index"] == 5
        assert record["metadata"]["token_count"] == 120

    def test_visual_block_ids_preserved(self):
        """visual_block_ids are preserved in record."""
        emb = _make_embedding(visual_block_ids=["vis_001", "vis_002"])
        record = build_opensearch_record(emb)

        assert record["visual_block_ids"] == ["vis_001", "vis_002"]

    def test_chunk_type_in_metadata(self):
        """chunk_type stored in metadata."""
        emb = _make_embedding()
        emb.chunk_type = ChunkType.VISUAL_DESCRIPTION
        record = build_opensearch_record(emb)

        assert record["metadata"]["chunk_type"] == "visual_description"


class TestBuildBulkRecords:
    def test_multiple_records(self):
        """Build bulk records from multiple embeddings."""
        embeddings = [
            _make_embedding(chunk_id=f"chunk_{i}", content=f"Content {i}")
            for i in range(3)
        ]
        records = build_bulk_records(embeddings)

        assert len(records) == 3
        assert records[0]["chunk_id"] == "chunk_0"
        assert records[2]["chunk_id"] == "chunk_2"

    def test_empty_input(self):
        """Empty list produces empty output."""
        assert build_bulk_records([]) == []


# ---- build_index_mapping tests ----


class TestBuildIndexMapping:
    def test_default_mapping(self):
        """Default mapping has correct structure."""
        mapping = build_index_mapping()

        assert mapping["settings"]["index"]["knn"] is True
        props = mapping["mappings"]["properties"]

        assert props["chunk_id"]["type"] == "keyword"
        assert props["document_id"]["type"] == "keyword"
        assert props["text"]["type"] == "text"
        assert props["embedding"]["type"] == "knn_vector"
        assert props["embedding"]["dimension"] == 1024
        assert props["source_uri"]["type"] == "keyword"
        assert props["source_type"]["type"] == "keyword"
        assert props["page"]["type"] == "integer"
        assert props["section_title"]["type"] == "text"
        assert props["acl"]["type"] == "keyword"
        assert props["content_hash"]["type"] == "keyword"
        assert props["metadata"]["type"] == "object"

    def test_custom_dimension(self):
        """Custom dimension is applied to vector field."""
        mapping = build_index_mapping(dimension=512)
        assert mapping["mappings"]["properties"]["embedding"]["dimension"] == 512

    def test_custom_vector_field(self):
        """Custom vector field name."""
        mapping = build_index_mapping(vector_field="vec")
        assert "vec" in mapping["mappings"]["properties"]
        assert mapping["mappings"]["properties"]["vec"]["type"] == "knn_vector"

    def test_custom_text_field(self):
        """Custom text field name."""
        mapping = build_index_mapping(text_field="body")
        assert "body" in mapping["mappings"]["properties"]
        assert mapping["mappings"]["properties"]["body"]["type"] == "text"

    def test_hnsw_params(self):
        """HNSW parameters are configurable."""
        mapping = build_index_mapping(ef_construction=256, m=32)
        params = mapping["mappings"]["properties"]["embedding"]["method"]["parameters"]
        assert params["ef_construction"] == 256
        assert params["m"] == 32


# ---- create_index_if_not_exists tests ----


class TestCreateIndex:
    def test_creates_when_not_exists(self):
        """Creates index when it doesn't exist."""
        mock_client = MagicMock()
        mock_client.indices.exists.return_value = False
        mock_client.indices.create.return_value = {"acknowledged": True}

        result = create_index_if_not_exists(mock_client, "test-index", dimension=512)

        assert result is True
        mock_client.indices.create.assert_called_once()
        call_kwargs = mock_client.indices.create.call_args[1]
        assert call_kwargs["index"] == "test-index"
        body = call_kwargs["body"]
        assert body["mappings"]["properties"]["embedding"]["dimension"] == 512

    def test_skips_when_exists(self):
        """Skips creation when index exists."""
        mock_client = MagicMock()
        mock_client.indices.exists.return_value = True

        result = create_index_if_not_exists(mock_client, "test-index")

        assert result is False
        mock_client.indices.create.assert_not_called()

    def test_dry_run_no_create(self):
        """Dry run checks existence but doesn't create."""
        mock_client = MagicMock()
        mock_client.indices.exists.return_value = False

        result = create_index_if_not_exists(mock_client, "test-index", dry_run=True)

        assert result is False
        mock_client.indices.create.assert_not_called()


# ---- bulk_index_chunks tests ----


class TestBulkIndexChunks:
    def test_bulk_index_success(self):
        """Bulk index sends records to OpenSearch."""
        mock_client = MagicMock()
        mock_client.bulk.return_value = {"errors": False, "items": []}

        embeddings = [_make_embedding(chunk_id=f"chunk_{i}") for i in range(3)]
        result = bulk_index_chunks(mock_client, "test-index", embeddings, batch_size=10)

        assert result["total"] == 3
        assert result["indexed"] == 3
        assert result["errors"] == 0
        assert result["dry_run"] is False
        mock_client.bulk.assert_called_once()

    def test_bulk_index_dry_run(self):
        """Dry run doesn't call OpenSearch."""
        mock_client = MagicMock()
        embeddings = [_make_embedding()]

        result = bulk_index_chunks(mock_client, "test-index", embeddings, dry_run=True)

        assert result["total"] == 1
        assert result["indexed"] == 0
        assert result["dry_run"] is True
        mock_client.bulk.assert_not_called()

    def test_bulk_index_batching(self):
        """Large sets are batched correctly."""
        mock_client = MagicMock()
        mock_client.bulk.return_value = {"errors": False, "items": []}

        embeddings = [_make_embedding(chunk_id=f"chunk_{i}") for i in range(5)]
        result = bulk_index_chunks(mock_client, "test-index", embeddings, batch_size=2)

        assert result["total"] == 5
        assert result["indexed"] == 5
        # 5 records / batch_size 2 = 3 bulk calls
        assert mock_client.bulk.call_count == 3

    def test_bulk_index_partial_errors(self):
        """Partial errors are counted correctly."""
        mock_client = MagicMock()
        mock_client.bulk.return_value = {
            "errors": True,
            "items": [
                {"index": {"_id": "chunk_0", "status": 201}},
                {"index": {"_id": "chunk_1", "error": {"reason": "mapping error"}}},
            ],
        }

        embeddings = [_make_embedding(chunk_id=f"chunk_{i}") for i in range(2)]
        result = bulk_index_chunks(mock_client, "test-index", embeddings)

        assert result["total"] == 2
        assert result["indexed"] == 1
        assert result["errors"] == 1

    def test_bulk_index_empty_input(self):
        """Empty input produces zero-result summary."""
        mock_client = MagicMock()
        result = bulk_index_chunks(mock_client, "test-index", [])

        assert result["total"] == 0
        assert result["indexed"] == 0
        mock_client.bulk.assert_not_called()


# ---- _build_bulk_body tests ----


class TestBuildBulkBody:
    def test_ndjson_format(self):
        """Bulk body is valid NDJSON with action + document lines."""
        records = [
            {"chunk_id": "c1", "text": "hello", "embedding": [0.1, 0.2]},
            {"chunk_id": "c2", "text": "world", "embedding": [0.3, 0.4]},
        ]
        body = _build_bulk_body(records, "my-index")

        lines = body.strip().split("\n")
        assert len(lines) == 4  # 2 action + 2 document

        # First action line
        action = json.loads(lines[0])
        assert action["index"]["_index"] == "my-index"
        assert action["index"]["_id"] == "c1"

        # First document line
        doc = json.loads(lines[1])
        assert doc["chunk_id"] == "c1"
        assert doc["text"] == "hello"


# ---- write_opensearch_bulk_jsonl tests ----


class TestWriteOpensearchBulkJsonl:
    def test_write_records(self, tmp_path):
        """Write bulk records to JSONL."""
        embeddings = [
            _make_embedding(chunk_id="c1", content="Hello"),
            _make_embedding(chunk_id="c2", content="World"),
        ]
        path = tmp_path / "opensearch_bulk.jsonl"
        count = write_opensearch_bulk_jsonl(embeddings, path)

        assert count == 2
        assert path.exists()

        records = read_jsonl(path)
        assert len(records) == 2
        assert records[0]["chunk_id"] == "c1"
        assert records[0]["text"] == "Hello"
        assert "image_base64" not in json.dumps(records)

    def test_write_dry_run(self, tmp_path):
        """Dry run doesn't create file."""
        embeddings = [_make_embedding()]
        path = tmp_path / "dry.jsonl"
        count = write_opensearch_bulk_jsonl(embeddings, path, dry_run=True)

        assert count == 1
        assert not path.exists()

    def test_no_image_base64(self, tmp_path):
        """image_base64 never appears in output regardless of config."""
        emb = _make_embedding()
        path = tmp_path / "no_img.jsonl"
        write_opensearch_bulk_jsonl([emb], path, persist_inline_image_base64=True)

        content = path.read_text()
        assert "image_base64" not in content

    def test_opensearch_record_fields(self, tmp_path):
        """Verify all required fields present in output."""
        emb = _make_embedding(
            visual_block_ids=["vis_a"],
            acl=["admin", "dev"],
        )
        path = tmp_path / "fields.jsonl"
        write_opensearch_bulk_jsonl([emb], path)

        records = read_jsonl(path)
        r = records[0]

        required_fields = [
            "chunk_id", "document_id", "text", "embedding",
            "source_uri", "source_type", "page", "section_title",
            "visual_block_ids", "acl", "content_hash", "embedding_model",
            "metadata",
        ]
        for field in required_fields:
            assert field in r, f"Missing field: {field}"

        assert r["visual_block_ids"] == ["vis_a"]
        assert r["acl"] == ["admin", "dev"]
        assert r["embedding_model"] == "amazon.titan-embed-text-v2:0"
