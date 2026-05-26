"""Optional Amazon Neptune Analytics vector store integration for GraphRAG.

All public functions are no-ops (return ``None``) when
``NEPTUNE_ANALYTICS_GRAPH_ID`` is unset or the boto3 neptune-graph client is
unavailable.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np


def _graph_id() -> str | None:
    return os.getenv("NEPTUNE_ANALYTICS_GRAPH_ID") or None


def _client(region: str = "ap-northeast-1") -> Any | None:
    graph_id = _graph_id()
    if not graph_id:
        return None
    try:
        import boto3
        return boto3.client("neptune-graph", region_name=region)
    except Exception:
        return None


def upsert_vector(
    node_id: str,
    embedding: np.ndarray,
    properties: dict[str, Any],
    region: str = "ap-northeast-1",
) -> bool:
    """Upsert a node with its embedding vector into Neptune Analytics.

    Returns ``True`` on success, ``False`` if Neptune is not configured or
    the call fails.
    """
    graph_id = _graph_id()
    if not graph_id:
        return False

    client = _client(region)
    if client is None:
        return False

    try:
        vector_list = embedding.tolist()
        props = {**properties, "~id": node_id, "embedding": vector_list}
        client.execute_query(
            graphIdentifier=graph_id,
            queryString=(
                "MERGE (n {`~id`: $id}) "
                "SET n += $props "
                "RETURN n"
            ),
            parameters={"id": node_id, "props": props},
            language="OPEN_CYPHER",
        )
        return True
    except Exception:
        return False


def vector_search(
    query_embedding: np.ndarray,
    top_k: int = 5,
    region: str = "ap-northeast-1",
) -> list[dict[str, Any]]:
    """Perform vector similarity search in Neptune Analytics.

    Returns a list of result dicts, or an empty list if Neptune is not
    configured or the call fails.
    """
    graph_id = _graph_id()
    if not graph_id:
        return []

    client = _client(region)
    if client is None:
        return []

    try:
        vector_list = query_embedding.tolist()
        response = client.execute_query(
            graphIdentifier=graph_id,
            queryString=(
                "CALL neptune.algo.vectors.topKByEmbedding($embedding, {topK: $topK}) "
                "YIELD node, score "
                "RETURN node, score ORDER BY score DESC"
            ),
            parameters={"embedding": vector_list, "topK": top_k},
            language="OPEN_CYPHER",
        )
        results = []
        for row in response.get("results", []):
            results.append({"node": row.get("node"), "score": row.get("score")})
        return results
    except Exception:
        return []


def is_available() -> bool:
    """Return True if Neptune Analytics is configured and accessible."""
    return _graph_id() is not None and _client() is not None
