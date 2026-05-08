"""
AWS Bedrock Titan embedding client for the semantic map workflow.

Fetches dense vector embeddings from the Amazon Titan Embeddings v2 model.
Results are cached on disk (as JSON files keyed by SHA-256 hash) to avoid
redundant API calls across pipeline runs.

If the Bedrock endpoint is unreachable or boto3 is not installed, all methods
degrade gracefully and return empty lists rather than raising.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional boto3
# ---------------------------------------------------------------------------
try:
    import boto3  # type: ignore
    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore
    _BOTO3_AVAILABLE = False

# ---------------------------------------------------------------------------
# Retry / rate-limit configuration
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 1.5
_BACKOFF_MULTIPLIER = 2.0

_THROTTLE_KEYWORDS = frozenset({"throttl", "too many", "slow down", "rate"})


class EmbeddingClient:
    """Client for generating embeddings via Amazon Bedrock Titan Embeddings v2.

    Parameters
    ----------
    aws_region:
        AWS region where Bedrock is deployed (e.g. ``"us-east-1"``).
    model_id:
        Bedrock embedding model identifier.
    cache_dir:
        Directory for caching embedding vectors locally.  Pass ``None`` to
        disable caching.
    """

    def __init__(
        self,
        aws_region: str,
        model_id: str = "amazon.titan-embed-text-v2:0",
        cache_dir: Optional[str] = None,
    ) -> None:
        self.aws_region = aws_region
        self.model_id = model_id
        self.cache_dir = Path(cache_dir) if cache_dir else None

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client = None
        if _BOTO3_AVAILABLE:
            try:
                self._client = boto3.client(
                    "bedrock-runtime",
                    region_name=self.aws_region,
                )
            except Exception as exc:
                logger.warning(
                    "EmbeddingClient: failed to create Bedrock client: %s", exc
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for *text*.

        The result is fetched from the local cache when available.  On any
        error the empty list is returned and a warning is logged.

        Parameters
        ----------
        text:
            Input text to embed.  Empty strings return an empty list.

        Returns
        -------
        list[float]
            Embedding vector, or ``[]`` on failure.
        """
        if not text or not text.strip():
            return []

        key = self.cache_key(text)

        # Cache read
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        # API call
        vector = self._call_bedrock(text)
        if vector:
            self._cache_put(key, text, vector)

        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of texts.

        Each text is embedded independently (Titan does not support batching).
        Failed embeddings are returned as empty lists.

        Parameters
        ----------
        texts:
            List of input strings.

        Returns
        -------
        list[list[float]]
            One vector per input text (same order).
        """
        results: list[list[float]] = []
        for idx, text in enumerate(texts):
            vec = self.embed(text)
            if not vec:
                logger.debug(
                    "embed_batch: empty embedding for item %d (len=%d)", idx, len(text)
                )
            results.append(vec)
        return results

    def is_available(self) -> bool:
        """Return ``True`` when Bedrock is reachable.

        Uses a minimal probe invocation to verify connectivity.
        """
        if not _BOTO3_AVAILABLE or self._client is None:
            return False
        try:
            body = json.dumps({"inputText": "ping"})
            self._client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            return True
        except Exception as exc:
            logger.warning("EmbeddingClient.is_available probe failed: %s", exc)
            return False

    def cache_key(self, text: str) -> str:
        """Return the SHA-256 hex digest of *text* (used as cache filename stem).

        Parameters
        ----------
        text:
            Input text.

        Returns
        -------
        str
            64-character hex string.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_bedrock(self, text: str) -> list[float]:
        """Invoke Bedrock to get an embedding, with exponential backoff."""
        if not _BOTO3_AVAILABLE or self._client is None:
            logger.warning("EmbeddingClient: boto3 unavailable; returning empty embedding")
            return []

        body = json.dumps({"inputText": text})
        last_exc: Optional[Exception] = None
        backoff = _BASE_BACKOFF_SECONDS

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.invoke_model(
                    modelId=self.model_id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads(response["body"].read())
                embedding = response_body.get("embedding", [])
                if not embedding:
                    logger.warning(
                        "EmbeddingClient: empty 'embedding' field in response for text[:50]=%r",
                        text[:50],
                    )
                return embedding

            except Exception as exc:
                is_throttle = any(
                    kw in str(exc).lower() for kw in _THROTTLE_KEYWORDS
                )
                if is_throttle and attempt < _MAX_RETRIES:
                    logger.warning(
                        "EmbeddingClient throttled on attempt %d/%d; backing off %.1fs",
                        attempt,
                        _MAX_RETRIES,
                        backoff,
                    )
                    time.sleep(backoff)
                    backoff *= _BACKOFF_MULTIPLIER
                    last_exc = exc
                    continue

                logger.warning(
                    "EmbeddingClient: Bedrock call failed on attempt %d/%d: %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                return []

        logger.warning(
            "EmbeddingClient: all %d retries exhausted; last error: %s",
            _MAX_RETRIES,
            last_exc,
        )
        return []

    def _cache_path(self, key: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{key}.json"

    def _cache_get(self, key: str) -> Optional[list[float]]:
        path = self._cache_path(key)
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            embedding = data.get("embedding")
            if isinstance(embedding, list):
                logger.debug("EmbeddingClient: cache hit for key %s", key[:12])
                return embedding
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("EmbeddingClient: corrupt cache entry %s: %s", path, exc)
        return None

    def _cache_put(self, key: str, text: str, embedding: list[float]) -> None:
        path = self._cache_path(key)
        if path is None:
            return
        try:
            payload = {"text_hash": key, "embedding": embedding}
            path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            logger.debug("EmbeddingClient: cached embedding for key %s", key[:12])
        except OSError as exc:
            logger.warning("EmbeddingClient: could not write cache %s: %s", path, exc)
