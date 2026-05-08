"""Entity normalizer - deduplicate and merge similar entities."""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from hermes_bedrock_agent.s3_graph_etl.schemas import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class EntityNormalizer:
    """Normalize and deduplicate entities across chunks."""

    def normalize(
        self, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Deduplicate nodes by name (case-insensitive) and fix edge references."""
        # Group nodes by normalized name
        name_groups: dict[str, list[GraphNode]] = defaultdict(list)
        for node in nodes:
            key = self._normalize_name(node.name)
            name_groups[key].append(node)

        # Merge duplicates - keep the one with highest confidence
        merged_nodes: list[GraphNode] = []
        id_mapping: dict[str, str] = {}  # old_id -> canonical_id

        for key, group in name_groups.items():
            canonical = max(group, key=lambda n: n.confidence)
            merged_nodes.append(canonical)
            for node in group:
                id_mapping[node.id] = canonical.id

        # Fix edge references
        fixed_edges: list[GraphEdge] = []
        seen_edges: set[str] = set()
        for edge in edges:
            from_id = id_mapping.get(edge.from_id, edge.from_id)
            to_id = id_mapping.get(edge.to_id, edge.to_id)
            if from_id == to_id:
                continue  # skip self-loops from merging
            edge_key = f"{from_id}-[{edge.type}]->{to_id}"
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            fixed_edges.append(edge.model_copy(update={"from_id": from_id, "to_id": to_id}))

        logger.info("Normalized: %d -> %d nodes, %d -> %d edges",
                    len(nodes), len(merged_nodes), len(edges), len(fixed_edges))
        return merged_nodes, fixed_edges

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize entity name for deduplication."""
        name = name.lower().strip()
        name = re.sub(r"[\s_-]+", "_", name)
        return name
