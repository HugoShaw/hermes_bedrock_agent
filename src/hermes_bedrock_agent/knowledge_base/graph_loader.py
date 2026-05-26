"""Load extracted graph entities into Neptune Analytics via openCypher MERGE."""

from __future__ import annotations

import logging
from typing import Optional

from ..clients.neptune import NeptuneClient, NeptuneClientError
from ..config import Config, config as _default_config
from .graph_extractor import extract_entities
from .schemas import Chunk, GraphEdge, GraphNode

logger = logging.getLogger(__name__)


def _props_to_cypher_set(props: dict, prefix: str = "n") -> str:
    parts = []
    for k, v in props.items():
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{prefix}.{k} = '{escaped}'")
        elif isinstance(v, (int, float)):
            parts.append(f"{prefix}.{k} = {v}")
        elif isinstance(v, list):
            inner = ", ".join(f"'{str(x)}'" for x in v)
            parts.append(f"{prefix}.{k} = [{inner}]")
    return ", ".join(parts) if parts else ""


def _merge_node_cypher(node: GraphNode) -> str:
    props = dict(node.properties)
    props["evidence_pdf_s3_path"] = node.evidence_pdf_s3_path
    props["name"] = node.name
    set_parts = _props_to_cypher_set(props, "n")
    name_esc = node.name.replace("\\", "\\\\").replace("'", "\\'")
    cypher = (
        f"MERGE (n:{node.label} {{node_id: '{node.node_id}'}}) "
        f"ON CREATE SET n.name = '{name_esc}' "
        f"ON MATCH SET n.name = '{name_esc}' "
    )
    if set_parts:
        cypher += f"SET {set_parts}"
    return cypher


def _merge_edge_cypher(edge: GraphEdge) -> str:
    props = dict(edge.properties)
    props["evidence_pdf_s3_path"] = edge.evidence_pdf_s3_path
    set_parts = _props_to_cypher_set(props, "r")
    cypher = (
        f"MATCH (a {{node_id: '{edge.from_id}'}}), (b {{node_id: '{edge.to_id}'}}) "
        f"MERGE (a)-[r:{edge.relationship}]->(b) "
    )
    if set_parts:
        cypher += f"SET {set_parts}"
    return cypher


def build_graph(
    chunks: list[Chunk],
    cfg: Optional[Config] = None,
    graph_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Extract entities from all chunks and load into Neptune.

    Returns dict with node_count, edge_count, error_count.
    """
    cfg = cfg or _default_config
    client = NeptuneClient(graph_id=graph_id or cfg.neptune_graph_id)

    if not client.is_configured:
        logger.warning("Neptune graph ID not configured — skipping graph build")
        return {"node_count": 0, "edge_count": 0, "error_count": 0}

    all_nodes: dict[str, GraphNode] = {}
    all_edges: list[GraphEdge] = []

    for chunk in chunks:
        nodes, edges = extract_entities(chunk)
        for node in nodes:
            if node.node_id not in all_nodes or not all_nodes[node.node_id].evidence_pdf_s3_path:
                all_nodes[node.node_id] = node
        all_edges.extend(edges)

    node_list = list(all_nodes.values())
    logger.info("Graph: %d unique nodes, %d edges", len(node_list), len(all_edges))

    if dry_run:
        logger.info("DRY RUN: would write %d nodes, %d edges", len(node_list), len(all_edges))
        return {"node_count": len(node_list), "edge_count": len(all_edges), "error_count": 0}

    node_count = edge_count = error_count = 0

    for node in node_list:
        try:
            client.execute_query(_merge_node_cypher(node))
            node_count += 1
        except Exception as exc:
            logger.warning("Node upsert failed [%s]: %s", node.node_id, exc)
            error_count += 1

    logger.info("Nodes: %d / %d", node_count, len(node_list))

    for edge in all_edges:
        try:
            client.execute_query(_merge_edge_cypher(edge))
            edge_count += 1
        except Exception as exc:
            logger.debug("Edge upsert failed [%s->%s]: %s", edge.from_id, edge.to_id, exc)
            error_count += 1

    logger.info("Edges: %d / %d (errors: %d)", edge_count, len(all_edges), error_count)
    return {"node_count": node_count, "edge_count": edge_count, "error_count": error_count}
