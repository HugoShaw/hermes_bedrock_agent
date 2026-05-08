"""Reusable openCypher query templates for Neptune Analytics."""
from __future__ import annotations


# --- Node operations ---

UPSERT_NODE = (
    "MERGE (n:`{label}` {{`~id`: $id}}) "
    "SET n += $props "
    "RETURN n.`~id` AS id"
)

UPSERT_EDGE = (
    "MATCH (a {{`~id`: $from_id}}), (b {{`~id`: $to_id}}) "
    "MERGE (a)-[r:`{edge_type}` {{`~id`: $edge_id}}]->(b) "
    "SET r += $props "
    "RETURN r.`~id` AS id"
)

# --- Query templates ---

ALL_RELATIONSHIPS = "MATCH (a)-[r]->(b) RETURN a.`~id` AS from_id, type(r) AS rel_type, b.`~id` AS to_id LIMIT 100"

NODES_BY_NAME = (
    "MATCH (n) WHERE n.name CONTAINS $name_pattern "
    "RETURN n.`~id` AS id, labels(n) AS labels, n.name AS name LIMIT 50"
)

ONE_HOP = (
    "MATCH (n {{`~id`: $node_id}})-[r]-(m) "
    "RETURN n.`~id` AS source, type(r) AS rel_type, m.`~id` AS target, m.name AS target_name"
)

TWO_HOP = (
    "MATCH (n {{`~id`: $node_id}})-[r1]-(m)-[r2]-(o) "
    "WHERE n <> o "
    "RETURN n.`~id` AS source, type(r1) AS rel1, m.`~id` AS mid, type(r2) AS rel2, o.`~id` AS target "
    "LIMIT 100"
)

VECTOR_TOP_K = (
    "CALL neptune.algo.vectors.topKByEmbedding($embedding, {{topK: $topK}}) "
    "YIELD node, score "
    "RETURN node, score ORDER BY score DESC"
)

GRAPHRAG_CONTEXT = (
    "CALL neptune.algo.vectors.topKByEmbedding($embedding, {{topK: $topK}}) "
    "YIELD node, score "
    "WITH node, score "
    "MATCH (node)-[r]-(neighbor) "
    "RETURN node.`~id` AS node_id, node.name AS node_name, node.text AS node_text, "
    "score, type(r) AS rel_type, neighbor.`~id` AS neighbor_id, neighbor.name AS neighbor_name "
    "ORDER BY score DESC LIMIT 50"
)
