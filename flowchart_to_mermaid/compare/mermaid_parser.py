"""Mermaid flowchart parser using regex-based parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ParsedNode:
    """A parsed node from Mermaid flowchart."""
    id: str
    label: str
    shape: str = "rect"  # rect, diamond, stadium, hexagon, round
    group_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedEdge:
    """A parsed edge from Mermaid flowchart."""
    source_id: str
    target_id: str
    label: Optional[str] = None
    style: str = "solid"  # solid, dashed

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedGroup:
    """A parsed subgraph group."""
    id: str
    label: str
    parent_group_id: Optional[str] = None
    node_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedGraph:
    """Complete parsed graph structure."""
    nodes: list[ParsedNode] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)
    groups: list[ParsedGroup] = field(default_factory=list)
    class_defs: dict[str, str] = field(default_factory=dict)
    class_assignments: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "groups": [g.to_dict() for g in self.groups],
            "class_defs": self.class_defs,
            "class_assignments": self.class_assignments,
        }


class MermaidParser:
    """Regex-based parser for Mermaid flowchart syntax."""

    # Node shape patterns
    SHAPE_PATTERNS = [
        # Double braces: {{label}} -> hexagon
        (r'\{\{"([^"]*?)"\}\}', "hexagon"),
        (r"\{\{([^}]*?)\}\}", "hexagon"),
        # Stadium: (["label"]) or ([label])
        (r'\(\["([^"]*?)"\]\)', "stadium"),
        (r"\(\[([^\]]*?)\]\)", "stadium"),
        # Diamond: {"label"} or {label}
        (r'\{"([^"]*?)"\}', "diamond"),
        (r"\{([^}]*?)\}", "diamond"),
        # Round: ("label") or (label)
        (r'\("([^"]*?)"\)', "round"),
        (r"\(([^)]*?)\)", "round"),
        # Rect with quotes: ["label"]
        (r'\["([^"]*?)"\]', "rect"),
        # Rect without quotes: [label]
        (r"\[([^\]]*?)\]", "rect"),
    ]

    # Edge patterns - order matters (longer patterns first)
    EDGE_PATTERNS = [
        # Dashed with label: -.->|label|
        (r"-\.->?\|([^|]*)\|", "dashed"),
        # Dashed with label: -. label .->
        (r"-\.(.+?)\.-+>", "dashed"),
        # Dashed no label: -.->
        (r"-\.->", "dashed"),
        # Solid with label: -->|label|
        (r"--+>\|([^|]*)\|", "solid"),
        # Solid with label: -- label -->
        (r"--\s+(.+?)\s*--+>", "solid"),
        # Solid no label: -->
        (r"--+>", "solid"),
    ]

    def parse(self, text: str) -> ParsedGraph:
        """Parse Mermaid flowchart text into a ParsedGraph."""
        graph = ParsedGraph()
        lines = text.split("\n")

        # Track subgraph stack for nesting
        group_stack: list[ParsedGroup] = []
        node_ids_seen: set[str] = set()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            # Skip empty lines and comments
            if not line or line.startswith("%%"):
                continue

            # Skip flowchart/graph declaration
            if re.match(r"^(flowchart|graph)\s+(TB|TD|LR|RL|BT)", line):
                continue

            # Handle classDef
            classdef_match = re.match(r"classDef\s+(\w+)\s+(.*)", line)
            if classdef_match:
                class_name = classdef_match.group(1)
                class_style = classdef_match.group(2).strip()
                graph.class_defs[class_name] = class_style
                continue

            # Handle class assignments: class nodeA,nodeB className
            class_assign_match = re.match(r"class\s+(.+?)\s+(\w+)\s*$", line)
            if class_assign_match:
                node_list_str = class_assign_match.group(1)
                class_name = class_assign_match.group(2)
                node_list = [n.strip() for n in node_list_str.split(",")]
                if class_name not in graph.class_assignments:
                    graph.class_assignments[class_name] = []
                graph.class_assignments[class_name].extend(node_list)
                continue

            # Handle triple-colon class: A:::className
            # (processed during node parsing)

            # Handle subgraph start
            if re.match(r"subgraph\s+", line):
                raw = line[len("subgraph "):].strip()
                # Check if it's ID["label"] form
                id_label_match = re.match(r'(\S+)\s*\["?([^"]*?)"?\]', raw)
                if id_label_match:
                    group_id = id_label_match.group(1)
                    group_label = id_label_match.group(2)
                else:
                    # Plain subgraph name (used as both id and label)
                    group_id = raw.split()[0] if raw else f"group_{len(graph.groups)}"
                    group_label = raw
                parent_id = group_stack[-1].id if group_stack else None
                group = ParsedGroup(
                    id=group_id, label=group_label, parent_group_id=parent_id
                )
                graph.groups.append(group)
                group_stack.append(group)
                continue

            # Handle subgraph end
            if line == "end":
                if group_stack:
                    group_stack.pop()
                continue

            # Parse edges and nodes from the line
            self._parse_line(line, graph, group_stack, node_ids_seen)

        return graph

    def _parse_line(
        self,
        line: str,
        graph: ParsedGraph,
        group_stack: list[ParsedGroup],
        node_ids_seen: set[str],
    ) -> None:
        """Parse a single line for nodes and edges."""
        # Skip style/linkStyle/direction lines
        if re.match(r"^(style|linkStyle|direction)\s+", line):
            return

        # Skip classDef/class (already handled)
        if re.match(r"^(classDef|class)\s+", line):
            return

        # Try to parse as edge chain (A --> B --> C)
        chain_elements = self._split_edge_chain(line)
        if chain_elements and len(chain_elements) >= 2:
            for element in chain_elements:
                node = self._parse_node_definition(element["node_str"])
                if node and node.id not in node_ids_seen:
                    if group_stack:
                        node.group_id = group_stack[-1].id
                        group_stack[-1].node_ids.append(node.id)
                    graph.nodes.append(node)
                    node_ids_seen.add(node.id)
                elif node and node.id in node_ids_seen:
                    # Update label if this definition has a real label
                    if group_stack:
                        grp = group_stack[-1]
                        if node.id not in grp.node_ids:
                            grp.node_ids.append(node.id)
                    if node.label != node.id:
                        for existing_node in graph.nodes:
                            if existing_node.id == node.id:
                                existing_node.label = node.label
                                existing_node.shape = node.shape
                                if group_stack:
                                    existing_node.group_id = group_stack[-1].id
                                break

            # Create edges between consecutive pairs
            for idx in range(len(chain_elements) - 1):
                src_node = self._parse_node_definition(chain_elements[idx]["node_str"])
                tgt_node = self._parse_node_definition(chain_elements[idx + 1]["node_str"])
                if src_node and tgt_node:
                    edge_info = chain_elements[idx + 1]
                    edge = ParsedEdge(
                        source_id=src_node.id,
                        target_id=tgt_node.id,
                        label=edge_info.get("edge_label"),
                        style=edge_info.get("edge_style", "solid"),
                    )
                    graph.edges.append(edge)
        else:
            # Try as standalone node definition
            node = self._parse_node_definition(line)
            if node and node.id not in node_ids_seen:
                if group_stack:
                    node.group_id = group_stack[-1].id
                    group_stack[-1].node_ids.append(node.id)
                graph.nodes.append(node)
                node_ids_seen.add(node.id)
            elif node and node.id in node_ids_seen:
                # Node already seen - update label if this definition has a real label
                if group_stack:
                    grp = group_stack[-1]
                    if node.id not in grp.node_ids:
                        grp.node_ids.append(node.id)
                # Update the existing node if this one has a proper label (not just ID)
                if node.label != node.id:
                    for existing_node in graph.nodes:
                        if existing_node.id == node.id:
                            existing_node.label = node.label
                            existing_node.shape = node.shape
                            if group_stack:
                                existing_node.group_id = group_stack[-1].id
                            elif existing_node.group_id is None and group_stack:
                                existing_node.group_id = group_stack[-1].id
                            break
                elif group_stack:
                    # Just update group_id if not already set
                    for existing_node in graph.nodes:
                        if existing_node.id == node.id and existing_node.group_id is None:
                            existing_node.group_id = group_stack[-1].id
                            break

    def _split_edge_chain(self, line: str) -> list[dict] | None:
        """Split a line into chain of nodes connected by edges.

        Returns list of dicts with keys: node_str, edge_label, edge_style
        The first element has no edge_label/edge_style (it's the source).
        """
        # Pattern to match edges in the line
        # We need to find positions of edge connectors
        edge_regex = re.compile(
            r"(-\.->?\|([^|]*)\|"  # dashed with label
            r"|-\.([^.]*?)\.-+>"   # dashed with inline label
            r"|-\.->?"             # dashed no label
            r"|--+>\|([^|]*)\|"    # solid with label
            r"|--\s+([^\s].*?)\s*--+>"  # solid with inline label
            r"|--+>)"              # solid no label
        )

        matches = list(edge_regex.finditer(line))
        if not matches:
            return None

        elements = []
        prev_end = 0

        for match in matches:
            # Node before this edge
            node_str = line[prev_end:match.start()].strip()
            if node_str:
                if not elements:
                    elements.append({"node_str": node_str})
                else:
                    # This shouldn't happen normally
                    elements.append({"node_str": node_str, "edge_label": None, "edge_style": "solid"})

            # Determine edge style and label
            full_match = match.group(0)
            edge_label = None
            edge_style = "solid"

            if "-." in full_match:
                edge_style = "dashed"
                # Check for label in dashed
                if match.group(2):
                    edge_label = match.group(2)
                elif match.group(3):
                    edge_label = match.group(3).strip()
            else:
                edge_style = "solid"
                if match.group(4):
                    edge_label = match.group(4)
                elif match.group(5):
                    edge_label = match.group(5).strip()

            prev_end = match.end()

            # The node after the edge will be picked up in the next iteration or after loop
            # Store edge info to attach to the next node
            elements.append({
                "node_str": "",  # placeholder
                "edge_label": edge_label if edge_label else None,
                "edge_style": edge_style,
            })

        # Remaining text after last edge is the last node
        remaining = line[prev_end:].strip()
        if remaining and elements:
            elements[-1]["node_str"] = remaining

        # Clean up: remove elements with empty node_str that aren't the last
        # Actually, restructure: elements should alternate node, edge-info+node
        # Let's rebuild properly
        result = []
        node_strs = []
        edge_infos = []

        pos = 0
        for match in matches:
            node_str = line[pos:match.start()].strip()
            if node_str:
                node_strs.append(node_str)

            full_match = match.group(0)
            edge_label = None
            edge_style = "solid"

            if "-." in full_match:
                edge_style = "dashed"
                if match.group(2):
                    edge_label = match.group(2)
                elif match.group(3):
                    edge_label = match.group(3).strip()
            else:
                if match.group(4):
                    edge_label = match.group(4)
                elif match.group(5):
                    edge_label = match.group(5).strip()

            edge_infos.append({"edge_label": edge_label, "edge_style": edge_style})
            pos = match.end()

        # Last node
        remaining = line[pos:].strip()
        if remaining:
            node_strs.append(remaining)

        if len(node_strs) < 2:
            return None

        # Build result
        result.append({"node_str": node_strs[0]})
        for idx, edge_info in enumerate(edge_infos):
            if idx + 1 < len(node_strs):
                result.append({
                    "node_str": node_strs[idx + 1],
                    "edge_label": edge_info["edge_label"],
                    "edge_style": edge_info["edge_style"],
                })

        return result if len(result) >= 2 else None

    def _parse_node_definition(self, text: str) -> ParsedNode | None:
        """Parse a node definition string like A["label"] or A{{"label"}}."""
        text = text.strip()
        if not text:
            return None

        # Remove trailing :::className
        class_suffix = None
        class_match = re.search(r":::(\w+)$", text)
        if class_match:
            class_suffix = class_match.group(1)
            text = text[: class_match.start()].strip()

        if not text:
            return None

        # Try to match node with shape
        # First extract ID (everything before the shape bracket)
        for pattern, shape in self.SHAPE_PATTERNS:
            # ID is alphanumeric/underscore before the shape
            full_pattern = r"^([A-Za-z_][A-Za-z0-9_]*)\s*" + pattern + r"$"
            m = re.match(full_pattern, text)
            if m:
                node_id = m.group(1)
                label = m.group(2)
                return ParsedNode(id=node_id, label=label, shape=shape)

        # Plain ID (no shape definition) - just a reference
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", text):
            return ParsedNode(id=text, label=text, shape="rect")

        return None
