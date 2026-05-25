"""Graph builder: extracts entities from chunks and loads them into Neptune Analytics.

Node labels: System, API, Field, Sheet, MappingRule, BusinessRule, DataFlow
Edge types:  MAPS_TO, CALLS_API, TRANSFORMS, FLOWS_TO, DEFINED_IN, HAS_CONDITION

All nodes and edges carry an `evidence_pdf_s3_path` property for traceability.
All operations use MERGE (upsert) so the pipeline is idempotent.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .config import config
from .schemas import Chunk, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# ── Known system node definitions ────────────────────────────────────────────

_KNOWN_SYSTEMS = {
    "SAP": "SAP S/4HANA",
    "S4/HANA": "SAP S/4HANA",
    "S4HANA": "SAP S/4HANA",
    "DataSpider": "DataSpider (NTT DATA)",
    "ANDPAD": "ANDPAD",
    "中間F": "中間ファイル (Intermediate File)",
    "中間ファイル": "中間ファイル (Intermediate File)",
}

_SYSTEM_CANONICAL = {
    "SAP": "SAP",
    "S4/HANA": "SAP",
    "S4HANA": "SAP",
    "DataSpider": "DataSpider",
    "ANDPAD": "ANDPAD",
    "中間F": "IntermediateFile",
    "中間ファイル": "IntermediateFile",
}

# Mapping of chunk_type → inferred DataFlow edge type
_FLOW_FROM_TYPE = {
    "mapping_table": "MAPS_TO",
    "api_spec": "CALLS_API",
    "flowchart": "FLOWS_TO",
    "data_condition": "HAS_CONDITION",
    "business_rule": "HAS_CONDITION",
}


def _safe_node_id(label: str, name: str) -> str:
    """Create a deterministic node ID from label + name."""
    clean = re.sub(r"[^\w]", "_", name)
    return f"{label}_{clean}"[:128]


# ── Entity extraction ─────────────────────────────────────────────────────────

def extract_entities(chunk: Chunk) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Extract nodes and edges from a single chunk."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    pdf_path = chunk.source_pdf_s3_path

    sheet_node_id = _safe_node_id("Sheet", f"{chunk.sheet_index:02d}_{chunk.sheet_name}")
    sheet_node = GraphNode(
        node_id=sheet_node_id,
        label="Sheet",
        name=chunk.sheet_name,
        properties={
            "sheet_index": chunk.sheet_index,
            "workbook_name": chunk.workbook_name,
            "chunk_type": chunk.chunk_type,
        },
        evidence_pdf_s3_path=pdf_path,
    )
    nodes.append(sheet_node)

    # System nodes + FLOWS_TO edges between systems
    system_node_ids: list[str] = []
    for sys_kw in chunk.systems:
        canonical = _SYSTEM_CANONICAL.get(sys_kw, sys_kw)
        sys_node_id = _safe_node_id("System", canonical)
        display = _KNOWN_SYSTEMS.get(sys_kw, sys_kw)
        nodes.append(GraphNode(
            node_id=sys_node_id,
            label="System",
            name=canonical,
            properties={"display_name": display},
            evidence_pdf_s3_path=pdf_path,
        ))
        system_node_ids.append(sys_node_id)
        # Sheet DEFINED_IN System
        edges.append(GraphEdge(
            from_id=sheet_node_id,
            to_id=sys_node_id,
            relationship="DEFINED_IN",
            properties={"chunk_id": chunk.chunk_id},
            evidence_pdf_s3_path=pdf_path,
        ))

    # DataFlow node between consecutive systems in a mapping sheet
    if chunk.chunk_type == "mapping_table" and len(system_node_ids) >= 2:
        for i in range(len(system_node_ids) - 1):
            flow_name = f"{system_node_ids[i]}_to_{system_node_ids[i+1]}"
            flow_node_id = _safe_node_id("DataFlow", flow_name)
            nodes.append(GraphNode(
                node_id=flow_node_id,
                label="DataFlow",
                name=flow_name,
                properties={"sheet_index": chunk.sheet_index, "chunk_id": chunk.chunk_id},
                evidence_pdf_s3_path=pdf_path,
            ))
            edges.append(GraphEdge(
                from_id=system_node_ids[i],
                to_id=system_node_ids[i + 1],
                relationship="FLOWS_TO",
                properties={"via": flow_node_id, "sheet_index": chunk.sheet_index},
                evidence_pdf_s3_path=pdf_path,
            ))

    # API nodes + CALLS_API edges from sheet
    for api_name in chunk.apis:
        api_node_id = _safe_node_id("API", api_name)
        nodes.append(GraphNode(
            node_id=api_node_id,
            label="API",
            name=api_name,
            properties={"sheet_index": chunk.sheet_index},
            evidence_pdf_s3_path=pdf_path,
        ))
        edges.append(GraphEdge(
            from_id=sheet_node_id,
            to_id=api_node_id,
            relationship="CALLS_API",
            properties={"chunk_id": chunk.chunk_id},
            evidence_pdf_s3_path=pdf_path,
        ))

    # Field nodes + MAPS_TO edges
    for field_name in chunk.fields[:10]:  # limit to top 10 per chunk
        field_node_id = _safe_node_id("Field", f"{chunk.sheet_index:02d}_{field_name}")
        nodes.append(GraphNode(
            node_id=field_node_id,
            label="Field",
            name=field_name,
            properties={"sheet_index": chunk.sheet_index, "sheet_name": chunk.sheet_name},
            evidence_pdf_s3_path=pdf_path,
        ))
        edges.append(GraphEdge(
            from_id=sheet_node_id,
            to_id=field_node_id,
            relationship="MAPS_TO",
            properties={"chunk_id": chunk.chunk_id},
            evidence_pdf_s3_path=pdf_path,
        ))

    # MappingRule / BusinessRule nodes for specific chunk types
    if chunk.chunk_type in ("mapping_table", "business_rule", "data_condition"):
        rule_label = "MappingRule" if chunk.chunk_type == "mapping_table" else "BusinessRule"
        rule_node_id = _safe_node_id(rule_label, chunk.chunk_id)
        nodes.append(GraphNode(
            node_id=rule_node_id,
            label=rule_label,
            name=chunk.chunk_id,
            properties={
                "content_preview": chunk.content[:200],
                "sheet_index": chunk.sheet_index,
            },
            evidence_pdf_s3_path=pdf_path,
        ))
        rel = "TRANSFORMS" if chunk.chunk_type == "mapping_table" else "HAS_CONDITION"
        edges.append(GraphEdge(
            from_id=sheet_node_id,
            to_id=rule_node_id,
            relationship=rel,
            properties={"chunk_id": chunk.chunk_id},
            evidence_pdf_s3_path=pdf_path,
        ))

    # Related-sheet FLOWS_TO edges
    for related_idx in chunk.related_sheets[:5]:
        related_node_id = _safe_node_id("Sheet", f"{related_idx:02d}_")
        edges.append(GraphEdge(
            from_id=sheet_node_id,
            to_id=related_node_id,
            relationship="FLOWS_TO",
            properties={"source": "cross_sheet_summary"},
            evidence_pdf_s3_path=pdf_path,
        ))

    return nodes, edges


# ── Neptune cypher helpers ────────────────────────────────────────────────────

def _props_to_cypher_set(props: dict, prefix: str = "n") -> str:
    """Convert a dict to a SET clause fragment."""
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


def _merge_node_cypher(node: GraphNode) -> tuple[str, dict]:
    """Build a MERGE cypher for a node."""
    props = dict(node.properties)
    props["evidence_pdf_s3_path"] = node.evidence_pdf_s3_path
    props["name"] = node.name

    set_parts = _props_to_cypher_set(props, "n")
    set_clause = f"SET {set_parts}" if set_parts else ""

    name_esc = node.name.replace("\\", "\\\\").replace("'", "\\'")
    cypher = (
        f"MERGE (n:{node.label} {{node_id: '{node.node_id}'}}) "
        f"ON CREATE SET n.name = '{name_esc}' "
        f"ON MATCH SET n.name = '{name_esc}' "
    )
    if set_clause:
        cypher += set_clause
    return cypher, {}


def _merge_edge_cypher(edge: GraphEdge) -> tuple[str, dict]:
    """Build a MERGE cypher for an edge."""
    props = dict(edge.properties)
    props["evidence_pdf_s3_path"] = edge.evidence_pdf_s3_path

    set_parts = _props_to_cypher_set(props, "r")
    set_clause = f"SET {set_parts}" if set_parts else ""

    cypher = (
        f"MATCH (a {{node_id: '{edge.from_id}'}}), (b {{node_id: '{edge.to_id}'}}) "
        f"MERGE (a)-[r:{edge.relationship}]->(b) "
    )
    if set_clause:
        cypher += set_clause
    return cypher, {}


# ── Main builder ──────────────────────────────────────────────────────────────

def build_graph(
    chunks: list[Chunk],
    graph_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Extract entities from all chunks and load into Neptune.

    Args:
        chunks: List of Chunk objects from dataset_builder.
        graph_id: Neptune graph ID override.
        dry_run: If True, skip actual Neptune calls and just log.

    Returns:
        Dict with node_count, edge_count, error_count stats.
    """
    from hermes_bedrock_agent.clients.neptune_client import NeptuneClient, NeptuneClientError

    client = NeptuneClient(graph_id=graph_id or config.neptune_graph_id)

    if not client.is_configured:
        logger.warning("Neptune graph ID not configured — skipping graph build")
        return {"node_count": 0, "edge_count": 0, "error_count": 0}

    # Deduplicate nodes across all chunks
    all_nodes: dict[str, GraphNode] = {}
    all_edges: list[GraphEdge] = []

    for chunk in chunks:
        nodes, edges = extract_entities(chunk)
        for node in nodes:
            # Merge: keep the one with a non-empty pdf path if possible
            if node.node_id not in all_nodes or not all_nodes[node.node_id].evidence_pdf_s3_path:
                all_nodes[node.node_id] = node
        all_edges.extend(edges)

    node_list = list(all_nodes.values())
    logger.info("Graph extraction: %d unique nodes, %d edges", len(node_list), len(all_edges))

    node_count = 0
    edge_count = 0
    error_count = 0

    if dry_run:
        logger.info("DRY RUN: would write %d nodes, %d edges", len(node_list), len(all_edges))
        return {"node_count": len(node_list), "edge_count": len(all_edges), "error_count": 0}

    # Upsert nodes
    for node in node_list:
        try:
            cypher, params = _merge_node_cypher(node)
            client.execute_query(cypher, params)
            node_count += 1
        except Exception as exc:
            logger.warning("Node upsert failed [%s]: %s", node.node_id, exc)
            error_count += 1

    logger.info("Nodes written: %d / %d", node_count, len(node_list))

    # Upsert edges
    for edge in all_edges:
        try:
            cypher, params = _merge_edge_cypher(edge)
            client.execute_query(cypher, params)
            edge_count += 1
        except Exception as exc:
            logger.debug("Edge upsert failed [%s->%s]: %s", edge.from_id, edge.to_id, exc)
            error_count += 1

    logger.info("Edges written: %d / %d (errors: %d)", edge_count, len(all_edges), error_count)
    return {"node_count": node_count, "edge_count": edge_count, "error_count": error_count}
