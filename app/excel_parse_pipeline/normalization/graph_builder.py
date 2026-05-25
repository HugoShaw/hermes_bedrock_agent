"""GraphRAG normalization: convert extracted data to graph nodes and edges.

Uses a generic ontology:
- Document, Workbook, Sheet, Region, Table, Column, Field
- SourceField, TargetField, MappingRelation, TransformationRule
- Condition, FlowNode, FlowEdge, Evidence, Uncertainty
"""
import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Node labels (generic ontology)
NODE_LABELS = [
    "Document", "Workbook", "Sheet", "Region", "Table", "Column",
    "Field", "SourceField", "TargetField", "MappingRelation",
    "TransformationRule", "Condition", "LookupRule", "CodeConversionRule",
    "FixedValue", "FlowNode", "FlowEdge", "Evidence", "Uncertainty",
]

# Edge types
EDGE_TYPES = [
    "HAS_SHEET", "HAS_REGION", "HAS_TABLE", "HAS_FIELD",
    "MAPS_TO", "USES_TRANSFORMATION", "HAS_CONDITION",
    "REFERENCES", "DERIVED_FROM", "HAS_EVIDENCE", "REQUIRES_REVIEW",
    "NEXT_STEP", "BRANCHES_TO",
]


def _make_id(prefix: str, *parts) -> str:
    """Generate a deterministic ID from parts."""
    content = "|".join(str(p) for p in parts)
    hash_part = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"{prefix}:{hash_part}"


def normalize_to_graph(
    execution_results: dict,
    mermaid_results: list,
    parse_plan: dict,
    workbook_atlas: dict,
) -> dict:
    """Normalize all extracted data into graph nodes and edges."""
    nodes = []
    edges = []

    workbook_name = workbook_atlas.get("workbook_name", "unknown")
    workbook_id = _make_id("workbook", workbook_name)

    # Workbook node
    nodes.append({
        "node_id": workbook_id,
        "label": "Workbook",
        "name": workbook_name,
        "properties": {
            "workbook_type": parse_plan.get("workbook_type", "unknown"),
            "sheet_count": workbook_atlas.get("sheet_count", 0),
            "source_file": workbook_atlas.get("source_file", ""),
        },
        "confidence": 0.95,
        "evidence": {
            "workbook": workbook_name,
            "source_file": workbook_atlas.get("source_file", ""),
        },
    })

    # Sheet nodes
    for sheet in workbook_atlas.get("sheets", []):
        sheet_name = sheet["sheet_name"]
        sheet_id = _make_id("sheet", workbook_name, sheet_name)

        nodes.append({
            "node_id": sheet_id,
            "label": "Sheet",
            "name": sheet_name,
            "properties": {
                "used_range": sheet.get("used_range", ""),
                "row_count": sheet["dimensions"]["total_rows"],
                "col_count": sheet["dimensions"]["total_cols"],
            },
            "confidence": 0.95,
            "evidence": {
                "workbook": workbook_name,
                "sheet": sheet_name,
            },
        })

        edges.append({
            "edge_id": _make_id("edge", workbook_id, "HAS_SHEET", sheet_id),
            "source_id": workbook_id,
            "target_id": sheet_id,
            "relation_type": "HAS_SHEET",
            "confidence": 0.95,
        })

    # Table nodes from execution results
    for table in execution_results.get("tables", []):
        table_id = _make_id("table", workbook_name, table.get("sheet_name"), table.get("region_id"))
        sheet_id = _make_id("sheet", workbook_name, table.get("sheet_name"))

        nodes.append({
            "node_id": table_id,
            "label": "Table",
            "name": f"{table.get('sheet_name')}_{table.get('region_id')}",
            "properties": {
                "semantic_role": table.get("semantic_role", "unknown"),
                "range": table.get("range", ""),
                "row_count": table.get("row_count", 0),
                "headers": json.dumps(table.get("headers", {}), ensure_ascii=False),
            },
            "confidence": 0.8,
            "evidence": table.get("evidence", {}),
        })

        edges.append({
            "edge_id": _make_id("edge", sheet_id, "HAS_TABLE", table_id),
            "source_id": sheet_id,
            "target_id": table_id,
            "relation_type": "HAS_TABLE",
            "confidence": 0.8,
        })

    # Field nodes (sample - don't create thousands of nodes for large tables)
    field_count = 0
    for field in execution_results.get("fields", []):
        if field_count >= 200:  # Limit to prevent explosion
            break
        field_id = _make_id("field", workbook_name, field.get("field_id"))
        table_id = _make_id("table", workbook_name, field.get("sheet_name"), field.get("region_id"))

        # Extract field name from data
        field_name = ""
        for col_data in field.get("data", {}).values():
            if col_data.get("role") == "field_name":
                field_name = str(col_data.get("value", ""))
                break
        if not field_name:
            # Use first non-empty value
            for col_data in field.get("data", {}).values():
                if col_data.get("value"):
                    field_name = str(col_data["value"])[:50]
                    break

        if field_name:
            nodes.append({
                "node_id": field_id,
                "label": "Field",
                "name": field_name,
                "properties": {
                    "row": field.get("row"),
                    "data": json.dumps(
                        {k: v.get("value") for k, v in field.get("data", {}).items()},
                        ensure_ascii=False
                    )[:500],
                },
                "confidence": field.get("confidence", 0.7),
                "evidence": field.get("evidence", {}),
            })

            edges.append({
                "edge_id": _make_id("edge", table_id, "HAS_FIELD", field_id),
                "source_id": table_id,
                "target_id": field_id,
                "relation_type": "HAS_FIELD",
                "confidence": field.get("confidence", 0.7),
            })
            field_count += 1

    # Mapping edges
    for mapping in execution_results.get("mappings", []):
        source_name = mapping.get("source_field", "")
        target_name = mapping.get("target_field", "")
        
        if source_name and target_name:
            mapping_id = _make_id("mapping", workbook_name, source_name, target_name)
            
            nodes.append({
                "node_id": mapping_id,
                "label": "MappingRelation",
                "name": f"{source_name} -> {target_name}",
                "properties": {
                    "source_field": source_name,
                    "target_field": target_name,
                    "transformation": mapping.get("transformation", ""),
                },
                "confidence": mapping.get("confidence", 0.7),
                "evidence": mapping.get("evidence", {}),
            })

    # Flow nodes from Mermaid
    for mermaid in mermaid_results:
        for node in mermaid.get("nodes", []):
            flow_node_id = _make_id("flow", mermaid.get("source_file", ""), node["node_id"])

            nodes.append({
                "node_id": flow_node_id,
                "label": "FlowNode",
                "name": node.get("label", node["node_id"]),
                "properties": {
                    "node_type": node.get("node_type", "process"),
                    "mermaid_node_id": node["node_id"],
                    "source_type": "manual_mermaid",
                    "mermaid_file": mermaid.get("source_file", ""),
                    "related_workbook": mermaid.get("related_workbook", ""),
                    "related_sheet": mermaid.get("related_sheet", ""),
                },
                "confidence": 1.0,
                "evidence": {
                    "mermaid_file": mermaid.get("source_file", ""),
                    "workbook": mermaid.get("related_workbook", ""),
                },
            })

        for edge in mermaid.get("edges", []):
            source_flow_id = _make_id("flow", mermaid.get("source_file", ""), edge["source_node"])
            target_flow_id = _make_id("flow", mermaid.get("source_file", ""), edge["target_node"])

            edges.append({
                "edge_id": _make_id("edge", source_flow_id, "NEXT_STEP", target_flow_id),
                "source_id": source_flow_id,
                "target_id": target_flow_id,
                "relation_type": "NEXT_STEP",
                "properties": {
                    "label": edge.get("label", ""),
                    "edge_type": edge.get("edge_type", "flow"),
                    "source_type": "manual_mermaid",
                },
                "confidence": 1.0,
                "evidence": {
                    "mermaid_file": mermaid.get("source_file", ""),
                },
            })

    # Uncertainty nodes
    for record in execution_results.get("uncertain_records", []):
        unc_id = _make_id("uncertainty", record.get("sheet_name", ""), record.get("region_id", ""))
        nodes.append({
            "node_id": unc_id,
            "label": "Uncertainty",
            "name": record.get("reason", "unknown"),
            "properties": {
                "text": record.get("text", "")[:200],
                "record_type": record.get("record_type", ""),
            },
            "confidence": record.get("confidence", 0.3),
            "evidence": {
                "workbook": workbook_name,
                "sheet": record.get("sheet_name", ""),
                "region_id": record.get("region_id", ""),
            },
        })

    return {"nodes": nodes, "edges": edges}


def save_graph(graph: dict, output_dir: Path) -> dict:
    """Save graph nodes and edges as JSONL."""
    graph_dir = output_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = graph_dir / "nodes.jsonl"
    edges_path = graph_dir / "edges.jsonl"

    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in graph["nodes"]:
            f.write(json.dumps(node, ensure_ascii=False, default=str) + "\n")

    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in graph["edges"]:
            f.write(json.dumps(edge, ensure_ascii=False, default=str) + "\n")

    return {
        "nodes": {"path": str(nodes_path), "count": len(graph["nodes"])},
        "edges": {"path": str(edges_path), "count": len(graph["edges"])},
    }
