"""Neptune Analytics openCypher client for graph read/write operations."""
from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.config import NeptuneConfig

logger = logging.getLogger(__name__)


class NeptuneClient:
    """Client for Neptune Analytics openCypher queries."""

    def __init__(self, config: NeptuneConfig | None = None) -> None:
        if config is None:
            config = NeptuneConfig.from_env()
        self.config = config
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client("neptune-graph", region_name=self.config.region)
        return self._client

    @property
    def graph_id(self) -> str:
        if not self.config.graph_id:
            raise RuntimeError("NEPTUNE_GRAPH_ID is not configured")
        return self.config.graph_id

    def execute_query(self, cypher: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an openCypher query and return results."""
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
        except (ClientError, BotoCoreError) as exc:
            logger.error("Neptune query failed: %s", exc)
            raise RuntimeError(f"Neptune query failed: {exc}") from exc

    def upsert_node(
        self,
        node_id: str,
        label: str,
        properties: dict[str, Any],
    ) -> bool:
        """Upsert a node with MERGE + SET."""
        # Neptune Analytics: use ~id for node identity
        props = {k: v for k, v in properties.items() if k != "embedding"}
        cypher = (
            f"MERGE (n:`{label}` {{`~id`: $id}}) "
            "SET n += $props "
            "RETURN n.`~id` AS id"
        )
        try:
            self.execute_query(cypher, {"id": node_id, "props": props})
            # Handle embedding separately if present
            if "embedding" in properties:
                self._set_embedding(node_id, label, properties["embedding"])
            return True
        except Exception as exc:
            logger.error("Failed to upsert node %s: %s", node_id, exc)
            return False

    def upsert_edge(
        self,
        edge_id: str,
        from_id: str,
        to_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Upsert an edge between two nodes."""
        props = properties or {}
        cypher = (
            "MATCH (a {`~id`: $from_id}), (b {`~id`: $to_id}) "
            f"MERGE (a)-[r:`{edge_type}` {{`~id`: $edge_id}}]->(b) "
            "SET r += $props "
            "RETURN r.`~id` AS id"
        )
        try:
            self.execute_query(cypher, {
                "from_id": from_id,
                "to_id": to_id,
                "edge_id": edge_id,
                "props": props,
            })
            return True
        except Exception as exc:
            logger.error("Failed to upsert edge %s: %s", edge_id, exc)
            return False

    def _set_embedding(self, node_id: str, label: str, embedding: list[float]) -> None:
        """Set embedding vector property on a node."""
        cypher = (
            f"MATCH (n:`{label}` {{`~id`: $id}}) "
            "CALL neptune.algo.vectors.upsert(n, $embedding) "
            "RETURN n.`~id` AS id"
        )
        self.execute_query(cypher, {"id": node_id, "embedding": embedding})

    def vector_search(self, query_embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """Perform vector similarity search."""
        cypher = (
            "CALL neptune.algo.vectors.topKByEmbedding($embedding, {topK: $topK}) "
            "YIELD node, score "
            "RETURN node, score ORDER BY score DESC"
        )
        try:
            result = self.execute_query(cypher, {"embedding": query_embedding, "topK": top_k})
            return result.get("results", [])
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)
            return []

    def is_available(self) -> bool:
        """Check if Neptune is configured and reachable."""
        if not self.config.is_configured:
            return False
        try:
            self.execute_query("RETURN 1 AS ping")
            return True
        except Exception:
            return False
