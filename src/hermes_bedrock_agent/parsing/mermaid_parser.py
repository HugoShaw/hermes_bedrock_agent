"""Mermaid flowchart parser — extract structure from .mmd files."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


class MermaidNode(BaseModel):
    id: str
    label: str
    node_type: str  # "process", "decision", "subprocess", "terminal", "annotation"
    subgraph: Optional[str] = None


class MermaidEdge(BaseModel):
    source: str
    target: str
    label: Optional[str] = None


class MermaidSubgraph(BaseModel):
    id: str
    label: str
    nodes: list[str] = Field(default_factory=list)


class MermaidParseResult(BaseModel):
    source_path: str
    source_type: str  # "mmd_file" or "markdown_block"
    title: Optional[str] = None
    diagram_type: str  # "flowchart", "sequenceDiagram", etc.
    nodes: list[MermaidNode] = Field(default_factory=list)
    edges: list[MermaidEdge] = Field(default_factory=list)
    subgraphs: list[MermaidSubgraph] = Field(default_factory=list)
    raw_content: str
    markdown_summary: str = ""
    output_dir: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Regex patterns for Mermaid syntax
# ─────────────────────────────────────────────────────────────────────────────

# Node definitions: N69["label"], N14{"label"}, N3(["label"]), N5[["label"]]
_RE_NODE_SQUARE = re.compile(r'^\s*([A-Za-z0-9_]+)\["(.+?)"\]')
_RE_NODE_DIAMOND = re.compile(r'^\s*([A-Za-z0-9_]+)\{"(.+?)"\}')
_RE_NODE_STADIUM = re.compile(r'^\s*([A-Za-z0-9_]+)\(\["(.+?)"\]\)')
_RE_NODE_SUBROUTINE = re.compile(r'^\s*([A-Za-z0-9_]+)\[\["(.+?)"\]\]')

# Edges: N3 --> N69, N14 -->|"label"| N28, A252 -. 注釈 .- N29
_RE_EDGE_ARROW = re.compile(
    r'^\s*([A-Za-z0-9_]+)\s+'
    r'(-+>|=+>|--+>|-\.+->?|=\.+=>?)'
    r'(?:\|"(.+?)"\|)?\s*'
    r'([A-Za-z0-9_]+)'
)
_RE_EDGE_DOTTED = re.compile(
    r'^\s*([A-Za-z0-9_]+)\s+-\.\s*(.+?)\s*\.-\s*([A-Za-z0-9_]+)'
)

# Subgraph: subgraph R74["label"]
_RE_SUBGRAPH = re.compile(r'^\s*subgraph\s+([A-Za-z0-9_]+)\["(.+?)"\]')
_RE_SUBGRAPH_PLAIN = re.compile(r'^\s*subgraph\s+([A-Za-z0-9_]+)\s*$')
_RE_END = re.compile(r'^\s*end\s*$')

# Diagram type line
_RE_DIAGRAM_TYPE = re.compile(r'^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie)\s*(TD|TB|BT|LR|RL)?\s*$')

# classDef / class lines (skip)
_RE_CLASSDEF = re.compile(r'^\s*classDef\s+')
_RE_CLASS = re.compile(r'^\s*class\s+')


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────


def _detect_node_type(line: str, node_id: str) -> str:
    """Detect the node type from Mermaid syntax shape."""
    if re.search(rf'{re.escape(node_id)}\{{".+?"\}}', line):
        return "decision"
    if re.search(rf'{re.escape(node_id)}\(\[".+?"\]\)', line):
        return "terminal"
    if re.search(rf'{re.escape(node_id)}\[\[".+?"\]\]', line):
        return "subprocess"
    if node_id.startswith("A"):
        return "annotation"
    return "process"


def _clean_label(label: str) -> str:
    """Remove HTML tags like <br/> from labels."""
    return re.sub(r'<br\s*/?>', '\n', label).strip()


def _parse_content(content: str) -> tuple[str, list[MermaidNode], list[MermaidEdge], list[MermaidSubgraph]]:
    """Parse Mermaid content and extract structure."""
    nodes: dict[str, MermaidNode] = {}
    edges: list[MermaidEdge] = []
    subgraphs: dict[str, MermaidSubgraph] = {}
    subgraph_stack: list[str] = []
    diagram_type = "flowchart"

    lines = content.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue

        # Skip style lines
        if _RE_CLASSDEF.match(line) or _RE_CLASS.match(line):
            continue

        # Diagram type
        m = _RE_DIAGRAM_TYPE.match(line)
        if m:
            diagram_type = m.group(1)
            continue

        # Subgraph start
        m = _RE_SUBGRAPH.match(line)
        if m:
            sg_id, sg_label = m.group(1), _clean_label(m.group(2))
            subgraphs[sg_id] = MermaidSubgraph(id=sg_id, label=sg_label)
            subgraph_stack.append(sg_id)
            continue

        m = _RE_SUBGRAPH_PLAIN.match(line)
        if m:
            sg_id = m.group(1)
            subgraphs[sg_id] = MermaidSubgraph(id=sg_id, label=sg_id)
            subgraph_stack.append(sg_id)
            continue

        # Subgraph end
        if _RE_END.match(line):
            if subgraph_stack:
                subgraph_stack.pop()
            continue

        # Dotted edge with label (A252 -. 注釈 .- N29)
        m = _RE_EDGE_DOTTED.match(line)
        if m:
            src, lbl, tgt = m.group(1), m.group(2), m.group(3)
            edges.append(MermaidEdge(source=src, target=tgt, label=lbl))
            # Ensure nodes exist
            for nid in (src, tgt):
                if nid not in nodes:
                    nodes[nid] = MermaidNode(
                        id=nid, label=nid, node_type="annotation" if nid.startswith("A") else "process",
                        subgraph=subgraph_stack[-1] if subgraph_stack else None,
                    )
            continue

        # Arrow edge
        m = _RE_EDGE_ARROW.match(line)
        if m:
            src, _, lbl, tgt = m.group(1), m.group(2), m.group(3), m.group(4)
            edges.append(MermaidEdge(source=src, target=tgt, label=lbl))
            # Ensure nodes exist
            for nid in (src, tgt):
                if nid not in nodes:
                    nodes[nid] = MermaidNode(
                        id=nid, label=nid, node_type="process",
                        subgraph=subgraph_stack[-1] if subgraph_stack else None,
                    )
            continue

        # Node definitions (try all shapes)
        node_id = None
        node_label = None
        for pat in (_RE_NODE_STADIUM, _RE_NODE_SUBROUTINE, _RE_NODE_DIAMOND, _RE_NODE_SQUARE):
            m = pat.match(line)
            if m:
                node_id, node_label = m.group(1), m.group(2)
                break

        if node_id and node_label:
            ntype = _detect_node_type(line, node_id)
            current_sg = subgraph_stack[-1] if subgraph_stack else None
            nodes[node_id] = MermaidNode(
                id=node_id, label=_clean_label(node_label), node_type=ntype, subgraph=current_sg,
            )
            if current_sg and current_sg in subgraphs:
                if node_id not in subgraphs[current_sg].nodes:
                    subgraphs[current_sg].nodes.append(node_id)

    # Assign nodes to subgraphs based on their subgraph field
    for node in nodes.values():
        if node.subgraph and node.subgraph in subgraphs:
            if node.id not in subgraphs[node.subgraph].nodes:
                subgraphs[node.subgraph].nodes.append(node.id)

    return diagram_type, list(nodes.values()), edges, list(subgraphs.values())


def _generate_markdown_summary(
    diagram_type: str,
    nodes: list[MermaidNode],
    edges: list[MermaidEdge],
    subgraphs: list[MermaidSubgraph],
    source_path: str,
) -> str:
    """Generate a human-readable Markdown summary of the parsed Mermaid structure."""
    lines: list[str] = []
    lines.append(f"# Mermaid Flowchart Analysis")
    lines.append(f"")
    lines.append(f"**Source:** `{source_path}`  ")
    lines.append(f"**Diagram type:** {diagram_type}  ")
    lines.append(f"**Nodes:** {len(nodes)} | **Edges:** {len(edges)} | **Subgraphs:** {len(subgraphs)}")
    lines.append("")

    # Subgraphs (functional modules)
    if subgraphs:
        lines.append("## Functional Modules (Subgraphs)")
        lines.append("")
        for sg in subgraphs:
            lines.append(f"### {sg.label}")
            sg_nodes = [n for n in nodes if n.subgraph == sg.id]
            if sg_nodes:
                for n in sg_nodes:
                    type_marker = {"decision": "◇", "terminal": "◎", "subprocess": "▣", "annotation": "📝"}.get(n.node_type, "□")
                    lines.append(f"- {type_marker} `{n.id}` — {n.label}")
            lines.append("")

    # Standalone nodes
    standalone = [n for n in nodes if not n.subgraph]
    if standalone:
        lines.append("## Standalone Nodes")
        lines.append("")
        for n in standalone:
            type_marker = {"decision": "◇", "terminal": "◎", "subprocess": "▣", "annotation": "📝"}.get(n.node_type, "□")
            lines.append(f"- {type_marker} `{n.id}` — {n.label}")
        lines.append("")

    # Decision nodes summary
    decisions = [n for n in nodes if n.node_type == "decision"]
    if decisions:
        lines.append("## Decision Points")
        lines.append("")
        for d in decisions:
            outgoing = [e for e in edges if e.source == d.id]
            lines.append(f"- **{d.label}** (`{d.id}`)")
            for e in outgoing:
                target_node = next((n for n in nodes if n.id == e.target), None)
                target_label = target_node.label if target_node else e.target
                lines.append(f"  - {e.label or '→'} → {target_label}")
        lines.append("")

    # Edge summary (data flow)
    if edges:
        lines.append("## Edge Relationships")
        lines.append("")
        lines.append(f"Total edges: {len(edges)}")
        lines.append("")
        labeled_edges = [e for e in edges if e.label]
        if labeled_edges:
            lines.append("### Labeled transitions:")
            lines.append("")
            for e in labeled_edges:
                src_node = next((n for n in nodes if n.id == e.source), None)
                tgt_node = next((n for n in nodes if n.id == e.target), None)
                src_label = src_node.label if src_node else e.source
                tgt_label = tgt_node.label if tgt_node else e.target
                lines.append(f"- {src_label} —[{e.label}]→ {tgt_label}")
            lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def parse_mermaid_file(file_path: str, output_dir: str) -> MermaidParseResult:
    """Parse a .mmd file and produce structured output.

    Outputs:
        {output_dir}/mermaid_raw.mmd — verbatim copy
        {output_dir}/mermaid_parsed.md — human-readable summary
        {output_dir}/mermaid_structure.json — machine-readable structure
    """
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    diagram_type, nodes, edges, subgraphs = _parse_content(content)

    title = None
    for sg in subgraphs:
        if sg.label:
            title = f"Flowchart: {sg.label.split('：')[0] if '：' in sg.label else sg.label}"
            break

    md_summary = _generate_markdown_summary(diagram_type, nodes, edges, subgraphs, file_path)

    result = MermaidParseResult(
        source_path=file_path,
        source_type="mmd_file",
        title=title,
        diagram_type=diagram_type,
        nodes=nodes,
        edges=edges,
        subgraphs=subgraphs,
        raw_content=content,
        markdown_summary=md_summary,
        output_dir=output_dir,
    )

    # Write outputs
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    shutil.copy2(file_path, out / "mermaid_raw.mmd")

    (out / "mermaid_parsed.md").write_text(md_summary, encoding="utf-8")

    structure = {
        "source_path": file_path,
        "diagram_type": diagram_type,
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
        "subgraphs": [sg.model_dump() for sg in subgraphs],
    }
    (out / "mermaid_structure.json").write_text(
        json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info(
        "Parsed %s: %d nodes, %d edges, %d subgraphs → %s",
        path.name, len(nodes), len(edges), len(subgraphs), output_dir,
    )
    return result


def detect_mermaid_in_markdown(file_path: str) -> list[str]:
    """Detect ```mermaid code blocks in a Markdown file.

    Returns list of extracted Mermaid code strings.
    """
    content = Path(file_path).read_text(encoding="utf-8")
    blocks: list[str] = []
    in_block = False
    current: list[str] = []

    for line in content.splitlines():
        if re.match(r'^```mermaid', line.strip()):
            in_block = True
            current = []
        elif in_block and line.strip() == "```":
            in_block = False
            blocks.append("\n".join(current))
        elif in_block:
            current.append(line)

    return blocks
