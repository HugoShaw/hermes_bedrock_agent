"""Graph layout engine — node grouping, ranking, and positioning.

Provides:
- GraphLayoutEngine: layout computation for subgraphs
- Supports hierarchical, force-directed, and circular layouts
- Produces positions suitable for Mermaid / React Flow rendering
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.visualization import (
    LayoutAlgorithm,
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)

logger = get_logger(__name__)


@dataclass
class LayoutConfig:
    """Configuration for graph layout."""

    algorithm: LayoutAlgorithm = LayoutAlgorithm.HIERARCHICAL
    node_spacing_x: float = 200.0
    node_spacing_y: float = 150.0
    max_nodes_per_layer: int = 8
    center_x: float = 400.0
    center_y: float = 300.0


class GraphLayoutEngine:
    """Computes layout positions for graph visualization.

    Supports multiple layout algorithms and provides node grouping
    by type, layer, importance, and confidence.
    """

    def __init__(self, config: Optional[LayoutConfig] = None):
        self.config = config or LayoutConfig()

    def compute_layout(self, subgraph: SubgraphResult) -> SubgraphResult:
        """Compute positions for all nodes in the subgraph.

        Args:
            subgraph: SubgraphResult with nodes and edges.

        Returns:
            Updated SubgraphResult with layout_computed=True and node positions.
        """
        if not subgraph.nodes:
            return subgraph

        if self.config.algorithm == LayoutAlgorithm.HIERARCHICAL:
            nodes = self._hierarchical_layout(subgraph.nodes, subgraph.edges)
        elif self.config.algorithm == LayoutAlgorithm.CIRCULAR:
            nodes = self._circular_layout(subgraph.nodes)
        else:
            nodes = self._force_directed_layout(subgraph.nodes, subgraph.edges)

        return subgraph.model_copy(update={
            "nodes": nodes,
            "layout_computed": True,
            "layout_algorithm": self.config.algorithm,
        })

    def group_by_layer(
        self,
        nodes: list[VisualizationNode],
        edges: list[VisualizationEdge],
    ) -> dict[int, list[VisualizationNode]]:
        """Group nodes into layers based on graph distance from center.

        Layer 0 = nodes with no incoming edges or center nodes.
        Layer N = nodes reachable from layer N-1.
        """
        if not nodes:
            return {}

        # Build adjacency for BFS
        node_ids = {n.node_id for n in nodes}
        adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
        in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

        for edge in edges:
            if edge.source_id in adjacency and edge.target_id in node_ids:
                adjacency[edge.source_id].append(edge.target_id)
                in_degree[edge.target_id] = in_degree.get(edge.target_id, 0) + 1

        # BFS from root nodes (in_degree == 0)
        layers: dict[int, list[VisualizationNode]] = {}
        node_map = {n.node_id: n for n in nodes}
        visited: set[str] = set()

        # Layer 0: nodes with no incoming edges
        roots = [nid for nid, deg in in_degree.items() if deg == 0]
        if not roots:
            roots = [nodes[0].node_id]  # Fallback: first node

        current_layer = roots
        layer_idx = 0

        while current_layer:
            layers[layer_idx] = [node_map[nid] for nid in current_layer if nid in node_map]
            visited.update(current_layer)
            next_layer = []
            for nid in current_layer:
                for neighbor in adjacency.get(nid, []):
                    if neighbor not in visited:
                        next_layer.append(neighbor)
            current_layer = list(set(next_layer))
            layer_idx += 1
            if layer_idx > 20:  # Safety limit
                break

        # Add orphaned nodes to last layer
        orphaned = [n for n in nodes if n.node_id not in visited]
        if orphaned:
            layers[layer_idx] = orphaned

        return layers

    def rank_nodes(
        self,
        nodes: list[VisualizationNode],
        edges: list[VisualizationEdge],
        *,
        by: str = "degree",
    ) -> list[VisualizationNode]:
        """Rank nodes by importance metric.

        Args:
            nodes: Nodes to rank.
            edges: Edges for degree computation.
            by: Ranking criterion — 'degree', 'type', 'confidence'.

        Returns:
            Nodes sorted by importance (most important first).
        """
        if by == "degree":
            # Compute degree for each node
            degree_map: dict[str, int] = {n.node_id: 0 for n in nodes}
            for edge in edges:
                if edge.source_id in degree_map:
                    degree_map[edge.source_id] += 1
                if edge.target_id in degree_map:
                    degree_map[edge.target_id] += 1

            ranked = sorted(nodes, key=lambda n: degree_map.get(n.node_id, 0), reverse=True)
            # Update degree field
            for node in ranked:
                node.degree = degree_map.get(node.node_id, 0)
            return ranked

        elif by == "type":
            # Priority order by type
            type_priority = {
                "system": 0, "business_process": 1, "module": 2,
                "service": 3, "data_source": 4, "table": 5,
                "api": 6, "process_step": 7, "unknown": 99,
            }
            return sorted(nodes, key=lambda n: type_priority.get(n.entity_type, 50))

        elif by == "confidence":
            # Sort by confidence property if available
            def _get_confidence(n: VisualizationNode) -> float:
                try:
                    return float(n.properties.get("confidence", "0"))
                except (ValueError, TypeError):
                    return 0.0
            return sorted(nodes, key=_get_confidence, reverse=True)

        return nodes

    def limit_nodes(
        self,
        nodes: list[VisualizationNode],
        edges: list[VisualizationEdge],
        max_nodes: int,
    ) -> tuple[list[VisualizationNode], list[VisualizationEdge]]:
        """Limit the number of nodes, keeping the most important.

        Removes low-importance nodes and their orphaned edges.
        """
        if len(nodes) <= max_nodes:
            return nodes, edges

        # Rank and take top N
        ranked = self.rank_nodes(nodes, edges, by="degree")
        kept_nodes = ranked[:max_nodes]
        kept_ids = {n.node_id for n in kept_nodes}

        # Filter edges to only those connecting kept nodes
        kept_edges = [
            e for e in edges
            if e.source_id in kept_ids and e.target_id in kept_ids
        ]

        return kept_nodes, kept_edges

    def _hierarchical_layout(
        self,
        nodes: list[VisualizationNode],
        edges: list[VisualizationEdge],
    ) -> list[VisualizationNode]:
        """Assign hierarchical (top-down) positions."""
        layers = self.group_by_layer(nodes, edges)
        positioned: dict[str, VisualizationNode] = {}

        for layer_idx, layer_nodes in layers.items():
            y = self.config.center_y + layer_idx * self.config.node_spacing_y
            count = len(layer_nodes)
            start_x = self.config.center_x - (count - 1) * self.config.node_spacing_x / 2

            for i, node in enumerate(layer_nodes):
                x = start_x + i * self.config.node_spacing_x
                positioned[node.node_id] = node.model_copy(update={"x": x, "y": y})

        # Return in original order
        return [positioned.get(n.node_id, n) for n in nodes]

    def _circular_layout(self, nodes: list[VisualizationNode]) -> list[VisualizationNode]:
        """Assign circular positions."""
        count = len(nodes)
        radius = max(100, count * 30)
        result = []

        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / count
            x = self.config.center_x + radius * math.cos(angle)
            y = self.config.center_y + radius * math.sin(angle)
            result.append(node.model_copy(update={"x": x, "y": y}))

        return result

    def _force_directed_layout(
        self,
        nodes: list[VisualizationNode],
        edges: list[VisualizationEdge],
    ) -> list[VisualizationNode]:
        """Simple force-directed layout (deterministic, no simulation).

        Uses a grid-based initial placement with degree-based sizing.
        For production, client-side libraries (d3-force, dagre) are preferred.
        """
        # Start with grid placement, then adjust by degree
        count = len(nodes)
        cols = max(1, int(math.ceil(math.sqrt(count))))

        degree_map: dict[str, int] = {n.node_id: 0 for n in nodes}
        for edge in edges:
            if edge.source_id in degree_map:
                degree_map[edge.source_id] += 1
            if edge.target_id in degree_map:
                degree_map[edge.target_id] += 1

        result = []
        for i, node in enumerate(nodes):
            row = i // cols
            col = i % cols
            x = self.config.center_x + (col - cols / 2) * self.config.node_spacing_x
            y = self.config.center_y + (row - count / cols / 2) * self.config.node_spacing_y
            size = 1.0 + degree_map.get(node.node_id, 0) * 0.2
            result.append(node.model_copy(update={"x": x, "y": y, "size": size}))

        return result
