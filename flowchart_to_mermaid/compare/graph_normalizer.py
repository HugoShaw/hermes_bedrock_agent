"""Graph normalizer for Mermaid parsed graphs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from flowchart_to_mermaid.compare.mermaid_parser import ParsedGraph, ParsedNode, ParsedEdge, ParsedGroup


@dataclass
class NormalizedNode:
    """A normalized node with cleaned labels."""
    original_id: str
    label: str
    label_normalized: str
    node_type: str  # terminator, decision, api, file, loop, exception, process
    group_label: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NormalizedEdge:
    """A normalized edge using labels instead of IDs."""
    source_label_normalized: str
    target_label_normalized: str
    edge_label: Optional[str] = None
    edge_label_normalized: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NormalizedGroup:
    """A normalized subgraph group."""
    label: str
    label_normalized: str
    node_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NormalizedGraph:
    """Fully normalized graph for comparison."""
    nodes: list[NormalizedNode] = field(default_factory=list)
    edges: list[NormalizedEdge] = field(default_factory=list)
    groups: list[NormalizedGroup] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "groups": [g.to_dict() for g in self.groups],
        }


class GraphNormalizer:
    """Normalizes parsed Mermaid graphs for comparison."""

    # Node type inference patterns (order matters - more specific first)
    TYPE_PATTERNS = [
        # API: GET：, POST：, PUT：, DELETE： (most specific - check first)
        (r"(GET[：:]|POST[：:]|PUT[：:]|DELETE[：:]|PATCH[：:])", "api"),
        # Loop (before terminator since ループ開始 should be loop, not terminator)
        (r"(ループ|繰り返し|LOOP|FOR|WHILE)", "loop"),
        # Exception
        (r"(例外|エラー|異常|EXCEPTION|ERROR)", "exception"),
        # File operations
        (r"(ファイル|読込|書込|削除|移動|圧縮|ダウンロード|アップロード)", "file"),
        # Decision: 条件, 分岐, の場合
        (r"(条件|分岐|の場合|判定|チェック)", "decision"),
        # Terminator: 開始 or 終了 (least specific - check last among keywords)
        (r"^(開始|終了|スタート|エンド|START|END)$", "terminator"),
        # Also match when 開始/終了 is standalone but not part of compound like ループ開始
        (r"(?<![ァ-ヶ亜-熙])(開始|終了)(?![ァ-ヶ亜-熙])", "terminator"),
    ]

    def normalize(self, parsed: ParsedGraph) -> NormalizedGraph:
        """Normalize a ParsedGraph into a NormalizedGraph."""
        result = NormalizedGraph()

        # Build group lookup: group_id -> group
        group_map: dict[str, ParsedGroup] = {g.id: g for g in parsed.groups}

        # Build node id -> node lookup
        node_map: dict[str, ParsedNode] = {n.id: n for n in parsed.nodes}

        # Normalize nodes
        for node in parsed.nodes:
            group_label = None
            if node.group_id and node.group_id in group_map:
                group_label = self._normalize_text(group_map[node.group_id].label)

            label_normalized = self._normalize_text(node.label)
            node_type = self._infer_node_type(label_normalized, node.shape)

            norm_node = NormalizedNode(
                original_id=node.id,
                label=node.label,
                label_normalized=label_normalized,
                node_type=node_type,
                group_label=group_label,
            )
            result.nodes.append(norm_node)

        # Build ID to normalized label mapping
        id_to_norm_label: dict[str, str] = {}
        for norm_node in result.nodes:
            id_to_norm_label[norm_node.original_id] = norm_node.label_normalized

        # Normalize edges
        for edge in parsed.edges:
            src_label = id_to_norm_label.get(edge.source_id, edge.source_id)
            tgt_label = id_to_norm_label.get(edge.target_id, edge.target_id)
            edge_label = edge.label
            edge_label_norm = self._normalize_text(edge.label) if edge.label else None

            norm_edge = NormalizedEdge(
                source_label_normalized=src_label,
                target_label_normalized=tgt_label,
                edge_label=edge_label,
                edge_label_normalized=edge_label_norm,
            )
            result.edges.append(norm_edge)

        # Normalize groups (with hierarchy propagation)
        # First pass: build all groups
        group_children: dict[str, list[str]] = {}  # parent_group_id -> [child_group_ids]
        for group in parsed.groups:
            if group.parent_group_id:
                if group.parent_group_id not in group_children:
                    group_children[group.parent_group_id] = []
                group_children[group.parent_group_id].append(group.id)

        for group in parsed.groups:
            group_label = group.label
            group_label_norm = self._normalize_text(group.label)

            # Collect normalized labels of nodes in this group
            node_labels = []
            for nid in group.node_ids:
                if nid in id_to_norm_label:
                    node_labels.append(id_to_norm_label[nid])
                else:
                    node_labels.append(nid)
            
            # Also include nodes from child groups
            if group.id in group_children:
                for child_gid in group_children[group.id]:
                    for child_group in parsed.groups:
                        if child_group.id == child_gid:
                            for nid in child_group.node_ids:
                                if nid in id_to_norm_label:
                                    label = id_to_norm_label[nid]
                                    if label not in node_labels:
                                        node_labels.append(label)

            norm_group = NormalizedGroup(
                label=group_label,
                label_normalized=group_label_norm,
                node_labels=node_labels,
            )
            result.groups.append(norm_group)

        return result

    def _normalize_text(self, text: str) -> str:
        """Apply normalization rules to text."""
        if not text:
            return ""

        result = text

        # Replace <br/>, <br>, \n with single space
        result = re.sub(r"<br\s*/?>", " ", result, flags=re.IGNORECASE)
        result = result.replace("\\n", " ")

        # Remove Mermaid shape wrappers and quotes that might remain
        # (shouldn't be needed if parser is correct, but defensive)
        result = result.strip('"').strip("'")

        # Normalize colons: treat : and ： as equivalent (normalize to ：)
        result = result.replace(":", "：")

        # Collapse multiple spaces to one
        result = re.sub(r"\s+", " ", result)

        # Strip leading/trailing whitespace
        result = result.strip()

        return result

    def _infer_node_type(self, label_normalized: str, shape: str) -> str:
        """Infer node type from normalized label and shape."""
        # Check against type patterns
        for pattern, node_type in self.TYPE_PATTERNS:
            if re.search(pattern, label_normalized, re.IGNORECASE):
                return node_type

        # If shape is diamond, it's likely a decision
        if shape == "diamond":
            return "decision"

        # If shape is stadium, it's likely a terminator
        if shape == "stadium":
            return "terminator"

        # Default
        return "process"
