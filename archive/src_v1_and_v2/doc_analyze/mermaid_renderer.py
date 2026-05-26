"""Convert AnalysisResult to a Mermaid flowchart."""

from __future__ import annotations

from hermes_bedrock_agent.doc_analyze.analyzer import AnalysisResult


# ---------------------------------------------------------------------------
# Node style definitions
# ---------------------------------------------------------------------------

_CLASS_DEFS = {
    "company":    "fill:#4A90D9,color:#fff,stroke:#2C5F8A",
    "subsidiary": "fill:#7BB3E8,color:#fff,stroke:#4A90D9",
    "system":     "fill:#50C878,color:#fff,stroke:#2D8A4E",
    "module":     "fill:#90EE90,color:#333,stroke:#50C878",
    "department": "fill:#FFB347,color:#fff,stroke:#E07000",
    "team":       "fill:#FFD580,color:#333,stroke:#FFB347",
    "other":      "fill:#D3D3D3,color:#333,stroke:#A0A0A0",
}

# Which subgraph each type belongs to (None = ungrouped)
_TYPE_TO_SUBGRAPH: dict[str, str | None] = {
    "company":    "Companies",
    "subsidiary": "Companies",
    "system":     "Systems",
    "module":     "Systems",
    "department": "Departments",
    "team":       "Departments",
    "other":      None,
}


def _safe_id(raw: str) -> str:
    """Make a Mermaid-safe node ID (alphanumeric + underscore)."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in raw)


def _arrow(rel_type: str, direction: str, label: str) -> str:
    """Return the Mermaid edge syntax for a relationship."""
    lbl = f'|"{label}"|' if label else ""
    if rel_type == "hierarchy":
        return f"-->{lbl}"
    if rel_type == "integration":
        return f"<-->{lbl}" if direction == "bi" else f"-->{lbl}"
    if rel_type == "data_flow":
        return f"-.->{lbl}"
    if rel_type == "business_process":
        return f"==>{lbl}"
    return f"---{lbl}"


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_mermaid(result: AnalysisResult, title: str = "Document Relationship Map") -> tuple[str, str]:
    """Return (raw_mermaid_code, full_markdown_block).

    *raw_mermaid_code* is the diagram content (no fences).
    *full_markdown_block* wraps it in ```mermaid ... ```.
    """
    lines: list[str] = []
    lines.append(f"%% Title: {title}")
    lines.append("flowchart TD")

    # --- class definitions ---------------------------------------------------
    for cls_name, style in _CLASS_DEFS.items():
        lines.append(f"    classDef {cls_name} {style}")
    lines.append("")

    # --- group entities by subgraph ------------------------------------------
    subgraph_entities: dict[str, list] = {"Companies": [], "Systems": [], "Departments": []}
    ungrouped: list = []

    for entity in result.entities:
        sg = _TYPE_TO_SUBGRAPH.get(entity.type, None)
        if sg:
            subgraph_entities[sg].append(entity)
        else:
            ungrouped.append(entity)

    # Emit subgraphs
    for sg_name, entities in subgraph_entities.items():
        if not entities:
            continue
        lines.append(f"    subgraph {sg_name}")
        for e in entities:
            node_id = _safe_id(e.id)
            display = e.name.replace('"', "'")
            lines.append(f'        {node_id}["{display}"]')
        lines.append("    end")
        lines.append("")

    # Emit ungrouped nodes
    for e in ungrouped:
        node_id = _safe_id(e.id)
        display = e.name.replace('"', "'")
        lines.append(f'    {node_id}["{display}"]')
    if ungrouped:
        lines.append("")

    # --- class assignments ---------------------------------------------------
    for entity in result.entities:
        node_id = _safe_id(entity.id)
        cls = entity.type if entity.type in _CLASS_DEFS else "other"
        lines.append(f"    class {node_id} {cls}")
    if result.entities:
        lines.append("")

    # --- relationships -------------------------------------------------------
    for rel in result.relationships:
        from_id = _safe_id(rel.from_id)
        to_id = _safe_id(rel.to_id)
        arrow = _arrow(rel.type, rel.direction, rel.label)
        lines.append(f"    {from_id} {arrow} {to_id}")

    raw_mermaid = "\n".join(lines)
    full_markdown = f"```mermaid\n{raw_mermaid}\n```"
    return raw_mermaid, full_markdown
