"""Structured Mermaid extraction — convert mermaid_structure.json into graph nodes/edges.

This module handles direct extraction from parsed Mermaid artifacts WITHOUT LLM calls.
It reads mermaid_structure.json (structured JSON with nodes, edges, subgraphs) and
produces PipelineNode/PipelineEdge-compatible dicts with proper source_file attribution.

Key rules:
- source_file on every node/edge must point to the actual mermaid artifact path
- link_method must be 'explicit_mermaid_edge' (not 'structured_visual_edge')
- 'structured_visual_edge' is reserved for Excel/VLM-derived flowchart edges
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ._utils import normalize_id

logger = logging.getLogger(__name__)

# Mapping from mermaid node_type to semantic entity_type
_NODE_TYPE_MAP = {
    "process": "FlowNode",
    "decision": "DecisionPoint",
    "annotation": "Annotation",
    "start": "StartEndNode",
    "end": "StartEndNode",
    "io": "FlowNode",
    "subroutine": "FunctionModule",
    "database": "DataEntity",
    "default": "FlowNode",
}


def extract_from_mermaid_structure(
    structure_path: str | Path,
    project_id: str,
    project_name: str,
) -> tuple[list[dict], list[dict]]:
    """Extract nodes and edges from a mermaid_structure.json file.

    Returns (nodes, edges) as plain dicts compatible with the pipeline.
    All items have source_file pointing to the structure_path and
    link_method='explicit_mermaid_edge' for edges.
    """
    structure_path = Path(structure_path)
    if not structure_path.exists():
        logger.warning("Mermaid structure file not found: %s", structure_path)
        return [], []

    try:
        data = json.loads(structure_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse mermaid structure %s: %s", structure_path, exc)
        return [], []

    source_file = str(structure_path)
    diagram_type = data.get("diagram_type", "flowchart")
    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])
    subgraphs = data.get("subgraphs", [])

    # Build subgraph lookup: node_id -> subgraph info
    node_to_subgraph: dict[str, dict] = {}
    for sg in subgraphs:
        sg_id = sg.get("id", "")
        sg_label = sg.get("label", "")
        for nid in sg.get("nodes", []):
            node_to_subgraph[nid] = {"id": sg_id, "label": sg_label}

    nodes: list[dict] = []
    edges: list[dict] = []

    # Extract subgraph nodes as FunctionModule
    for sg in subgraphs:
        sg_id = sg.get("id", "")
        sg_label = sg.get("label", "")
        if not sg_id or not sg_label:
            continue

        node_id = f"mermaid:{project_id}:{normalize_id(sg_id)}"
        nodes.append({
            "id": node_id,
            "entity_type": "FunctionModule",
            "name": sg_label,
            "display_name": sg_label,
            "description": f"Mermaid subgraph: {sg_label}",
            "layer": "process",
            "category": "mermaid_subgraph",
            "evidence_text": f"subgraph {sg_id}[\"{sg_label}\"]",
            "confidence": 0.92,
            "review_status": "verified",
            "importance": 3,
            "view_scope": "core",
            "flow_node_kind": "subgraph",
            "parent_function_id": "",
            "sequence_no": "",
            "project_name": project_name,
            "project_id": project_id,
            "workbook_name": "mermaid",
            "sheet_name": f"flowchart_{diagram_type}",
            "sheet_type": "mermaid_flowchart",
            "source_file": source_file,
            "mermaid_node_id": sg_id,
        })

    # Extract individual nodes
    for raw_node in raw_nodes:
        nid = raw_node.get("id", "")
        label = raw_node.get("label", "")
        node_type = raw_node.get("node_type", "default")

        if not nid:
            continue

        entity_type = _NODE_TYPE_MAP.get(node_type, "FlowNode")
        # Infer more specific types from label content
        label_lower = label.lower() if label else ""
        if "api" in label_lower or "get：" in label_lower or "post：" in label_lower:
            entity_type = "APICallStep"
            flow_kind = "api"
        elif "ファイル" in label_lower and ("書込" in label_lower or "作成" in label_lower):
            entity_type = "FileOperation"
            flow_kind = "write"
        elif "ファイル" in label_lower and "読込" in label_lower:
            entity_type = "FileOperation"
            flow_kind = "read"
        elif node_type == "decision":
            flow_kind = "decision"
        elif node_type == "annotation":
            flow_kind = "annotation"
        elif "エラー" in label_lower:
            entity_type = "ErrorHandlingStep"
            flow_kind = "error"
        elif "初期化" in label_lower or "変数" in label_lower:
            flow_kind = "transform"
        else:
            flow_kind = "unknown"

        # Clean multi-line labels
        clean_label = label.replace("\\n", " ").strip() if label else nid

        sg_info = node_to_subgraph.get(nid, {})
        parent_id = ""
        if sg_info:
            parent_id = f"mermaid:{project_id}:{normalize_id(sg_info['id'])}"

        node_id = f"mermaid:{project_id}:{normalize_id(nid)}"
        nodes.append({
            "id": node_id,
            "entity_type": entity_type,
            "name": clean_label,
            "display_name": clean_label,
            "description": f"Mermaid {node_type} node: {clean_label}",
            "layer": "process",
            "category": f"mermaid_{node_type}",
            "evidence_text": f"{nid}[\"{label[:80]}\"]" if label else nid,
            "confidence": 0.90,
            "review_status": "verified",
            "importance": 2,
            "view_scope": "core",
            "flow_node_kind": flow_kind,
            "parent_function_id": parent_id,
            "sequence_no": "",
            "project_name": project_name,
            "project_id": project_id,
            "workbook_name": "mermaid",
            "sheet_name": f"flowchart_{diagram_type}",
            "sheet_type": "mermaid_flowchart",
            "source_file": source_file,
            "mermaid_node_id": nid,
        })

    # Build node ID lookup for edge endpoint resolution
    mermaid_id_to_node_id = {
        nid: f"mermaid:{project_id}:{normalize_id(nid)}"
        for raw_node in raw_nodes
        if (nid := raw_node.get("id", ""))
    }
    # Also add subgraph IDs
    for sg in subgraphs:
        sg_id = sg.get("id", "")
        if sg_id:
            mermaid_id_to_node_id[sg_id] = f"mermaid:{project_id}:{normalize_id(sg_id)}"

    # Extract edges
    for idx, raw_edge in enumerate(raw_edges):
        source = raw_edge.get("source", "")
        target = raw_edge.get("target", "")
        edge_label = raw_edge.get("label", "") or ""

        if not source or not target:
            continue

        start_id = mermaid_id_to_node_id.get(source, f"mermaid:{project_id}:{normalize_id(source)}")
        end_id = mermaid_id_to_node_id.get(target, f"mermaid:{project_id}:{normalize_id(target)}")

        # Determine relationship type based on edge label and context
        rel_type = "NEXT_STEP"
        condition_text = ""
        branch_label = ""

        if edge_label:
            label_lower = edge_label.lower()
            if any(kw in label_lower for kw in ["yes", "no", "true", "false", "ok", "ng", "はい", "いいえ"]):
                rel_type = "BRANCHES_TO"
                branch_label = edge_label
            elif any(kw in label_lower for kw in ["条件", "if", "when", "場合"]):
                rel_type = "BRANCHES_TO"
                condition_text = edge_label
            else:
                condition_text = edge_label

        edge_id = f"rel:mermaid:{project_id}:edge_{idx:04d}_{normalize_id(source)}_{normalize_id(target)}"
        edges.append({
            "id": edge_id,
            "from_id": start_id,
            "to_id": end_id,
            "start_id": start_id,
            "end_id": end_id,
            "type": rel_type,
            "edge_label": edge_label,
            "condition_text": condition_text,
            "branch_label": branch_label,
            "evidence_text": f"{source} --> {target}" + (f" |{edge_label}|" if edge_label else ""),
            "confidence": 0.92,
            "link_method": "explicit_mermaid_edge",
            "review_status": "verified",
            "layer": "process",
            "sequence_no": str(idx),
            "project_name": project_name,
            "project_id": project_id,
            "workbook_name": "mermaid",
            "sheet_name": f"flowchart_{diagram_type}",
            "source_file": source_file,
        })

    # Generate CONTAINS_STEP edges for subgraph membership
    for raw_node in raw_nodes:
        nid = raw_node.get("id", "")
        if not nid:
            continue
        sg_info = node_to_subgraph.get(nid)
        if not sg_info:
            continue

        sg_node_id = f"mermaid:{project_id}:{normalize_id(sg_info['id'])}"
        child_node_id = f"mermaid:{project_id}:{normalize_id(nid)}"

        edge_id = f"rel:mermaid:{project_id}:contains_{normalize_id(sg_info['id'])}_{normalize_id(nid)}"
        edges.append({
            "id": edge_id,
            "from_id": sg_node_id,
            "to_id": child_node_id,
            "start_id": sg_node_id,
            "end_id": child_node_id,
            "type": "CONTAINS_STEP",
            "edge_label": "",
            "condition_text": "",
            "branch_label": "",
            "evidence_text": f"subgraph {sg_info['id']} contains {nid}",
            "confidence": 0.95,
            "link_method": "explicit_mermaid_edge",
            "review_status": "verified",
            "layer": "process",
            "sequence_no": "",
            "project_name": project_name,
            "project_id": project_id,
            "workbook_name": "mermaid",
            "sheet_name": f"flowchart_{diagram_type}",
            "source_file": source_file,
        })

    logger.info(
        "Mermaid structured extraction: %d nodes, %d edges from %s",
        len(nodes), len(edges), structure_path.name,
    )
    return nodes, edges


def find_mermaid_structures(project_dir: str | Path) -> list[Path]:
    """Find all mermaid_structure.json files under a project run directory."""
    project_dir = Path(project_dir)
    results = []

    # Check mermaid/ top-level
    for f in project_dir.rglob("mermaid_structure.json"):
        results.append(f)

    # Check parsed/mermaid/
    parsed_mermaid = project_dir / "parsed" / "mermaid"
    if parsed_mermaid.exists():
        for f in parsed_mermaid.rglob("mermaid_structure.json"):
            if f not in results:
                results.append(f)

    return sorted(results)
