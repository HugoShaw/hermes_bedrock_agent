"""Load extracted graph entities into Neptune Analytics via openCypher MERGE.

Supports two modes:
  1. Legacy keyword-based: extract_entities() per chunk (fast, no LLM cost)
  2. LLM-based two-pass: Business Semantic Graph + Implementation Graph
"""

from __future__ import annotations

import logging
from typing import Optional

from ..clients.neptune import NeptuneClient, NeptuneClientError
from ..config import Config, config as _default_config
from .graph_extractor import (
    extract_business_graph,
    extract_entities,
    extract_implementation_graph,
)
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
            # Neptune doesn't support arrays; join as pipe-separated string
            joined = "|".join(str(x).replace("'", "\\'") for x in v)
            parts.append(f"{prefix}.{k} = '{joined}'")
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
    from_esc = edge.from_id.replace("'", "\\'")
    to_esc = edge.to_id.replace("'", "\\'")
    cypher = (
        f"MATCH (a {{node_id: '{from_esc}'}}), (b {{node_id: '{to_esc}'}}) "
        f"MERGE (a)-[r:{edge.relationship}]->(b) "
    )
    if set_parts:
        cypher += f"SET {set_parts}"
    return cypher


def _load_nodes_edges(
    client: NeptuneClient,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    layer_name: str,
) -> dict[str, int]:
    """Load a set of nodes and edges into Neptune."""
    node_count = edge_count = error_count = 0

    # Deduplicate nodes by node_id
    unique_nodes: dict[str, GraphNode] = {}
    for node in nodes:
        if node.node_id not in unique_nodes:
            unique_nodes[node.node_id] = node

    for node in unique_nodes.values():
        try:
            client.execute_query(_merge_node_cypher(node))
            node_count += 1
        except Exception as exc:
            logger.warning("[%s] Node upsert failed [%s]: %s", layer_name, node.node_id[:50], exc)
            error_count += 1

    logger.info("[%s] Nodes: %d / %d", layer_name, node_count, len(unique_nodes))

    for edge in edges:
        try:
            client.execute_query(_merge_edge_cypher(edge))
            edge_count += 1
        except Exception as exc:
            logger.debug("[%s] Edge upsert failed [%s->%s]: %s", layer_name, edge.from_id[:30], edge.to_id[:30], exc)
            error_count += 1

    logger.info("[%s] Edges: %d / %d (errors: %d)", layer_name, edge_count, len(edges), error_count)
    return {"node_count": node_count, "edge_count": edge_count, "error_count": error_count}


def build_graph(
    chunks: list[Chunk],
    cfg: Optional[Config] = None,
    graph_id: Optional[str] = None,
    dry_run: bool = False,
    use_llm: bool = False,
    delay_seconds: float = 3.0,
) -> dict[str, int]:
    """Extract entities from all chunks and load into Neptune.

    Args:
        chunks: Parsed markdown chunks with metadata.
        cfg: Configuration.
        graph_id: Override Neptune graph ID.
        dry_run: Extract but don't write to Neptune.
        use_llm: Use Claude Sonnet LLM for extraction (True) or keyword rules (False).
        delay_seconds: Delay between LLM calls (only when use_llm=True).

    Returns dict with node_count, edge_count, error_count, and per-layer stats.
    """
    cfg = cfg or _default_config
    client = NeptuneClient(graph_id=graph_id or cfg.neptune_graph_id)

    if not client.is_configured:
        logger.warning("Neptune graph ID not configured — skipping graph build")
        return {"node_count": 0, "edge_count": 0, "error_count": 0}

    if use_llm:
        return _build_graph_llm(chunks, client, cfg, dry_run, delay_seconds)
    else:
        return _build_graph_keyword(chunks, client, dry_run)


def _build_graph_keyword(
    chunks: list[Chunk],
    client: NeptuneClient,
    dry_run: bool,
) -> dict[str, int]:
    """Legacy keyword-based extraction — fast, no LLM cost."""
    all_nodes: dict[str, GraphNode] = {}
    all_edges: list[GraphEdge] = []

    for chunk in chunks:
        nodes, edges = extract_entities(chunk)
        for node in nodes:
            if node.node_id not in all_nodes or not all_nodes[node.node_id].evidence_pdf_s3_path:
                all_nodes[node.node_id] = node
        all_edges.extend(edges)

    node_list = list(all_nodes.values())
    logger.info("Graph (keyword): %d unique nodes, %d edges", len(node_list), len(all_edges))

    if dry_run:
        logger.info("DRY RUN: would write %d nodes, %d edges", len(node_list), len(all_edges))
        return {"node_count": len(node_list), "edge_count": len(all_edges), "error_count": 0}

    return _load_nodes_edges(client, node_list, all_edges, "keyword")


def _build_graph_llm(
    chunks: list[Chunk],
    client: NeptuneClient,
    cfg: Config,
    dry_run: bool,
    delay_seconds: float,
) -> dict[str, int]:
    """Two-pass LLM extraction: Business + Implementation graphs."""
    logger.info("=== Pass 1: Business Semantic Graph extraction ===")
    biz_nodes, biz_edges = extract_business_graph(chunks, cfg=cfg, delay_seconds=delay_seconds)

    logger.info("=== Pass 2: Implementation / Evidence Graph extraction ===")
    impl_nodes, impl_edges = extract_implementation_graph(chunks, cfg=cfg, delay_seconds=delay_seconds)

    total_nodes = len(biz_nodes) + len(impl_nodes)
    total_edges = len(biz_edges) + len(impl_edges)
    logger.info(
        "Total extracted: %d nodes (%d biz + %d impl), %d edges (%d biz + %d impl)",
        total_nodes, len(biz_nodes), len(impl_nodes),
        total_edges, len(biz_edges), len(impl_edges),
    )

    if dry_run:
        logger.info("DRY RUN: would write %d nodes, %d edges", total_nodes, total_edges)
        return {
            "node_count": total_nodes, "edge_count": total_edges, "error_count": 0,
            "business_nodes": len(biz_nodes), "business_edges": len(biz_edges),
            "implementation_nodes": len(impl_nodes), "implementation_edges": len(impl_edges),
        }

    logger.info("Loading Business Semantic Graph into Neptune...")
    biz_stats = _load_nodes_edges(client, biz_nodes, biz_edges, "business")

    logger.info("Loading Implementation Graph into Neptune...")
    impl_stats = _load_nodes_edges(client, impl_nodes, impl_edges, "implementation")

    return {
        "node_count": biz_stats["node_count"] + impl_stats["node_count"],
        "edge_count": biz_stats["edge_count"] + impl_stats["edge_count"],
        "error_count": biz_stats["error_count"] + impl_stats["error_count"],
        "business_nodes": biz_stats["node_count"],
        "business_edges": biz_stats["edge_count"],
        "implementation_nodes": impl_stats["node_count"],
        "implementation_edges": impl_stats["edge_count"],
    }
