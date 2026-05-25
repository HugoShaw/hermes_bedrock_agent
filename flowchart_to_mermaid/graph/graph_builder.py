"""Graph builder: combine text, shapes, arrows into nodes and edges."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import networkx as nx

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, NodeType,
    PageFlow, Shape, ShapeType, TextBlock, UncertainPoint, UncertaintyType,
)

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Build a directed graph from extracted text blocks, shapes, and arrows."""

    def __init__(self, direction: str = "auto"):
        self.direction = direction

    def build(
        self,
        text_blocks: list[TextBlock],
        shapes: list[Shape],
        arrows: list[dict],
        groups: list[FlowGroup],
        page_width: int,
        page_height: int,
    ) -> tuple[list[FlowNode], list[FlowEdge], list[FlowGroup], list[UncertainPoint]]:
        """Build graph from extracted elements.

        Strategy:
        1. Match text blocks to shapes (text inside shape bbox)
        2. Create nodes from matched pairs
        3. Create nodes from unmatched text (using layout heuristics)
        4. Build edges from arrows or infer from layout
        5. Assign nodes to groups

        Returns (nodes, edges, groups, uncertain_points)
        """
        nodes = []
        edges = []
        uncertain_points = []

        # Step 1: Create nodes primarily from text blocks
        # (since our shape detection may not be perfect,
        #  we use text blocks as the primary node source)
        nodes = self._create_nodes_from_text(text_blocks, shapes)

        # Step 2: Infer edges from layout (top-to-bottom or left-to-right)
        if self.direction == "auto":
            aspect = page_width / max(page_height, 1)
            self.direction = "LR" if aspect > 1.5 else "TD"

        edges, edge_uncertain = self._infer_edges(nodes, arrows)
        uncertain_points.extend(edge_uncertain)

        # Step 3: Assign nodes to groups
        groups = self._assign_nodes_to_groups(nodes, groups)

        logger.info(
            f"Built graph: {len(nodes)} nodes, {len(edges)} edges, "
            f"{len(groups)} groups, {len(uncertain_points)} uncertain points"
        )
        return nodes, edges, groups, uncertain_points

    def _create_nodes_from_text(
        self, text_blocks: list[TextBlock], shapes: list[Shape]
    ) -> list[FlowNode]:
        """Create flow nodes from text blocks, classifying by content."""
        nodes = []
        node_idx = 0

        for tb in text_blocks:
            # Skip very short or obviously non-node text
            text = tb.text.strip()
            if len(text) < 2:
                continue
            # Skip if it looks like a pure number or page marker
            if text.isdigit() and len(text) <= 2:
                continue

            node_type = self._classify_node_type(text)

            # Find matching shape
            matched_shape = self._find_matching_shape(tb, shapes)

            # If matched to a diamond, override to decision
            if matched_shape and matched_shape.type == ShapeType.DECISION:
                node_type = NodeType.DECISION

            node_idx += 1
            nodes.append(FlowNode(
                id=f"N{node_idx:03d}",
                label=text,
                type=node_type,
                bbox=tb.bbox,
                source_text_ids=[tb.id],
                confidence=tb.confidence * 0.9,
                uncertain=tb.confidence < 0.7,
            ))

        return nodes

    def _classify_node_type(self, text: str) -> NodeType:
        """Classify node type based on text content."""
        text_lower = text.lower()

        # Terminator
        if any(kw in text for kw in ["開始", "終了", "Start", "End"]):
            return NodeType.TERMINATOR

        # Decision
        if any(kw in text for kw in ["条件", "分岐", "の場合", "判定", "チェック"]):
            return NodeType.DECISION

        # API
        if any(kw in text for kw in ["GET：", "POST：", "PUT：", "DELETE：", "API"]):
            return NodeType.API

        # File operations
        if any(kw in text for kw in ["ファイル", "読込", "書込", "読取", "削除", "移動", "圧縮"]):
            return NodeType.FILE

        # Loop
        if any(kw in text for kw in ["ループ", "繰り返"]):
            return NodeType.LOOP

        # Exception
        if any(kw in text for kw in ["例外", "エラー", "異常"]):
            return NodeType.EXCEPTION

        return NodeType.PROCESS

    def _find_matching_shape(
        self, text_block: TextBlock, shapes: list[Shape]
    ) -> Optional[Shape]:
        """Find a shape that contains this text block."""
        tx1, ty1, tx2, ty2 = text_block.bbox

        for shape in shapes:
            sx1, sy1, sx2, sy2 = shape.bbox
            # Text center should be inside shape
            tcx = (tx1 + tx2) / 2
            tcy = (ty1 + ty2) / 2
            if sx1 <= tcx <= sx2 and sy1 <= tcy <= sy2:
                return shape
        return None

    def _infer_edges(
        self, nodes: list[FlowNode], arrows: list[dict]
    ) -> tuple[list[FlowEdge], list[UncertainPoint]]:
        """Infer edges between nodes using layout heuristics.

        Since arrow detection in complex flowcharts is imperfect,
        we use a layout-based approach:
        - Sort nodes by position (y for TD, x for LR)
        - Connect adjacent nodes in sequence
        - Handle branches at decision nodes
        """
        if not nodes:
            return [], []

        edges = []
        uncertain_points = []
        edge_idx = 0

        # Sort by position
        if self.direction == "LR":
            sorted_nodes = sorted(nodes, key=lambda n: (n.bbox[0] if n.bbox else 0, n.bbox[1] if n.bbox else 0))
        else:
            sorted_nodes = sorted(nodes, key=lambda n: (n.bbox[1] if n.bbox else 0, n.bbox[0] if n.bbox else 0))

        # Connect sequential nodes
        for i in range(len(sorted_nodes) - 1):
            curr = sorted_nodes[i]
            next_node = sorted_nodes[i + 1]

            # Check spatial proximity
            if curr.bbox and next_node.bbox:
                if self.direction == "LR":
                    dist = next_node.bbox[0] - curr.bbox[2]  # horizontal gap
                else:
                    dist = next_node.bbox[1] - curr.bbox[3]  # vertical gap

                # Skip if too far apart (likely not directly connected)
                if dist > 500:
                    continue

            edge_idx += 1
            edge = FlowEdge(
                id=f"E{edge_idx:03d}",
                source=curr.id,
                target=next_node.id,
                confidence=0.6,
                inferred=True,
            )
            edges.append(edge)

            uncertain_points.append(UncertainPoint(
                type=UncertaintyType.EDGE,
                message=f"Inferred edge from layout position ({self.direction})",
                related_ids=[curr.id, next_node.id],
            ))

        return edges, uncertain_points

    def _assign_nodes_to_groups(
        self, nodes: list[FlowNode], groups: list[FlowGroup]
    ) -> list[FlowGroup]:
        """Assign nodes to groups based on bbox containment."""
        for group in groups:
            gx1, gy1, gx2, gy2 = group.bbox
            group.node_ids = []

            for node in nodes:
                if not node.bbox:
                    continue
                nx_center = (node.bbox[0] + node.bbox[2]) / 2
                ny_center = (node.bbox[1] + node.bbox[3]) / 2

                if gx1 <= nx_center <= gx2 and gy1 <= ny_center <= gy2:
                    group.node_ids.append(node.id)
                    node.group_id = group.id

        return groups
