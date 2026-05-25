"""Semantic repair: rule-based fixes for the flow graph."""

from __future__ import annotations

import logging
import re
from typing import Optional

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, NodeType,
    PageFlow, UncertainPoint, UncertaintyType,
)

logger = logging.getLogger(__name__)


class SemanticRepairer:
    """Rule-based repair of the extracted flow graph.

    Fixes common issues:
    - Merge text blocks that belong to the same node
    - Remove duplicate nodes
    - Fix node type misclassifications
    - Clean up edge connections
    """

    def repair(self, doc: FlowDocument) -> FlowDocument:
        """Apply all repair rules to the document."""
        for page in doc.pages:
            page.nodes = self._merge_adjacent_text_nodes(page.nodes)
            page.nodes = self._deduplicate_nodes(page.nodes)
            page.nodes = self._reclassify_nodes(page.nodes)
            page.edges = self._clean_edges(page.edges, page.nodes)
            page.edges = self._deduplicate_edges(page.edges)

        logger.info("Semantic repair completed")
        return doc

    def _merge_adjacent_text_nodes(self, nodes: list[FlowNode]) -> list[FlowNode]:
        """Merge nodes that are spatially adjacent and likely the same box."""
        if len(nodes) <= 1:
            return nodes

        merged = []
        used = set()

        for i, n1 in enumerate(nodes):
            if i in used:
                continue

            # Find adjacent nodes to merge
            merge_candidates = [n1]
            for j, n2 in enumerate(nodes[i+1:], start=i+1):
                if j in used:
                    continue
                if self._should_merge(n1, n2):
                    merge_candidates.append(n2)
                    used.add(j)

            if len(merge_candidates) > 1:
                merged_node = self._merge_nodes(merge_candidates)
                merged.append(merged_node)
            else:
                merged.append(n1)

        return merged

    def _should_merge(self, n1: FlowNode, n2: FlowNode) -> bool:
        """Check if two nodes should be merged (same physical box)."""
        if not n1.bbox or not n2.bbox:
            return False

        # Vertical proximity (within 30px)
        vertical_gap = abs(n2.bbox[1] - n1.bbox[3])
        horizontal_overlap = min(n1.bbox[2], n2.bbox[2]) - max(n1.bbox[0], n2.bbox[0])

        # Adjacent vertically and horizontally overlapping
        if vertical_gap < 30 and horizontal_overlap > 0:
            return True

        return False

    def _merge_nodes(self, nodes: list[FlowNode]) -> FlowNode:
        """Merge multiple nodes into one."""
        # Combine labels
        label = "\n".join(n.label for n in nodes)
        # Take union bbox
        all_x1 = min(n.bbox[0] for n in nodes if n.bbox)
        all_y1 = min(n.bbox[1] for n in nodes if n.bbox)
        all_x2 = max(n.bbox[2] for n in nodes if n.bbox)
        all_y2 = max(n.bbox[3] for n in nodes if n.bbox)

        # Reclassify merged text
        from flowchart_to_mermaid.graph.graph_builder import GraphBuilder
        builder = GraphBuilder()
        node_type = builder._classify_node_type(label)

        return FlowNode(
            id=nodes[0].id,
            label=label,
            type=node_type,
            bbox=[all_x1, all_y1, all_x2, all_y2],
            source_text_ids=[tid for n in nodes for tid in n.source_text_ids],
            confidence=min(n.confidence for n in nodes),
            group_id=nodes[0].group_id,
        )

    def _deduplicate_nodes(self, nodes: list[FlowNode]) -> list[FlowNode]:
        """Remove nodes with identical or near-identical labels."""
        seen_labels = {}
        result = []

        for node in nodes:
            # Normalize for comparison
            normalized = node.label.strip().replace(" ", "").replace("　", "")
            if normalized in seen_labels:
                # Keep the one with higher confidence
                existing_idx = seen_labels[normalized]
                if node.confidence > result[existing_idx].confidence:
                    result[existing_idx] = node
            else:
                seen_labels[normalized] = len(result)
                result.append(node)

        return result

    def _reclassify_nodes(self, nodes: list[FlowNode]) -> list[FlowNode]:
        """Re-check node type classification after merging."""
        from flowchart_to_mermaid.graph.graph_builder import GraphBuilder
        builder = GraphBuilder()

        for node in nodes:
            new_type = builder._classify_node_type(node.label)
            if new_type != NodeType.PROCESS or node.type == NodeType.UNKNOWN:
                node.type = new_type

        return nodes

    def _clean_edges(
        self, edges: list[FlowEdge], nodes: list[FlowNode]
    ) -> list[FlowEdge]:
        """Remove edges that reference non-existent nodes."""
        node_ids = {n.id for n in nodes}
        valid_edges = []

        for edge in edges:
            if edge.source in node_ids and edge.target in node_ids:
                valid_edges.append(edge)
            else:
                logger.debug(f"Removed invalid edge: {edge.source} -> {edge.target}")

        return valid_edges

    def _deduplicate_edges(self, edges: list[FlowEdge]) -> list[FlowEdge]:
        """Remove duplicate edges (same source+target)."""
        seen = set()
        result = []

        for edge in edges:
            key = (edge.source, edge.target)
            if key not in seen:
                seen.add(key)
                result.append(edge)

        return result
