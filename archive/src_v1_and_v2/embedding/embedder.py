"""Embedding layer — converts DocumentChunks to ChunkEmbeddings.

Provides:
- BedrockEmbedder: calls Bedrock Titan/Cohere via clients/bedrock_client.py
- MockEmbedder: deterministic fake vectors for testing
- embed_text(): single text → vector
- embed_chunk(): single DocumentChunk → ChunkEmbedding
- embed_chunks(): batch DocumentChunks → ChunkEmbeddings with retry

Business logic lives HERE, not in clients/bedrock_client.py.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.chunk import ChunkEmbedding, DocumentChunk
from hermes_bedrock_agent.utils.hashing import content_hash

logger = get_logger(__name__)


class EmbedderConfig(BaseModel):
    """Configuration for embedder."""

    model_id: str = Field(default="amazon.titan-embed-text-v2:0")
    dimension: int = Field(default=1024, ge=1)
    batch_size: int = Field(default=25, ge=1)
    max_retries: int = Field(default=3, ge=1)
    retry_delay: float = Field(default=1.0, ge=0.1)


class BaseEmbedder(ABC):
    """Abstract base class for all embedders."""

    def __init__(self, config: Optional[EmbedderConfig] = None):
        self.config = config or EmbedderConfig()

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string, return vector."""
        ...

    def embed_chunk(self, chunk: DocumentChunk) -> ChunkEmbedding:
        """Embed a single DocumentChunk → ChunkEmbedding."""
        start_ms = int(time.time() * 1000)
        vector = self.embed_text(chunk.content)
        elapsed_ms = int(time.time() * 1000) - start_ms

        return ChunkEmbedding(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            content=chunk.content,
            embedding=vector,
            embedding_model=self.config.model_id,
            embedding_dimension=self.config.dimension,
            embedding_time_ms=elapsed_ms,
            content_hash=chunk.content_hash or content_hash(chunk.content),
            source_uri=chunk.source_uri,
            source_type=chunk.source_type,
            chunk_type=chunk.chunk_type,
            section_title=chunk.section_title,
            page=chunk.page,
            visual_block_ids=chunk.visual_block_ids,
            language=chunk.language,
            acl=chunk.acl,
            metadata={
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
            },
        )

    def embed_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        on_error: str = "skip",
    ) -> list[ChunkEmbedding]:
        """Embed a list of chunks in batches with retry.

        Args:
            chunks: List of DocumentChunks to embed.
            on_error: 'skip' (default) to skip failed chunks, 'raise' to propagate.

        Returns:
            List of ChunkEmbeddings (may be shorter than input if on_error='skip').
        """
        results: list[ChunkEmbedding] = []
        batch_size = self.config.batch_size

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batch_results = self._embed_batch_with_retry(batch, on_error=on_error)
            results.extend(batch_results)

            if i + batch_size < len(chunks):
                logger.debug(
                    f"Embedded batch {i // batch_size + 1}, "
                    f"total so far: {len(results)}/{len(chunks)}"
                )

        logger.info(
            f"Embedding complete: {len(results)}/{len(chunks)} chunks embedded "
            f"(model={self.config.model_id}, dim={self.config.dimension})"
        )
        return results

    def _embed_batch_with_retry(
        self,
        batch: list[DocumentChunk],
        *,
        on_error: str = "skip",
    ) -> list[ChunkEmbedding]:
        """Embed a single batch with retry logic."""
        results: list[ChunkEmbedding] = []

        for chunk in batch:
            last_error: Optional[Exception] = None
            for attempt in range(self.config.max_retries):
                try:
                    embedding = self.embed_chunk(chunk)
                    results.append(embedding)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < self.config.max_retries - 1:
                        delay = self.config.retry_delay * (2**attempt)
                        logger.warning(
                            f"Embed retry {attempt + 1}/{self.config.max_retries} "
                            f"for chunk {chunk.chunk_id}: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)

            if last_error is not None:
                if on_error == "raise":
                    raise last_error
                logger.error(
                    f"Failed to embed chunk {chunk.chunk_id} after "
                    f"{self.config.max_retries} attempts: {last_error}"
                )

        return results


class BedrockEmbedder(BaseEmbedder):
    """Embedder using AWS Bedrock Titan/Cohere models.

    Calls bedrock_client.invoke_model() for embedding.
    Supports injection of mock bedrock_client for testing.
    """

    def __init__(
        self,
        config: Optional[EmbedderConfig] = None,
        bedrock_client=None,
    ):
        super().__init__(config)
        self._bedrock_client = bedrock_client

    @property
    def bedrock_client(self):
        """Lazy-load bedrock client."""
        if self._bedrock_client is None:
            from hermes_bedrock_agent.clients.bedrock_client import get_bedrock_client

            self._bedrock_client = get_bedrock_client()
        return self._bedrock_client

    def embed_text(self, text: str) -> list[float]:
        """Call Bedrock to embed text.

        Uses invoke_model with the embedding model.
        Titan V2 expects: {"inputText": "...", "dimensions": N}
        Returns: {"embedding": [...]}
        """
        model_id = self.config.model_id

        # Build request body based on model type
        if "titan" in model_id.lower():
            body = {
                "inputText": text,
                "dimensions": self.config.dimension,
            }
        elif "cohere" in model_id.lower():
            body = {
                "texts": [text],
                "input_type": "search_document",
            }
        else:
            # Generic fallback
            body = {"inputText": text}

        response_body = self.bedrock_client.invoke_model(
            model_id=model_id,
            body=body,
            content_type="application/json",
            accept="application/json",
        )

        # Parse response based on model type
        if "titan" in model_id.lower():
            vector = response_body["embedding"]
        elif "cohere" in model_id.lower():
            vector = response_body["embeddings"][0]
        else:
            vector = response_body.get("embedding", response_body.get("embeddings", [[]])[0])

        if len(vector) != self.config.dimension:
            logger.warning(
                f"Dimension mismatch: expected {self.config.dimension}, "
                f"got {len(vector)} from {model_id}"
            )

        return vector


class MockEmbedder(BaseEmbedder):
    """Deterministic mock embedder for testing.

    Generates stable vectors from content hash — same text always produces
    the same vector. No AWS calls made.
    """

    def __init__(self, config: Optional[EmbedderConfig] = None):
        super().__init__(config or EmbedderConfig(model_id="mock-embedder"))

    def embed_text(self, text: str) -> list[float]:
        """Generate a deterministic fake vector from text content.

        Uses SHA-256 hash bytes to seed vector values.
        Same text → same vector (stable for testing).
        """
        # Hash the text to get deterministic bytes
        h = hashlib.sha256(text.encode("utf-8")).digest()

        # Extend hash to fill the required dimension
        dimension = self.config.dimension
        vector: list[float] = []

        # Use repeated hashing to fill all dimensions
        seed = h
        while len(vector) < dimension:
            for byte in seed:
                if len(vector) >= dimension:
                    break
                # Normalize byte to [-1.0, 1.0] range
                vector.append((byte / 127.5) - 1.0)
            # Re-hash for more bytes if needed
            seed = hashlib.sha256(seed).digest()

        return vector[:dimension]
