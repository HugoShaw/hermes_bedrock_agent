"""Generate Neptune-compatible openCypher MERGE statements.

Neptune Analytics constraints:
  - No array properties (join with | separator)
  - Single quotes in string values must be escaped
  - Semicolons in values must be replaced (they break statement splitting on ';')
  - MERGE on node uses 'id' as the primary key
  - Edge MERGE uses MATCH on both endpoints, then MERGE on the relationship
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Escaping ──────────────────────────────────────────────────────────────────

def _escape(text: str) -> str:
    """Escape text for Cypher single-quoted string literals.

    Replaces ASCII semicolons with fullwidth ；ので to prevent the statement
    splitter from cutting mid-value — this was a critical bug fix in v3.1.
    """
    if not text:
        return ""
    result = text.replace("\\", "\\\\").replace("'", "\\'")
    result = result.replace("\n", " ").replace("\r", "")
    result = result.replace(";", "；")  # fullwidth semicolon — avoids split issues
    return result[:500]


def _build_cypher_props(obj: dict, exclude: set[str]) -> str:
    """Build SET clause property assignments from a dict."""
    parts = []
    # use 'n' for nodes, 'r' for edges
    var = "n" if ("labels" in obj or "entity_type" in obj) else "r"

    for key, value in obj.items():
        if key in exclude or value is None:
            continue
        if isinstance(value, bool):
            parts.append(f"{var}.{key} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            parts.append(f"{var}.{key} = {value}")
        elif isinstance(value, str):
            if not value.strip():
                continue
            parts.append(f"{var}.{key} = '{_escape(value)}'")
        elif isinstance(value, list):
            joined = "|".join(str(v) for v in value)
            parts.append(f"{var}.{key} = '{_escape(joined)}'")

    return ",\n    ".join(parts) if parts else f"{var}.id = {var}.id"


# ── Statement generators (plain dict API, matching v3.1 behaviour) ────────────

def node_dict_to_cypher(node: dict) -> str:
    """Generate an idempotent MERGE statement for a node dict."""
    labels = node.get("labels", node.get("entity_type", "Node"))
    primary_label = labels.split("|")[0]
    node_id = node["id"]
    props = _build_cypher_props(node, exclude={"id", "labels"})
    return f"MERGE (n:{primary_label} {{id: '{_escape(node_id)}'}})\nSET {props};"


def edge_dict_to_cypher(edge: dict) -> str:
    """Generate an idempotent MERGE statement for an edge dict."""
    start_id = edge.get("start_id", "")
    end_id = edge.get("end_id", "")
    rel_type = edge.get("type", "RELATED_TO")
    edge_id = edge.get("id", "")
    props = _build_cypher_props(edge, exclude={"id", "start_id", "end_id", "type"})
    return (
        f"MATCH (a {{id: '{_escape(start_id)}'}})\n"
        f"MATCH (b {{id: '{_escape(end_id)}'}})\n"
        f"MERGE (a)-[r:{rel_type} {{id: '{_escape(edge_id)}'}}]->(b)\n"
        f"SET {props};"
    )


# ── Pydantic-model wrappers (kept for backward compat with loader.py) ─────────

def node_to_cypher(node: object) -> str:
    """Accept a PipelineNode Pydantic model or a plain dict."""
    d = node.model_dump() if hasattr(node, "model_dump") else dict(node)
    return node_dict_to_cypher(d)


def edge_to_cypher(edge: object) -> str:
    """Accept a PipelineEdge Pydantic model or a plain dict."""
    d = edge.model_dump() if hasattr(edge, "model_dump") else dict(edge)
    return edge_dict_to_cypher(d)


# ── File writers ──────────────────────────────────────────────────────────────

def generate_cypher(
    nodes: list[dict],
    edges: list[dict],
    output_dir: Path,
    project_id: str,
) -> tuple[Path, Path]:
    """Write Cypher files for nodes and edges. Returns (nodes_file, edges_file)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_file = output_dir / f"{project_id}_nodes.cypher"
    edges_file = output_dir / f"{project_id}_edges.cypher"

    node_stmts = [node_dict_to_cypher(n) for n in nodes]
    edge_stmts = [edge_dict_to_cypher(e) for e in edges]

    nodes_file.write_text("\n\n".join(node_stmts) + "\n", encoding="utf-8")
    edges_file.write_text("\n\n".join(edge_stmts) + "\n", encoding="utf-8")

    logger.info(
        "Cypher files: %d node stmts → %s, %d edge stmts → %s",
        len(node_stmts), nodes_file.name,
        len(edge_stmts), edges_file.name,
    )
    return nodes_file, edges_file


def write_cypher_file(
    nodes: list[dict],
    edges: list[dict],
    output_path: Path,
    graph_type: str = "full",
) -> None:
    """Write a combined single Cypher file (nodes then edges)."""
    statements = [node_dict_to_cypher(n) for n in nodes] + [edge_dict_to_cypher(e) for e in edges]
    output_path.write_text("\n\n".join(statements), encoding="utf-8")
    logger.info(
        "Generated %s Cypher: %d nodes, %d edges → %s",
        graph_type, len(nodes), len(edges), output_path,
    )


def generate_jsonl(
    nodes: list,
    edges: list,
    output_dir: Path,
    project_id: str,
) -> tuple[Path, Path]:
    """Write nodes.jsonl and edges.jsonl. Accepts dicts or Pydantic models."""
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_jsonl = output_dir / f"{project_id}_nodes.jsonl"
    edges_jsonl = output_dir / f"{project_id}_edges.jsonl"

    with nodes_jsonl.open("w", encoding="utf-8") as f:
        for node in nodes:
            d = node.model_dump() if hasattr(node, "model_dump") else node
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    with edges_jsonl.open("w", encoding="utf-8") as f:
        for edge in edges:
            d = edge.model_dump() if hasattr(edge, "model_dump") else edge
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    logger.info(
        "JSONL files: %s (%d nodes), %s (%d edges)",
        nodes_jsonl.name, len(nodes), edges_jsonl.name, len(edges),
    )
    return nodes_jsonl, edges_jsonl
