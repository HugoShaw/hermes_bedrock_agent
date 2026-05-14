"""Low-level Neptune Analytics openCypher client.

Handles connection, query execution, and payload parsing.
Does NOT contain graph schema logic, entity normalization, or business rules.

Migrated from: src/hermes_bedrock_agent/graph/neptune_client.py
(original preserved until cleanup phase)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.configs.settings import NeptuneSettings, get_settings

logger = get_logger(__name__)


class NeptuneClient:
    """Low-level client for Neptune Analytics openCypher queries.

    Provides:
    - execute_query: Raw openCypher execution
    - execute_batch: Multiple queries in sequence
    - Health check (ping)

    Higher-level graph operations (upsert_node, upsert_edge, vector_search)
    belong in the graph/ layer which composes on top of this client.
    """

    def __init__(
        self,
        graph_id: Optional[str] = None,
        region: Optional[str] = None,
        boto_client: Optional[Any] = None,
    ) -> None:
        """Initialize Neptune client.

        Args:
            graph_id: Neptune Analytics graph identifier. If None, read from settings.
            region: AWS region. If None, read from settings.
            boto_client: Optional pre-built boto3 client (for testing/mocking).
        """
        settings = get_settings().neptune
        self._graph_id = graph_id or settings.graph_id
        self._region = region or settings.region
        self._provided_client = boto_client
        self._client: Optional[Any] = boto_client

    @property
    def client(self) -> Any:
        """Lazily create boto3 neptune-graph client."""
        if self._client is None:
            self._client = boto3.client("neptune-graph", region_name=self._region)
        return self._client

    @property
    def graph_id(self) -> str:
        """Get the graph identifier, raising if not configured."""
        if not self._graph_id:
            raise NeptuneClientError(
                "NEPTUNE_GRAPH_ID is not configured. "
                "Set it in .env or pass graph_id to constructor.",
                code="NotConfigured",
            )
        return self._graph_id

    @property
    def is_configured(self) -> bool:
        """Check if graph_id is set."""
        return bool(self._graph_id)

    def execute_query(
        self,
        cypher: str,
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute an openCypher query and return parsed results.

        Args:
            cypher: openCypher query string.
            parameters: Optional query parameters dict.

        Returns:
            Parsed JSON response from Neptune.

        Raises:
            NeptuneClientError: On query execution failure.
        """
        try:
            params = parameters or {}
            response = self.client.execute_query(
                graphIdentifier=self.graph_id,
                queryString=cypher,
                parameters=params,
                language="OPEN_CYPHER",
            )
            # Neptune returns payload as streaming body
            payload = response.get("payload")
            if payload:
                body = payload.read()
                return json.loads(body)
            return {}
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(exc))
            logger.error("Neptune query failed [%s]: %s", code, message)
            raise NeptuneClientError(
                f"Neptune query failed [{code}]: {message}", code=code
            ) from exc
        except BotoCoreError as exc:
            logger.error("Neptune SDK error: %s", exc)
            raise NeptuneClientError(f"AWS SDK error: {exc}") from exc

    def execute_batch(
        self,
        queries: list[tuple[str, Optional[dict[str, Any]]]],
        stop_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        """Execute multiple openCypher queries sequentially.

        Args:
            queries: List of (cypher_string, parameters) tuples.
            stop_on_error: If True, stop on first error. If False, continue.

        Returns:
            List of results (one per query). Failed queries return {"error": ...}.
        """
        results: list[dict[str, Any]] = []
        for cypher, params in queries:
            try:
                result = self.execute_query(cypher, params)
                results.append(result)
            except NeptuneClientError as exc:
                if stop_on_error:
                    raise
                results.append({"error": str(exc), "query": cypher})
                logger.warning("Batch query failed (continuing): %s", exc)
        return results

    def ping(self) -> bool:
        """Check if Neptune is configured and reachable.

        Returns:
            True if a simple query succeeds.
        """
        if not self.is_configured:
            return False
        try:
            result = self.execute_query("RETURN 1 AS ping")
            return bool(result)
        except Exception:
            return False

    def get_graph_statistics(self) -> dict[str, Any]:
        """Get basic graph statistics (node/edge counts).

        Returns:
            Dict with node_count, edge_count, label_counts.
        """
        try:
            node_count_result = self.execute_query(
                "MATCH (n) RETURN count(n) AS node_count"
            )
            edge_count_result = self.execute_query(
                "MATCH ()-[r]->() RETURN count(r) AS edge_count"
            )
            return {
                "node_count": node_count_result.get("results", [{}])[0].get("node_count", 0),
                "edge_count": edge_count_result.get("results", [{}])[0].get("edge_count", 0),
            }
        except NeptuneClientError:
            return {"node_count": -1, "edge_count": -1, "error": "Query failed"}


class NeptuneClientError(Exception):
    """Raised when a Neptune API call fails."""

    def __init__(self, message: str, code: str = "Unknown") -> None:
        super().__init__(message)
        self.code = code
