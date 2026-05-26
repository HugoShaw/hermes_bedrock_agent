"""Simple Mermaid builder - generates a single .mmd file from flow specs and OOXML data.

Produces one consolidated Mermaid file with subgraphs per sheet.
Supports both Claude flow_spec and OOXML-only fallback.
"""
import re
import logging
from typing import Optional
from .models import SheetData

logger = logging.getLogger(__name__)


def build_combined_mermaid(
    sheets: list[SheetData],
    classifications: list[dict],
    claude_results: dict[str, Optional[dict]],
) -> str:
    """Build a single Mermaid file covering all visual/mixed sheets.

    Args:
        sheets: List of SheetData objects
        classifications: Classification results from simple_sheet_classifier
        claude_results: Dict of {sheet_name: claude_response_or_None}

    Returns:
        Complete Mermaid source code string
    """
    lines = ["%% Auto-generated Mermaid from Excel OOXML + Claude analysis"]
    lines.append("%% Source: convert_excel_to_markdown_simple.py")
    lines.append("")

    # Determine global flow direction from Claude results
    flow_dir = "TD"
    for result in claude_results.values():
        if result and result.get("flow_direction"):
            flow_dir = result["flow_direction"]
            break

    lines.append(f"flowchart {flow_dir}")
    lines.append("")

    sheet_map = {s.name: s for s in sheets}
    has_content = False

    for cls in classifications:
        if cls["classification"] in ("empty", "text_table"):
            continue

        sheet_name = cls["sheet_name"]
        sheet = sheet_map.get(sheet_name)
        if not sheet:
            continue

        claude_result = claude_results.get(sheet_name)

        # Generate subgraph for this sheet
        sheet_idx = next(
            (i for i, c in enumerate(classifications) if c["sheet_name"] == sheet_name), 0
        )
        safe_subgraph_id = f"SHEET_{sheet_idx + 1}"
        lines.append(f'subgraph {safe_subgraph_id}["{_escape_label(sheet_name)}"]')

        # Use a per-sheet prefix to avoid node ID collisions between sheets
        node_prefix = f"SH{sheet_idx + 1}_"

        if claude_result and claude_result.get("flow_spec"):
            # Use Claude flow_spec
            sheet_lines = _build_from_flow_spec(
                claude_result["flow_spec"], sheet_name, node_prefix
            )
            has_content = True
        elif sheet.shapes or sheet.connectors:
            # Fallback to OOXML
            sheet_lines = _build_from_ooxml(sheet, node_prefix)
            has_content = True
        else:
            sheet_lines = [f"    %% No visual content for sheet '{sheet_name}'"]

        lines.extend(sheet_lines)
        lines.append("end")
        lines.append("")

    if not has_content:
        lines.append("    %% No visual sheets found")

    return "\n".join(lines)


def _build_from_flow_spec(flow_spec: dict, sheet_name: str, node_prefix: str = "") -> list[str]:
    """Build Mermaid nodes and edges from Claude flow_spec."""
    lines = []
    lines.append(f"    %% Generated from Claude flow_spec")

    nodes = flow_spec.get("nodes", [])
    edges = flow_spec.get("edges", [])

    # Node definitions
    node_ids = set()
    id_map = {}  # original id -> prefixed id
    for node in nodes:
        orig_id = _safe_id(node.get("id", "UNKNOWN"))
        node_id = f"{node_prefix}{orig_id}"
        node_ids.add(node_id)
        id_map[node.get("id", "")] = node_id
        text = _escape_label(node.get("text", orig_id))
        node_type = node.get("type", "process")
        confidence = node.get("confidence", 1.0)

        if confidence < 0.5:
            lines.append(f"    %% low_confidence node: {node_id}")

        node_def = _format_node(node_id, text, node_type)
        lines.append(f"    {node_def}")

    lines.append("")

    # Edge definitions
    for edge in edges:
        from_id = id_map.get(edge.get("from", ""), f"{node_prefix}{_safe_id(edge.get('from', ''))}")
        to_id = id_map.get(edge.get("to", ""), f"{node_prefix}{_safe_id(edge.get('to', ''))}")
        label = edge.get("label")
        confidence = edge.get("confidence", 1.0)
        evidence = edge.get("evidence", "")

        if not from_id or not to_id:
            continue
        if from_id not in node_ids or to_id not in node_ids:
            # Reference to unknown node - skip with comment
            lines.append(f"    %% UNRESOLVED edge: {from_id} -> {to_id}")
            continue

        # Choose arrow style based on confidence
        if confidence < 0.5:
            arrow = " -.-> "
            lines.append(f"    %% inferred_by_claude confidence={confidence:.2f} evidence=\"{evidence}\"")
        elif confidence < 0.8:
            arrow = " -.-> "
            lines.append(f"    %% inferred_by_claude confidence={confidence:.2f}")
        else:
            arrow = " --> "

        if label:
            safe_label = _escape_label(label)
            lines.append(f"    {from_id}{arrow}|\"{safe_label}\"| {to_id}")
        else:
            lines.append(f"    {from_id}{arrow}{to_id}")

    return lines


def _build_from_ooxml(sheet: SheetData, node_prefix: str = "") -> list[str]:
    """Build Mermaid from raw OOXML shapes and connectors (fallback)."""
    lines = []
    lines.append(f"    %% Generated from OOXML (no Claude analysis)")

    if not sheet.shapes:
        lines.append(f"    %% No shapes in sheet")
        return lines

    # Build shape ID map
    shape_id_map = {}  # excel shape_id -> safe mermaid id
    for shape in sheet.shapes:
        safe_id = f"{node_prefix}S{shape.shape_id}"
        shape_id_map[shape.shape_id] = safe_id

        text = shape.text if shape.text else shape.name
        if not text:
            continue

        # Skip edge labels and containers (they clutter the Mermaid)
        role = getattr(shape, "_role_candidate", "unknown")
        if role in ("edge_label", "ignored"):
            lines.append(f"    %% skipped {safe_id} (role={role}): {text[:30]}")
            continue

        text = _escape_label(text)
        node_type = _infer_type_from_geometry(shape.geometry, shape.text)
        node_def = _format_node(safe_id, text, node_type)
        lines.append(f"    {node_def}")

    lines.append("")

    # Edges from connectors
    edges_added = set()
    for conn in sheet.connectors:
        src_id = shape_id_map.get(conn.start_shape_id)
        dst_id = shape_id_map.get(conn.end_shape_id)

        if not src_id or not dst_id:
            lines.append(f"    %% UNRESOLVED connector: {conn.name} "
                         f"(start={conn.start_shape_id}, end={conn.end_shape_id})")
            continue

        if src_id == dst_id:
            continue

        edge_key = (src_id, dst_id)
        if edge_key in edges_added:
            continue
        edges_added.add(edge_key)

        lines.append(f"    %% source=ooxml connector_id={conn.connector_id}")
        if conn.inferred:
            arrow = " -.-> "
        else:
            arrow = " --> "

        if conn.label:
            safe_label = _escape_label(conn.label)
            lines.append(f"    {src_id}{arrow}|\"{safe_label}\"| {dst_id}")
        else:
            lines.append(f"    {src_id}{arrow}{dst_id}")

    return lines


def _format_node(node_id: str, label: str, node_type: str) -> str:
    """Format a Mermaid node definition with appropriate shape."""
    if node_type in ("start", "end"):
        return f'{node_id}(["{label}"])'
    elif node_type == "decision":
        return f'{node_id}{{"{label}"}}'
    elif node_type == "data":
        return f'{node_id}[/"{label}"/]'
    elif node_type == "subroutine":
        return f'{node_id}[["{label}"]]'
    elif node_type == "annotation":
        return f'{node_id}>"{label}"]'
    elif node_type in ("loop_start", "loop_end"):
        return f'{node_id}[["{label}"]]'
    else:  # process, unknown
        return f'{node_id}["{label}"]'


def _safe_id(text: str) -> str:
    """Convert text to safe Mermaid node ID (ASCII only)."""
    if not text:
        return "UNKNOWN"
    # Keep only alphanumeric and underscore
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", text)
    # Remove leading digits
    if safe and safe[0].isdigit():
        safe = "N" + safe
    # Truncate
    safe = safe[:40]
    # Remove trailing underscores
    safe = safe.rstrip("_")
    return safe if safe else "UNKNOWN"


def _escape_label(text: str) -> str:
    """Escape text for use as Mermaid label."""
    if not text:
        return ""
    # Replace newlines with <br/>
    text = text.replace("\r\n", "<br/>").replace("\n", "<br/>").replace("\r", "<br/>")
    # Escape quotes
    text = text.replace('"', "'")
    # Remove/replace other problematic characters
    text = text.replace("#", "＃")
    text = text.replace("&", "＆")
    # Truncate very long labels
    if len(text) > 80:
        text = text[:77] + "..."
    return text


def _infer_type_from_geometry(geometry: Optional[str], text: Optional[str]) -> str:
    """Infer node type from Excel shape geometry preset."""
    geo = (geometry or "").lower()
    txt = (text or "").lower()

    if "terminator" in geo:
        return "start"
    elif "decision" in geo or "diamond" in geo:
        return "decision"
    elif "document" in geo:
        return "data"
    elif "parallelogram" in geo or "data" in geo:
        return "data"
    elif "predefined" in geo:
        return "subroutine"
    elif any(k in txt for k in ["判定", "確認", "場合", "分岐", "条件"]):
        return "decision"
    elif any(k in txt for k in ["開始", "start", "begin"]):
        return "start"
    elif any(k in txt for k in ["終了", "end", "完了"]):
        return "end"
    else:
        return "process"
