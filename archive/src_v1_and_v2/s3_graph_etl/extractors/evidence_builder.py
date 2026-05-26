"""Evidence builder - ensures all graph elements have proper provenance."""
from __future__ import annotations

import logging

from hermes_bedrock_agent.s3_graph_etl.schemas import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class EvidenceBuilder:
    """Ensure all nodes and edges have proper evidence and source tracking."""

    def enrich(
        self, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Add or validate evidence fields on all graph elements."""
        enriched_nodes: list[GraphNode] = []
        for node in nodes:
            if not node.evidence_text and node.text:
                node = node.model_copy(update={"evidence_text": node.text[:500]})
            enriched_nodes.append(node)

        enriched_edges: list[GraphEdge] = []
        for edge in edges:
            if not edge.evidence_text:
                edge = edge.model_copy(update={
                    "evidence_text": f"Relation {edge.type} from {edge.from_id} to {edge.to_id}"
                })
            enriched_edges.append(edge)

        return enriched_nodes, enriched_edges
