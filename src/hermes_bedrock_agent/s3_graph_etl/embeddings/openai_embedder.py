"""OpenAI embedding provider."""
from __future__ import annotations

import logging
import os

from hermes_bedrock_agent.config import EmbeddingConfig
from hermes_bedrock_agent.s3_graph_etl.embeddings.base_embedder import BaseEmbedder

logger = logging.getLogger(__name__)


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI Embedding client."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        if config is None:
            config = EmbeddingConfig.from_env()
        self.config = config
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import httpx
                self._client = httpx.Client(
                    base_url="https://api.openai.com/v1",
                    headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"},
                    timeout=60.0,
                )
            except ImportError:
                raise RuntimeError("httpx is required for OpenAI embeddings")
        return self._client

    @property
    def dimension(self) -> int:
        return self.config.dimension

    def embed(self, text: str) -> list[float]:
        """Embed a single text string using OpenAI."""
        response = self.client.post("/embeddings", json={
            "model": self.config.model_id,
            "input": text[:8191],
        })
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed batch using OpenAI batch API."""
        response = self.client.post("/embeddings", json={
            "model": self.config.model_id,
            "input": [t[:8191] for t in texts],
        })
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
