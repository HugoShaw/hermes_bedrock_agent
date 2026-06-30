"""Graph display helpers for QA terminal — readable node/edge formatting.

Provides business-friendly display of graph data:
- Readable node labels (Japanese display names preferred)
- Readable relationship names
- Multiple output formats (compact, table, network, raw)
- Mermaid export capability
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


# ── Node label resolution ───────────────────────────────────────────────────────

def _best_node_label(node: dict) -> str:
    """Return the best business-readable node label.

    Priority:
    1. display_name (top-level or in properties)
    2. name (top-level or in properties)
    3. title
    4. business_name
    5. label (but only if it looks like a name, not a graph label)
    6. canonical_key
    7. shortened id
    """
    props = node.get("properties", {})

    # Priority 1: display_name
    for src in (node, props):
        val = src.get("display_name", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 2: name
    for src in (node, props):
        val = src.get("name", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 3: title
    for src in (node, props):
        val = src.get("title", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 4: business_name
    for src in (node, props):
        val = src.get("business_name", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 5: sheet_name (common in this project)
    val = props.get("sheet_name", "")
    if val and isinstance(val, str) and val.strip():
        return val.strip()

    # Priority 6: canonical_key
    for src in (node, props):
        val = src.get("canonical_key", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 7: shortened id
    node_id = node.get("id", "")
    if node_id:
        return _short_id(str(node_id))
    return "?"


def _best_node_type(node: dict) -> str:
    """Return readable node type.

    Priority:
    1. entity_type (top-level or in properties)
    2. type (top-level or in properties)
    3. first item from labels list
    4. label (single string)
    5. 'Node'
    """
    props = node.get("properties", {})

    # Priority 1: entity_type
    for src in (node, props):
        val = src.get("entity_type", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 2: type
    for src in (node, props):
        val = src.get("type", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 3: labels list
    labels = node.get("labels", [])
    if isinstance(labels, list) and labels:
        first = labels[0]
        if isinstance(first, str) and first.strip():
            return first.strip()

    # Priority 4: label (single string — common in this project)
    val = node.get("label", "")
    if val and isinstance(val, str) and val.strip():
        return val.strip()

    return "Node"


def _best_edge_label(edge: dict) -> str:
    """Return readable relationship label.

    Priority:
    1. display_name (top-level or in properties)
    2. relationship_name
    3. name
    4. relationship
    5. relationship_type
    6. edge_type
    7. type
    8. 'RELATES_TO'
    """
    props = edge.get("properties", {})

    # Priority 1: display_name
    for src in (edge, props):
        val = src.get("display_name", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 2: relationship_name
    for src in (edge, props):
        val = src.get("relationship_name", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 3: name
    for src in (edge, props):
        val = src.get("name", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 4: relationship
    val = edge.get("relationship", "")
    if val and isinstance(val, str) and val.strip():
        return val.strip()

    # Priority 5: relationship_type
    for src in (edge, props):
        val = src.get("relationship_type", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 6: edge_type
    for src in (edge, props):
        val = src.get("edge_type", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 7: type
    for src in (edge, props):
        val = src.get("type", "")
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    return "RELATES_TO"


def _short_id(value: str, max_len: int = 10) -> str:
    """Return shortened ID for fallback display.

    Example: 'apiop:sample_20260519:発注情報登録_API' -> 'apiop:samp…'
    """
    if not value:
        return "?"
    value = str(value).strip()
    if len(value) <= max_len:
        return value
    return value[:max_len] + "…"


# ── Node lookup for edge resolution ────────────────────────────────────────────

def _build_node_index(nodes: list[dict]) -> dict[str, dict]:
    """Build an id→node lookup dict for resolving edge endpoints."""
    index: dict[str, dict] = {}
    for node in nodes:
        nid = node.get("id", "")
        if nid:
            index[nid] = node
    return index


def _resolve_edge_endpoint(endpoint_id: str, node_index: dict[str, dict]) -> tuple[str, str]:
    """Resolve an edge endpoint ID to (type, name) using the node index.

    Returns (node_type, node_label) tuple.
    """
    node = node_index.get(endpoint_id)
    if node:
        return _best_node_type(node), _best_node_label(node)
    # Fallback: try to parse the ID for structure
    # Common formats: "system:project:name", "apiop:project:name"
    parts = str(endpoint_id).split(":")
    if len(parts) >= 3:
        # type:project:name — use last part as name
        return parts[0].capitalize(), parts[-1].replace("_", " ")
    elif len(parts) == 2:
        return parts[0].capitalize(), parts[1].replace("_", " ")
    return "Node", _short_id(endpoint_id, 20)


# ── Display format: compact (default) ──────────────────────────────────────────

def format_graph_compact(
    nodes: list[dict],
    edges: list[dict],
    *,
    max_edges: int = 30,
    show_raw_ids: bool = False,
) -> list[str]:
    """Format graph as compact readable lines.

    Output style:
        [FlowNode] トークン取得 --NEXT_STEP--> [APIOperation] 発注情報登録API

    With show_raw_ids=True, appends:
          raw: source_id=... target_id=...
    """
    lines: list[str] = []
    node_index = _build_node_index(nodes)

    displayed = 0
    for edge in edges:
        if displayed >= max_edges:
            remaining = len(edges) - max_edges
            lines.append(f"  ... {remaining} more graph relationships hidden. Use /trace or verbose mode to inspect all.")
            break

        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        rel = _best_edge_label(edge)

        src_type, src_name = _resolve_edge_endpoint(from_id, node_index)
        tgt_type, tgt_name = _resolve_edge_endpoint(to_id, node_index)

        lines.append(f"  [{src_type}] {src_name} --{rel}--> [{tgt_type}] {tgt_name}")

        if show_raw_ids:
            lines.append(f"    raw: source_id={from_id} target_id={to_id}")

        displayed += 1

    # Show orphan nodes (nodes not referenced in any edge)
    edge_node_ids = set()
    for edge in edges:
        edge_node_ids.add(edge.get("from", ""))
        edge_node_ids.add(edge.get("to", ""))

    orphan_nodes = [n for n in nodes if n.get("id", "") not in edge_node_ids]
    if orphan_nodes and displayed < max_edges:
        for node in orphan_nodes[:5]:
            ntype = _best_node_type(node)
            nname = _best_node_label(node)
            lines.append(f"  [{ntype}] {nname}")
            if show_raw_ids:
                lines.append(f"    raw: id={node.get('id', '?')}")
        if len(orphan_nodes) > 5:
            lines.append(f"  ... {len(orphan_nodes) - 5} more standalone nodes")

    return lines


# ── Display format: table ───────────────────────────────────────────────────────

def format_graph_table(
    nodes: list[dict],
    edges: list[dict],
    *,
    max_edges: int = 30,
) -> list[str]:
    """Format graph as aligned relationship table.

    Output:
        #   From Type       From Name             Relation              To Type         To Name
        1   FlowNode        トークン取得           NEXT_STEP             FlowNode        発注処理
    """
    lines: list[str] = []
    node_index = _build_node_index(nodes)

    if not edges:
        lines.append("  (No graph edges)")
        return lines

    # Collect rows
    rows: list[tuple[str, str, str, str, str]] = []
    for edge in edges[:max_edges]:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        rel = _best_edge_label(edge)
        src_type, src_name = _resolve_edge_endpoint(from_id, node_index)
        tgt_type, tgt_name = _resolve_edge_endpoint(to_id, node_index)
        rows.append((src_type, src_name, rel, tgt_type, tgt_name))

    # Calculate column widths (capped for readability)
    max_w = [12, 22, 20, 12, 22]
    headers = ("From Type", "From Name", "Relation", "To Type", "To Name")

    def _trunc(s: str, w: int) -> str:
        if len(s) <= w:
            return s.ljust(w)
        return s[:w - 1] + "…"

    # Header
    header = "  #   " + "  ".join(_trunc(h, max_w[i]) for i, h in enumerate(headers))
    lines.append(header)
    lines.append("  " + "─" * (len(header) - 2))

    # Rows
    for idx, (st, sn, r, tt, tn) in enumerate(rows, 1):
        num = str(idx).rjust(3)
        row = f"  {num}   {_trunc(st, max_w[0])}  {_trunc(sn, max_w[1])}  {_trunc(r, max_w[2])}  {_trunc(tt, max_w[3])}  {_trunc(tn, max_w[4])}"
        lines.append(row)

    if len(edges) > max_edges:
        lines.append(f"  ... {len(edges) - max_edges} more edges. Use /trace to inspect all.")

    return lines


# ── Display format: network (tree-like grouped by source) ───────────────────────

def format_graph_network(
    nodes: list[dict],
    edges: list[dict],
    *,
    max_edges: int = 30,
    show_raw_ids: bool = False,
) -> list[str]:
    """Format graph as tree-like network grouped by source node.

    Output:
        [FlowNode] 発注処理
          ├─ CALLS_API → [APIOperation] 発注情報登録API
          ├─ READS_DATA → [DataObject] 発注一覧
          └─ BRANCHES_TO → [FlowNode] RET作成
    """
    lines: list[str] = []
    node_index = _build_node_index(nodes)

    if not edges:
        lines.append("  (No graph edges)")
        return lines

    # Group edges by source node
    groups: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        from_id = edge.get("from", "")
        groups[from_id].append(edge)

    displayed = 0
    for from_id, group_edges in groups.items():
        if displayed >= max_edges:
            remaining = sum(len(g) for g in list(groups.values())[list(groups.keys()).index(from_id):])
            lines.append(f"  ... {remaining} more relationships hidden. Use /trace or verbose mode to inspect all.")
            break

        src_type, src_name = _resolve_edge_endpoint(from_id, node_index)
        lines.append(f"  [{src_type}] {src_name}")
        if show_raw_ids:
            lines.append(f"    id: {from_id}")

        # Deduplicate edges within group
        seen_targets: set[tuple[str, str]] = set()
        unique_edges = []
        for edge in group_edges:
            key = (edge.get("to", ""), _best_edge_label(edge))
            if key not in seen_targets:
                seen_targets.add(key)
                unique_edges.append(edge)

        for i, edge in enumerate(unique_edges):
            if displayed >= max_edges:
                lines.append(f"    ... truncated")
                break
            to_id = edge.get("to", "")
            rel = _best_edge_label(edge)
            tgt_type, tgt_name = _resolve_edge_endpoint(to_id, node_index)

            is_last = (i == len(unique_edges) - 1)
            prefix = "└─" if is_last else "├─"
            lines.append(f"    {prefix} {rel} → [{tgt_type}] {tgt_name}")
            if show_raw_ids:
                lines.append(f"       target_id: {to_id}")
            displayed += 1

    return lines


# ── Display format: raw (legacy) ───────────────────────────────────────────────

def format_graph_raw(
    nodes: list[dict],
    edges: list[dict],
) -> list[str]:
    """Format graph in legacy raw ID style (original debug format)."""
    lines: list[str] = []

    for node in nodes[:10]:
        props = node.get("properties", {})
        name = props.get("name", props.get("sheet_name", ""))
        suffix = f" — {name}" if name else ""
        lines.append(f"  ● [{node.get('label', '')}] {node.get('id', '?')}{suffix}")
    if len(nodes) > 10:
        lines.append(f"    … {len(nodes) - 10} more nodes")

    for edge in edges[:10]:
        lines.append(f"  → {edge.get('from', '?')} --{edge.get('relationship', '?')}--> {edge.get('to', '?')}")
    if len(edges) > 10:
        lines.append(f"    … {len(edges) - 10} more edges")

    return lines


# ── Mermaid export ──────────────────────────────────────────────────────────────

def export_graph_mermaid(
    nodes: list[dict],
    edges: list[dict],
    *,
    max_nodes: int = 50,
    max_edges: int = 80,
) -> str:
    """Export graph as Mermaid flowchart LR syntax.

    Returns Mermaid text using safe generated node IDs (n1, n2, ...).
    """
    node_index = _build_node_index(nodes)

    # Assign safe IDs
    id_map: dict[str, str] = {}
    counter = 0

    def _safe_mermaid_id(original_id: str) -> str:
        nonlocal counter
        if original_id not in id_map:
            counter += 1
            id_map[original_id] = f"n{counter}"
        return id_map[original_id]

    def _escape_mermaid(text: str) -> str:
        """Escape Mermaid-sensitive characters in labels."""
        return text.replace('"', "'").replace("[", "(").replace("]", ")").replace("|", "/").replace("<", "＜").replace(">", "＞")

    lines = ["flowchart LR"]

    # Collect all referenced node IDs from edges
    all_ids: set[str] = set()
    for edge in edges[:max_edges]:
        all_ids.add(edge.get("from", ""))
        all_ids.add(edge.get("to", ""))
    # Also add standalone nodes
    for node in nodes[:max_nodes]:
        all_ids.add(node.get("id", ""))

    # Node definitions
    defined: set[str] = set()
    for node_id in all_ids:
        if not node_id or node_id in defined:
            continue
        safe_id = _safe_mermaid_id(node_id)
        node = node_index.get(node_id)
        if node:
            ntype = _best_node_type(node)
            nname = _best_node_label(node)
            label = _escape_mermaid(f"{ntype}: {nname}")
        else:
            # Parse from ID
            parts = str(node_id).split(":")
            if len(parts) >= 3:
                label = _escape_mermaid(f"{parts[0].capitalize()}: {parts[-1]}")
            else:
                label = _escape_mermaid(_short_id(node_id, 20))
        lines.append(f'  {safe_id}["{label}"]')
        defined.add(node_id)

    # Edges
    for edge in edges[:max_edges]:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        rel = _best_edge_label(edge)
        if from_id and to_id:
            safe_from = _safe_mermaid_id(from_id)
            safe_to = _safe_mermaid_id(to_id)
            safe_rel = _escape_mermaid(rel)
            lines.append(f"  {safe_from} -->|{safe_rel}| {safe_to}")

    if len(edges) > max_edges:
        lines.append(f"  %% ... {len(edges) - max_edges} more edges omitted")

    return "\n".join(lines)


# ── Graph display format enum ───────────────────────────────────────────────────

GRAPH_FORMATS = ("compact", "table", "network", "raw")
DEFAULT_GRAPH_FORMAT = "compact"


def format_graph(
    nodes: list[dict],
    edges: list[dict],
    *,
    fmt: str = DEFAULT_GRAPH_FORMAT,
    show_raw_ids: bool = False,
    max_edges: int = 30,
) -> list[str]:
    """Format graph data according to the selected display format.

    Args:
        nodes: List of node dicts
        edges: List of edge dicts
        fmt: One of 'compact', 'table', 'network', 'raw'
        show_raw_ids: Whether to show raw IDs (debug/trace mode)
        max_edges: Maximum edges to display before truncation

    Returns:
        List of formatted lines (no ANSI codes — caller applies colors)
    """
    if fmt == "table":
        return format_graph_table(nodes, edges, max_edges=max_edges)
    elif fmt == "network":
        return format_graph_network(nodes, edges, max_edges=max_edges, show_raw_ids=show_raw_ids)
    elif fmt == "raw":
        return format_graph_raw(nodes, edges)
    else:  # compact (default)
        return format_graph_compact(nodes, edges, max_edges=max_edges, show_raw_ids=show_raw_ids)
