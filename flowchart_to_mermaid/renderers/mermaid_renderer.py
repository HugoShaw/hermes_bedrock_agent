"""Mermaid diagram renderer: converts FlowDocument to .mmd format.

Supports:
- Nested subgraphs (via parent_group_id)
- Edge labels
- All node shapes (process, decision, api, file, terminator, loop, exception)
- Class definitions and assignments
- Proper label escaping without truncation
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, NodeType, PageFlow,
)

logger = logging.getLogger(__name__)


class MermaidRenderer:
    """Render a FlowDocument as Mermaid flowchart syntax."""

    def __init__(self, max_label_length: int = 200):
        """Initialize renderer.
        
        Args:
            max_label_length: Max label length before truncation. 
                              Set high to preserve full labels from profiles.
        """
        self.max_label_length = max_label_length

    def render(self, doc: FlowDocument, output_path: Path) -> str:
        """Render the document to Mermaid format and save to file.

        Returns the Mermaid source string.
        """
        lines = []

        # Header
        direction = doc.direction or "TD"
        lines.append(f"flowchart {direction}")
        lines.append("")

        # Process each page
        for page in doc.pages:
            # Render nodes and groups using nested subgraph approach
            lines.extend(self._render_page_content(page))
            lines.append("")

            # Render edges (including inter-group edges)
            for edge in page.edges:
                lines.append(f"    {self._render_edge(edge)}")

            lines.append("")

            # Style definitions at the end
            lines.extend(self._render_styles())
            lines.append("")

            # Apply classes
            lines.extend(self._render_class_assignments(page.nodes))

        content = "\n".join(lines)

        # Save to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Mermaid file saved: {output_path} ({len(content)} bytes)")

        return content

    def _render_page_content(self, page: PageFlow) -> list[str]:
        """Render all nodes and groups for a page with nested subgraphs."""
        lines = []
        
        # Build group hierarchy
        group_map = {g.id: g for g in page.groups}
        node_map = {n.id: n for n in page.nodes}
        
        # Find top-level groups (no parent or parent not in group_map)
        top_groups = [g for g in page.groups 
                      if not g.parent_group_id or g.parent_group_id not in group_map]
        child_groups = {g.id: [] for g in page.groups}
        for g in page.groups:
            if g.parent_group_id and g.parent_group_id in child_groups:
                child_groups[g.parent_group_id].append(g)
        
        # Track which nodes are in groups
        grouped_nodes = set()
        for g in page.groups:
            grouped_nodes.update(g.node_ids)
        
        # Render top-level groups
        for group in top_groups:
            lines.extend(self._render_group_recursive(
                group, child_groups, node_map, indent=1))
            lines.append("")
        
        # Render ungrouped nodes
        for node in page.nodes:
            if node.id not in grouped_nodes:
                lines.append(f"    {self._render_node(node)}")
        
        return lines

    def _render_group_recursive(self, group: FlowGroup, 
                                 child_groups: dict, 
                                 node_map: dict,
                                 indent: int = 1) -> list[str]:
        """Recursively render a group and its children."""
        lines = []
        prefix = "    " * indent
        label = self._escape_label(group.label)
        lines.append(f'{prefix}subgraph {group.id}["{label}"]')
        
        # Render child groups first
        for child in child_groups.get(group.id, []):
            lines.extend(self._render_group_recursive(
                child, child_groups, node_map, indent + 1))
        
        # Render nodes in this group
        inner_prefix = "    " * (indent + 1)
        for node_id in group.node_ids:
            if node_id in node_map:
                lines.append(f"{inner_prefix}{self._render_node(node_map[node_id])}")
        
        # Render intra-group edges (edges between nodes within this group)
        # These are rendered inline for clarity
        
        lines.append(f"{prefix}end")
        return lines

    def _render_styles(self) -> list[str]:
        """Generate classDef lines."""
        return [
            "    %% Style definitions",
            "    classDef api fill:#e8f1ff,stroke:#2f6fb3,color:#111;",
            "    classDef decision fill:#f2f2f2,stroke:#555,color:#111;",
            "    classDef file fill:#eeeeee,stroke:#777,color:#111;",
            "    classDef exception fill:#ffe5e5,stroke:#cc0000,color:#111;",
            "    classDef loop fill:#f0fff0,stroke:#228b22,color:#111;",
            "    classDef terminator fill:#e6e6fa,stroke:#4b0082,color:#111;",
            "    classDef uncertain stroke-dasharray: 5 5;",
        ]

    def _render_node(self, node: FlowNode) -> str:
        """Render a single node in Mermaid syntax."""
        label = self._escape_label(node.label)

        if node.type == NodeType.TERMINATOR:
            return f'{node.id}(["{label}"])'
        elif node.type == NodeType.DECISION:
            return f'{node.id}{{{{"{label}"}}}}'
        elif node.type == NodeType.LOOP:
            return f'{node.id}{{{{"{label}"}}}}'
        elif node.type == NodeType.EXCEPTION:
            return f'{node.id}["{label}"]'
        else:
            return f'{node.id}["{label}"]'

    def _render_edge(self, edge: FlowEdge) -> str:
        """Render a single edge in Mermaid syntax."""
        # Arrow style
        if edge.uncertain or edge.inferred:
            arrow = "-.->"
        else:
            arrow = "-->"

        # Edge label
        if edge.label:
            label = self._escape_edge_label(edge.label)
            return f"{edge.source} {arrow}|{label}| {edge.target}"
        else:
            return f"{edge.source} {arrow} {edge.target}"

    def _render_class_assignments(self, nodes: list[FlowNode]) -> list[str]:
        """Assign CSS classes to nodes based on type."""
        lines = []
        type_map = {
            NodeType.API: "api",
            NodeType.DECISION: "decision",
            NodeType.FILE: "file",
            NodeType.EXCEPTION: "exception",
            NodeType.LOOP: "loop",
            NodeType.TERMINATOR: "terminator",
        }

        # Group by class for compact output
        class_nodes: dict[str, list[str]] = {}
        for node in nodes:
            if node.type in type_map:
                cls = type_map[node.type]
                if cls not in class_nodes:
                    class_nodes[cls] = []
                class_nodes[cls].append(node.id)

        for cls, node_ids in class_nodes.items():
            lines.append(f"    class {','.join(node_ids)} {cls};")

        return lines

    @staticmethod
    def _escape_label(text: str) -> str:
        """Escape special Mermaid characters in labels."""
        # Replace problematic characters
        text = text.replace('"', "'")
        text = text.replace("\n", "<br/>")
        text = text.replace("#", "＃")
        return text

    @staticmethod
    def _escape_edge_label(text: str) -> str:
        """Escape edge label text."""
        text = text.replace('"', "'")
        text = text.replace("\n", " ")
        text = text.replace("#", "＃")
        return text
