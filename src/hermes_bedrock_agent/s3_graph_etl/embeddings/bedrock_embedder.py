"""Bedrock Titan embedding provider."""
from __future__ import annotations

import json
import logging

from hermes_bedrock_agent.config import EmbeddingConfig
from hermes_bedrock_agent.s3_graph_etl.embeddings.base_embedder import BaseEmbedder

logger = logging.getLogger(__name__)


class BedrockEmbedder(BaseEmbedder):
    """Amazon Bedrock Titan Embedding client."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        if config is None:
            config = EmbeddingConfig.from_env()
        self.config = config
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
        return self._client

    @property
    def dimension(self) -> int:
        return self.config.dimension

    def embed(self, text: str) -> list[float]:
        """Embed a single text string using Bedrock Titan."""
        body = json.dumps({"inputText": text[:8192]})  # Titan limit
        response = self.client.invoke_model(
            modelId=self.config.model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed batch - Titan doesn't support native batch, so iterate."""
        return [self.embed(text) for text in texts]


class MockEmbedder(BaseEmbedder):
    """Mock embedder for dry-run testing."""

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        """Return a deterministic mock embedding."""
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        # Generate deterministic floats from hash
        values = [((b % 200) - 100) / 100.0 for b in h]
        # Pad/truncate to dimension
        result = (values * (self._dimension // len(values) + 1))[:self._dimension]
        return result

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]
