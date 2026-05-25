"""Mermaid diagram builder from Excel shapes and connectors.

Produces two variants:
- raw: faithful to Excel Shape/Connector IDs and structure
- readable: cleaned up with proper node names and grouping
"""
import re
import logging
from .models import ExcelShape, ExcelConnector, SheetData

logger = logging.getLogger(__name__)


def build_raw_mermaid(sheet: SheetData) -> str:
    """Build raw Mermaid from shapes and connectors, faithful to Excel structure."""
    if not sheet.shapes:
        return ""
    
    lines = ["flowchart TD"]
    lines.append("")
    
    # Node definitions
    lines.append("    %% === Nodes (from Excel Shapes) ===")
    shape_id_map = {}  # shape_id -> safe mermaid id
    
    for i, shape in enumerate(sheet.shapes, 1):
        safe_id = f"S{shape.shape_id}"
        shape_id_map[shape.shape_id] = safe_id
        
        label = _sanitize_label(shape.text) if shape.text else shape.name
        node_str = _format_node(safe_id, label, shape.mermaid_shape)
        lines.append(f"    {node_str}")
    
    # Also register pictures as connectable nodes
    for pic in sheet.pictures:
        safe_id = f"S{pic.picture_id}"
        shape_id_map[pic.picture_id] = safe_id
        label = _sanitize_label(pic.name)
        lines.append(f"    {safe_id}[\"{label}\"]")
    
    lines.append("")
    
    # Edge definitions
    lines.append("    %% === Edges (from Excel Connectors) ===")
    edges_added = set()
    
    for conn in sheet.connectors:
        src_id = shape_id_map.get(conn.start_shape_id)
        dst_id = shape_id_map.get(conn.end_shape_id)
        
        if not src_id or not dst_id:
            lines.append(f"    %% UNRESOLVED: {conn.name} (start={conn.start_shape_id}, end={conn.end_shape_id})")
            continue
        
        if src_id == dst_id:
            continue
        
        edge_key = (src_id, dst_id)
        if edge_key in edges_added:
            continue
        edges_added.add(edge_key)
        
        if conn.label:
            label = _sanitize_label(conn.label)
            lines.append(f"    {src_id} -->|\"{label}\"| {dst_id}")
        else:
            arrow = " -->" if conn.has_arrow else " ---"
            lines.append(f"    {src_id}{arrow} {dst_id}")
    
    lines.append("")
    return "\n".join(lines)


def build_readable_mermaid(sheet: SheetData) -> str:
    """Build readable Mermaid with cleaned labels, proper shapes, and grouping."""
    if not sheet.shapes:
        return ""
    
    lines = ["flowchart TD"]
    lines.append("")
    
    # Build shape lookup
    shape_map = {s.shape_id: s for s in sheet.shapes}
    shape_id_to_mid = {}  # shape_id -> mermaid node id
    
    # Detect groups based on position proximity and naming patterns
    groups = _detect_groups(sheet.shapes)
    
    # Assign readable IDs
    node_counter = [0]
    def next_id():
        node_counter[0] += 1
        return f"N{node_counter[0]:03d}"
    
    # Track which shapes are in groups
    grouped_shapes = set()
    for gname, shape_ids in groups.items():
        for sid in shape_ids:
            grouped_shapes.add(sid)
    
    # Output grouped shapes in subgraphs
    for gname, shape_ids in groups.items():
        safe_gname = _sanitize_label(gname)
        lines.append(f"    subgraph {next_id()}_G[\"{safe_gname}\"]")
        for sid in shape_ids:
            shape = shape_map.get(sid)
            if shape and shape.text and shape.text.strip():
                mid = next_id()
                shape_id_to_mid[sid] = mid
                label = _sanitize_label(shape.text)
                node_str = _format_node(mid, label, shape.mermaid_shape)
                lines.append(f"        {node_str}")
        lines.append("    end")
        lines.append("")
    
    # Output ungrouped shapes
    for shape in sheet.shapes:
        if shape.shape_id not in grouped_shapes:
            if not shape.text or not shape.text.strip():
                continue  # Skip decorative shapes
            mid = next_id()
            shape_id_to_mid[shape.shape_id] = mid
            label = _sanitize_label(shape.text)
            node_str = _format_node(mid, label, shape.mermaid_shape)
            lines.append(f"    {node_str}")
    
    # Include pictures as connectable nodes
    for pic in sheet.pictures:
        mid = next_id()
        shape_id_to_mid[pic.picture_id] = mid
        label = _sanitize_label(pic.name)
        lines.append(f"    {mid}[\"{label}\"]")
    
    lines.append("")
    
    # Edges
    lines.append("    %% === Connections ===")
    edges_added = set()
    
    for conn in sheet.connectors:
        src_mid = shape_id_to_mid.get(conn.start_shape_id)
        dst_mid = shape_id_to_mid.get(conn.end_shape_id)
        
        if not src_mid or not dst_mid:
            continue
        if src_mid == dst_mid:
            continue
        
        edge_key = (src_mid, dst_mid)
        if edge_key in edges_added:
            continue
        edges_added.add(edge_key)
        
        if conn.label:
            label = _sanitize_label(conn.label)
            lines.append(f"    {src_mid} -->|\"{label}\"| {dst_mid}")
        else:
            lines.append(f"    {src_mid} --> {dst_mid}")
    
    lines.append("")
    return "\n".join(lines)


def _detect_groups(shapes: list[ExcelShape]) -> dict[str, list[str]]:
    """Detect logical groups based on container shapes with 機能No labels.
    
    Uses both row AND column bounds to properly assign shapes to containers.
    Only assigns a shape to a container if it's STRICTLY inside (not the container itself).
    """
    groups = {}
    
    # Find container shapes (those with 機能No pattern)
    containers = []
    for shape in shapes:
        if not shape.text:
            continue
        if "機能No" in shape.text or "機能Ｎｏ" in shape.text:
            containers.append(shape)
    
    if not containers:
        return {}
    
    # Build a map for fast lookup
    shape_map = {s.shape_id: s for s in shapes}
    
    # For each container, find shapes strictly within its bounds
    assigned = set()
    
    for container in containers:
        if (container.from_row is None or container.to_row is None or
            container.from_col is None or container.to_col is None):
            continue
        
        group_name = container.text.split("\n")[0].strip()
        group_members = []
        
        for s in shapes:
            if s.shape_id == container.shape_id:
                continue
            if s.shape_id in assigned:
                continue
            if (s.from_row is None or s.to_row is None or
                s.from_col is None or s.to_col is None):
                continue
            
            # Check if shape is strictly within container bounds
            if (container.from_row <= s.from_row and s.to_row <= container.to_row and
                container.from_col <= s.from_col and s.to_col <= container.to_col):
                group_members.append(s.shape_id)
                assigned.add(s.shape_id)
        
        if group_members:
            groups[group_name] = group_members
    
    return groups


def _format_node(node_id: str, label: str, shape_type: str) -> str:
    """Format a Mermaid node with proper shape syntax."""
    # Escape quotes in label
    label = label.replace('"', "'")
    # Convert newlines to <br/>
    label = label.replace("\n", "<br/>")
    
    if shape_type == "diamond":
        return f'{node_id}{{"{label}"}}'
    elif shape_type == "stadium":
        return f'{node_id}(["{label}"])'
    elif shape_type == "subroutine":
        return f'{node_id}[["{label}"]]'
    elif shape_type == "parallelogram":
        return f'{node_id}[/"{label}"/]'
    elif shape_type == "doc":
        return f'{node_id}[("{label}")]'
    else:
        return f'{node_id}["{label}"]'


def _sanitize_label(text: str) -> str:
    """Sanitize text for use in Mermaid labels."""
    if not text:
        return ""
    # Remove or escape problematic characters
    text = text.replace('"', "'")
    text = text.replace("#", "＃")
    # Keep newlines as <br/> for Mermaid
    text = text.replace("\n", "<br/>")
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    return text.strip()
