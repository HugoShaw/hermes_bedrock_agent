"""Phase 4 & 5: Build project/workbook/sheet hierarchy nodes + cross-document links."""

from __future__ import annotations

import logging
from collections import defaultdict

from ._utils import normalize_id

logger = logging.getLogger(__name__)


def build_structure_layer(
    inventory: list[dict],
    project_id: str,
    project_name: str,
) -> tuple[list[dict], list[dict]]:
    """Build Project → Workbook → Sheet hierarchy nodes and edges."""
    nodes: list[dict] = []
    edges: list[dict] = []

    # Project node
    proj_node_id = f"project:{project_id}"
    nodes.append({
        "id": proj_node_id,
        "labels": "Project",
        "entity_type": "Project",
        "name": project_name,
        "display_name": project_name,
        "description": f"Project: {project_name}",
        "project_name": project_name,
        "project_id": project_id,
        "layer": "project",
        "category": "project",
        "source_file": inventory[0]["file_path"] if inventory else "",
        "evidence_id": f"evidence:{project_id}:project",
        "evidence_text": f"Project directory containing {len(inventory)} markdown files",
        "confidence": 1.0,
        "review_status": "verified",
        "importance": 3,
        "view_scope": "core",
    })

    # Workbook nodes
    workbooks_seen: set[str] = set()
    for file_rec in inventory:
        wb_name = file_rec["workbook_name"]
        if wb_name in workbooks_seen:
            continue
        workbooks_seen.add(wb_name)

        wb_id = f"workbook:{project_id}:{normalize_id(wb_name)}"
        nodes.append({
            "id": wb_id,
            "labels": "Workbook|DocumentGroup",
            "entity_type": "Workbook",
            "name": wb_name,
            "display_name": wb_name,
            "description": f"Workbook: {wb_name}",
            "project_name": project_name,
            "project_id": project_id,
            "layer": "project",
            "category": "workbook",
            "source_file": file_rec["file_path"],
            "evidence_id": f"evidence:{project_id}:{normalize_id(wb_name)}",
            "evidence_text": f"Workbook directory: {wb_name}",
            "confidence": 1.0,
            "review_status": "verified",
            "importance": 2,
            "view_scope": "core",
        })
        edges.append({
            "id": f"rel:{project_id}:struct_{normalize_id(wb_name)[:20]}_proj",
            "start_id": proj_node_id,
            "end_id": wb_id,
            "type": "HAS_WORKBOOK",
            "project_name": project_name,
            "project_id": project_id,
            "source_file": file_rec["file_path"],
            "evidence_id": f"evidence:{project_id}:{normalize_id(wb_name)}",
            "evidence_text": f"Project contains workbook {wb_name}",
            "link_method": "structural",
            "confidence": 1.0,
            "review_status": "verified",
            "layer": "project",
        })

    # Sheet nodes
    for file_rec in inventory:
        wb_key = normalize_id(file_rec["workbook_name"])
        sheet_key = normalize_id(file_rec["sheet_name"])
        sheet_id = f"sheet:{project_id}:{wb_key}:{sheet_key}"
        wb_id = f"workbook:{project_id}:{wb_key}"

        nodes.append({
            "id": sheet_id,
            "labels": "Sheet",
            "entity_type": "Sheet",
            "name": file_rec["sheet_name"],
            "display_name": f"{file_rec['workbook_name']} / {file_rec['sheet_name']}",
            "description": f"Sheet type: {file_rec['sheet_type']}",
            "project_name": project_name,
            "project_id": project_id,
            "layer": "evidence",
            "category": file_rec["sheet_type"],
            "source_file": file_rec["file_path"],
            "evidence_id": f"evidence:{project_id}:{wb_key}:{sheet_key}",
            "evidence_text": f"Sheet: {file_rec['sheet_name']} ({file_rec['sheet_type']})",
            "confidence": 1.0,
            "review_status": "verified",
            "importance": 1,
            "view_scope": "evidence",
            "workbook_name": file_rec["workbook_name"],
            "sheet_name": file_rec["sheet_name"],
            "sheet_type": file_rec["sheet_type"],
        })
        edges.append({
            "id": f"rel:{project_id}:struct_{wb_key}_{sheet_key}",
            "start_id": wb_id,
            "end_id": sheet_id,
            "type": "HAS_SHEET",
            "project_name": project_name,
            "project_id": project_id,
            "source_file": file_rec["file_path"],
            "evidence_id": f"evidence:{project_id}:{wb_key}:{sheet_key}",
            "evidence_text": (
                f"Workbook {file_rec['workbook_name']} contains sheet {file_rec['sheet_name']}"
            ),
            "link_method": "structural",
            "confidence": 1.0,
            "review_status": "verified",
            "layer": "evidence",
        })

    return nodes, edges


def build_sheet_id_map(inventory: list[dict], project_id: str) -> dict[str, str]:
    """Map file_path → sheet node ID for EXTRACTED_OBJECT link generation."""
    mapping = {}
    for file_rec in inventory:
        wb_key = normalize_id(file_rec["workbook_name"])
        sheet_key = normalize_id(file_rec["sheet_name"])
        mapping[file_rec["file_path"]] = f"sheet:{project_id}:{wb_key}:{sheet_key}"
    return mapping


def build_cross_document_links(
    nodes: list[dict],
    edges: list[dict],
    project_id: str,
    project_name: str,
) -> list[dict]:
    """Generate candidate cross-document links based on shared entity names."""
    candidate_links: list[dict] = []

    # Index by name for cross-sheet matching
    systems_by_name: dict[str, str] = {}
    apis_by_name: dict[str, str] = {}
    mappings_by_name: dict[str, str] = {}

    for node in nodes:
        et = node.get("entity_type", "")
        name = node.get("name", "").strip()
        if not name:
            continue
        if et in ("System", "Middleware"):
            systems_by_name[name] = node["id"]
        elif et == "APIOperation":
            apis_by_name[name] = node["id"]
        elif et == "MappingDefinition":
            mappings_by_name[name] = node["id"]

    existing_edge_keys: set[tuple] = {
        (e.get("start_id"), e.get("end_id"), e.get("type"))
        for e in edges
    }

    def _add(start: str, end: str, rel: str, evidence: str, source: str) -> None:
        key = (start, end, rel)
        if key not in existing_edge_keys:
            existing_edge_keys.add(key)
            candidate_links.append({
                "project_name": project_name,
                "project_id": project_id,
                "start_id": start,
                "end_id": end,
                "type": rel,
                "evidence_text": evidence,
                "link_method": "cross_sheet_name_match",
                "confidence": 0.70,
                "review_status": "pending",
                "source_file": source,
                "layer": "cross_layer",
            })

    for node in nodes:
        et = node.get("entity_type", "")
        desc = (node.get("description", "") + " " + node.get("evidence_text", "")).lower()

        if et == "FunctionModule":
            for api_name, api_id in apis_by_name.items():
                if api_name.lower() in desc and node["id"] != api_id:
                    _add(node["id"], api_id, "CALLS_API",
                         f"Function '{node.get('name','')}' references API '{api_name}'",
                         node.get("source_file", ""))

        elif et == "APIOperation":
            for map_name, map_id in mappings_by_name.items():
                if map_name.lower() in desc and node["id"] != map_id:
                    _add(node["id"], map_id, "USES_MAPPING",
                         f"API '{node.get('name','')}' references mapping '{map_name}'",
                         node.get("source_file", ""))

    return candidate_links
