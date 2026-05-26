"""Low-level Bedrock Knowledge Base retrieval client.

Handles the Bedrock Agent Runtime Retrieve API.
Does NOT contain retrieval ranking, fusion, or context building logic.

Migrated from: src/hermes_bedrock_agent/kb/bedrock_kb_client.py
(original preserved until cleanup phase)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.configs.settings import get_settings

logger = get_logger(__name__)


@dataclass
class KBRetrievalResult:
    """A single chunk returned by Bedrock Knowledge Base Retrieve API."""

    text: str
    score: float
    metadata: dict[str, Any]
    location: dict[str, Any]
    kb_id: str
    kb_label: str = ""

    @property
    def display_source(self) -> str:
        return self.kb_label if self.kb_label else self.kb_id

    @property
    def source_uri(self) -> str:
        """Extract source URI from location metadata."""
        s3_loc = self.location.get("s3Location", {})
        return s3_loc.get("uri", "")


class BedrockKBClient:
    """Low-level client for Bedrock Knowledge Base Retrieve API.

    Supports querying single or multiple Knowledge Bases.
    Does NOT apply ranking logic — returns raw scored results.
    """

    def __init__(
        self,
        region: Optional[str] = None,
        boto_client: Optional[Any] = None,
    ) -> None:
        """Initialize Bedrock KB client.

        Args:
            region: AWS region. If None, read from settings.
            boto_client: Optional pre-built boto3 client (for testing/mocking).
        """
        self._region = region or get_settings().aws.region
        self._provided_client = boto_client
        self._client: Optional[Any] = boto_client

    @property
    def client(self) -> Any:
        """Lazily create boto3 bedrock-agent-runtime client."""
        if self._client is None:
            self._client = boto3.client("bedrock-agent-runtime", region_name=self._region)
        return self._client

    def retrieve(
        self,
        kb_id: str,
        query: str,
        number_of_results: int = 5,
        kb_label: str = "",
    ) -> list[KBRetrievalResult]:
        """Retrieve chunks from a single Knowledge Base.

        Args:
            kb_id: Knowledge Base ID.
            query: Natural language query.
            number_of_results: Max results to return (1-20).
            kb_label: Optional label for display purposes.

        Returns:
            List of KBRetrievalResult with text, score, metadata.

        Raises:
            BedrockKBClientError: On API failure.
            ValueError: On invalid parameters.
        """
        if not query.strip():
            raise ValueError("Query must not be empty.")
        if number_of_results < 1 or number_of_results > 20:
            raise ValueError("number_of_results must be between 1 and 20.")

        try:
            response = self.client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": number_of_results,
                    }
                },
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(exc))
            logger.error("Bedrock KB retrieve failed [%s]: %s (kb=%s)", code, message, kb_id)
            raise BedrockKBClientError(
                f"KB retrieve [{code}]: {message}", code=code
            ) from exc
        except BotoCoreError as exc:
            logger.error("Bedrock KB SDK error: %s", exc)
            raise BedrockKBClientError(f"AWS SDK error: {exc}") from exc

        results: list[KBRetrievalResult] = []
        for row in response.get("retrievalResults", []):
            content = row.get("content", {})
            results.append(
                KBRetrievalResult(
                    text=content.get("text", ""),
                    score=float(row.get("score") or 0.0),
                    metadata=row.get("metadata", {}),
                    location=row.get("location", {}),
                    kb_id=kb_id,
                    kb_label=kb_label,
                )
            )
        return results

    def retrieve_multi(
        self,
        kb_ids: list[tuple[str, str]],
        query: str,
        number_of_results: int = 5,
    ) -> dict[str, list[KBRetrievalResult]]:
        """Retrieve from multiple Knowledge Bases sequentially.

        Args:
            kb_ids: List of (kb_id, kb_label) tuples.
            query: Natural language query.
            number_of_results: Max results per KB.

        Returns:
            Dict mapping kb_id to list of results.
            Failed KBs have empty lists (errors logged, not raised).
        """
        all_results: dict[str, list[KBRetrievalResult]] = {}
        for kb_id, kb_label in kb_ids:
            try:
                results = self.retrieve(kb_id, query, number_of_results, kb_label)
                all_results[kb_id] = results
            except BedrockKBClientError as exc:
                logger.warning("KB %s (%s) failed: %s", kb_id, kb_label, exc)
                all_results[kb_id] = []
        return all_results

    def ping(self, kb_id: str) -> bool:
        """Check if a Knowledge Base is accessible.

        Args:
            kb_id: Knowledge Base ID to test.

        Returns:
            True if a minimal retrieve succeeds.
        """
        try:
            self.retrieve(kb_id, "test", number_of_results=1)
            return True
        except Exception:
            return False


class BedrockKBClientError(Exception):
    """Raised when a Bedrock KB API call fails."""

    def __init__(self, message: str, code: str = "Unknown") -> None:
        super().__init__(message)
        self.code = code
