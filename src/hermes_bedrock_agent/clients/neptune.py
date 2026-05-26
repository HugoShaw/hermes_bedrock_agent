"""Neptune Analytics openCypher client with SigV4."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class NeptuneClientError(Exception):
    def __init__(self, message: str, code: str = "Unknown") -> None:
        super().__init__(message)
        self.code = code


class NeptuneClient:
    """Neptune Analytics openCypher client."""

    def __init__(
        self,
        graph_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        self._graph_id = graph_id or os.getenv("NEPTUNE_GRAPH_ID", "")
        self._region = region or os.getenv("AWS_REGION", "ap-northeast-1")
        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client("neptune-graph", region_name=self._region)
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(self._graph_id)

    def execute_query(
        self,
        cypher: str,
        parameters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not self._graph_id:
            raise NeptuneClientError("NEPTUNE_GRAPH_ID is not configured.", code="NotConfigured")
        try:
            response = self.client.execute_query(
                graphIdentifier=self._graph_id,
                queryString=cypher,
                parameters=parameters or {},
                language="OPEN_CYPHER",
            )
            payload = response.get("payload")
            if payload:
                return json.loads(payload.read())
            return {}
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(exc))
            logger.error("Neptune query failed [%s]: %s", code, message)
            raise NeptuneClientError(f"Neptune [{code}]: {message}", code=code) from exc
        except BotoCoreError as exc:
            raise NeptuneClientError(f"AWS SDK error: {exc}") from exc

    def ping(self) -> bool:
        if not self.is_configured:
            return False
        try:
            return bool(self.execute_query("RETURN 1 AS ping"))
        except Exception:
            return False

    def get_graph_statistics(self) -> dict[str, Any]:
        try:
            nc = self.execute_query("MATCH (n) RETURN count(n) AS node_count")
            ec = self.execute_query("MATCH ()-[r]->() RETURN count(r) AS edge_count")
            return {
                "node_count": nc.get("results", [{}])[0].get("node_count", 0),
                "edge_count": ec.get("results", [{}])[0].get("edge_count", 0),
            }
        except NeptuneClientError:
            return {"node_count": -1, "edge_count": -1, "error": "Query failed"}
