"""Tests for embedding/ — MockEmbedder, BedrockEmbedder (mocked), batch embedding.

All tests use MockEmbedder or mocked bedrock_client. No real AWS calls.
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from hermes_bedrock_agent.embedding.embedder import (
    BaseEmbedder,
    BedrockEmbedder,
    EmbedderConfig,
    MockEmbedder,
)
from hermes_bedrock_agent.schemas.chunk import ChunkType, DocumentChunk


def _make_chunk(
    chunk_id: str = "chunk_abc123",
    document_id: str = "doc_001",
    content: str = "This is test content for embedding.",
    chunk_index: int = 0,
    source_uri: str = "s3://bucket/file.md",
    source_type: str = "markdown",
    page: int | None = None,
    section_title: str = "",
    visual_block_ids: list | None = None,
    content_hash: str = "hash_abc",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=chunk_index,
        content=content,
        source_uri=source_uri,
        source_type=source_type,
        page=page,
        section_title=section_title,
        visual_block_ids=visual_block_ids or [],
        content_hash=content_hash,
    )


# ---- MockEmbedder tests ----


class TestMockEmbedder:
    def test_embed_text_returns_correct_dimension(self):
        """Mock embedding produces vector of configured dimension."""
        config = EmbedderConfig(dimension=1024, model_id="mock")
        embedder = MockEmbedder(config)
        vector = embedder.embed_text("Hello world")

        assert len(vector) == 1024
        assert all(isinstance(v, float) for v in vector)

    def test_embed_text_custom_dimension(self):
        """Custom dimension produces correct-length vector."""
        config = EmbedderConfig(dimension=256, model_id="mock")
        embedder = MockEmbedder(config)
        vector = embedder.embed_text("Test text")

        assert len(vector) == 256

    def test_embed_text_deterministic(self):
        """Same text always produces same vector."""
        embedder = MockEmbedder()
        v1 = embedder.embed_text("Identical text input")
        v2 = embedder.embed_text("Identical text input")

        assert v1 == v2

    def test_embed_text_different_input_different_vector(self):
        """Different text produces different vectors."""
        embedder = MockEmbedder()
        v1 = embedder.embed_text("First text")
        v2 = embedder.embed_text("Second text")

        assert v1 != v2

    def test_embed_text_values_in_range(self):
        """Vector values are in [-1.0, 1.0] range."""
        embedder = MockEmbedder(EmbedderConfig(dimension=2048))
        vector = embedder.embed_text("Range test")

        assert all(-1.0 <= v <= 1.0 for v in vector)

    def test_embed_chunk_returns_chunk_embedding(self):
        """embed_chunk produces ChunkEmbedding with correct fields."""
        embedder = MockEmbedder(EmbedderConfig(dimension=512, model_id="mock-embedder"))
        chunk = _make_chunk(
            page=3,
            section_title="Methods",
            visual_block_ids=["vis_001"],
        )

        result = embedder.embed_chunk(chunk)

        assert result.chunk_id == "chunk_abc123"
        assert result.document_id == "doc_001"
        assert result.content == chunk.content
        assert len(result.embedding) == 512
        assert result.embedding_dimension == 512
        assert result.embedding_model == "mock-embedder"
        assert result.source_uri == "s3://bucket/file.md"
        assert result.source_type == "markdown"
        assert result.page == 3
        assert result.section_title == "Methods"
        assert result.visual_block_ids == ["vis_001"]
        assert result.content_hash == "hash_abc"
        assert result.embedding_time_ms is not None
        assert result.metadata["chunk_index"] == 0

    def test_embed_chunks_batch(self):
        """embed_chunks processes multiple chunks."""
        embedder = MockEmbedder(EmbedderConfig(dimension=128, batch_size=2))
        chunks = [_make_chunk(chunk_id=f"chunk_{i}", content=f"Content {i}") for i in range(5)]

        results = embedder.embed_chunks(chunks)

        assert len(results) == 5
        assert all(len(r.embedding) == 128 for r in results)
        # Verify each chunk got its own embedding
        ids = [r.chunk_id for r in results]
        assert ids == [f"chunk_{i}" for i in range(5)]

    def test_embed_chunks_stability(self):
        """Same chunks produce same embeddings on repeated calls."""
        embedder = MockEmbedder(EmbedderConfig(dimension=64))
        chunks = [_make_chunk(content="Stable content")]

        r1 = embedder.embed_chunks(chunks)
        r2 = embedder.embed_chunks(chunks)

        assert r1[0].embedding == r2[0].embedding
        assert r1[0].chunk_id == r2[0].chunk_id

    def test_embed_empty_list(self):
        """Empty input produces empty output."""
        embedder = MockEmbedder()
        results = embedder.embed_chunks([])
        assert results == []


# ---- BedrockEmbedder tests (mocked) ----


class TestBedrockEmbedder:
    def _mock_bedrock_client(self, dimension: int = 1024):
        """Create a mock bedrock client that returns fake vectors."""
        mock_client = MagicMock()

        def fake_invoke(model_id, body, **kwargs):
            # body is now a dict (not a JSON string)
            text = body.get("inputText", "")
            if isinstance(body, str):
                import json as j
                parsed = j.loads(body)
                text = parsed.get("inputText", "")
            # Deterministic fake vector
            import hashlib
            h = hashlib.sha256(text.encode()).digest()
            vector = [(b / 255.0) for b in h * (dimension // 32 + 1)][:dimension]

            # Returns parsed dict (our wrapper handles serialization)
            return {"embedding": vector}

        mock_client.invoke_model.side_effect = fake_invoke
        return mock_client

    def test_embed_text_titan(self):
        """BedrockEmbedder calls invoke_model with Titan format."""
        mock_client = self._mock_bedrock_client(1024)
        config = EmbedderConfig(model_id="amazon.titan-embed-text-v2:0", dimension=1024)
        embedder = BedrockEmbedder(config=config, bedrock_client=mock_client)

        vector = embedder.embed_text("Test input")

        assert len(vector) == 1024
        mock_client.invoke_model.assert_called_once()
        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["model_id"] == "amazon.titan-embed-text-v2:0"
        body = call_kwargs["body"]
        assert body["inputText"] == "Test input"
        assert body["dimensions"] == 1024

    def test_embed_text_cohere(self):
        """BedrockEmbedder handles Cohere model format."""
        mock_client = MagicMock()
        vector = [0.1] * 1024
        mock_client.invoke_model.return_value = {"embeddings": [vector]}

        config = EmbedderConfig(model_id="cohere.embed-multilingual-v3", dimension=1024)
        embedder = BedrockEmbedder(config=config, bedrock_client=mock_client)

        result = embedder.embed_text("Cohere test")

        assert len(result) == 1024
        call_kwargs = mock_client.invoke_model.call_args[1]
        body = call_kwargs["body"]
        assert body["texts"] == ["Cohere test"]
        assert body["input_type"] == "search_document"

    def test_embed_chunk_full_flow(self):
        """BedrockEmbedder embed_chunk produces complete ChunkEmbedding."""
        mock_client = self._mock_bedrock_client(512)
        config = EmbedderConfig(model_id="amazon.titan-embed-text-v2:0", dimension=512)
        embedder = BedrockEmbedder(config=config, bedrock_client=mock_client)

        chunk = _make_chunk(page=2, section_title="Results")
        result = embedder.embed_chunk(chunk)

        assert result.chunk_id == chunk.chunk_id
        assert result.embedding_model == "amazon.titan-embed-text-v2:0"
        assert result.embedding_dimension == 512
        assert len(result.embedding) == 512
        assert result.page == 2
        assert result.section_title == "Results"

    def test_embed_chunks_retry_on_failure(self):
        """Retry logic works on transient failures."""
        mock_client = MagicMock()
        call_count = [0]

        def failing_then_success(model_id, body, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Transient error")
            vector = [0.5] * 256
            return {"embedding": vector}

        mock_client.invoke_model.side_effect = failing_then_success

        config = EmbedderConfig(
            model_id="amazon.titan-embed-text-v2:0",
            dimension=256,
            max_retries=3,
            retry_delay=0.1,  # Fast retry for tests
        )
        embedder = BedrockEmbedder(config=config, bedrock_client=mock_client)

        chunk = _make_chunk()
        results = embedder.embed_chunks([chunk])

        assert len(results) == 1
        assert call_count[0] == 2  # 1 failure + 1 success

    def test_embed_chunks_skip_on_permanent_failure(self):
        """Permanently failing chunks are skipped (on_error='skip')."""
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = Exception("Permanent failure")

        config = EmbedderConfig(
            model_id="amazon.titan-embed-text-v2:0",
            dimension=256,
            max_retries=2,
            retry_delay=0.1,
        )
        embedder = BedrockEmbedder(config=config, bedrock_client=mock_client)

        chunk = _make_chunk()
        results = embedder.embed_chunks([chunk], on_error="skip")

        assert len(results) == 0
        assert mock_client.invoke_model.call_count == 2  # max_retries

    def test_embed_chunks_raise_on_permanent_failure(self):
        """on_error='raise' propagates exception."""
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = Exception("Fatal error")

        config = EmbedderConfig(
            model_id="amazon.titan-embed-text-v2:0",
            dimension=256,
            max_retries=1,
            retry_delay=0.1,
        )
        embedder = BedrockEmbedder(config=config, bedrock_client=mock_client)

        chunk = _make_chunk()
        with pytest.raises(Exception, match="Fatal error"):
            embedder.embed_chunks([chunk], on_error="raise")
