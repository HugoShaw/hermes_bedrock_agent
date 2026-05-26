"""Hierarchy extractor - extracts CONTAINS relationships from document structure."""
from __future__ import annotations

import logging

from hermes_bedrock_agent.s3_graph_etl.schemas import (
    DocumentChunk,
    GraphEdge,
    GraphNode,
    RelationType,
)

logger = logging.getLogger(__name__)


class HierarchyExtractor:
    """Extract document hierarchy (file -> section -> subsection) as graph nodes/edges."""

    def extract(self, chunks: list[DocumentChunk]) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Extract hierarchy from a list of chunks belonging to the same file."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        if not chunks:
            return nodes, edges

        # Create a document-level node
        source_uri = chunks[0].source_uri
        source_file = chunks[0].source_file
        doc_node_id = f"doc:{source_file}"

        nodes.append(GraphNode(
            id=doc_node_id,
            label="Document",
            name=source_file,
            text=f"Document: {source_file}",
            source_uri=source_uri,
            source_file=source_file,
            confidence=1.0,
        ))

        # Create section nodes from headings
        for chunk in chunks:
            if chunk.title:
                section_id = f"section:{chunk.id}"
                nodes.append(GraphNode(
                    id=section_id,
                    label="Section",
                    name=chunk.title,
                    text=chunk.text[:200],
                    source_uri=source_uri,
                    source_file=source_file,
                    evidence_text=chunk.evidence_text,
                    confidence=chunk.confidence,
                ))
                edges.append(GraphEdge(
                    id=f"rel:{doc_node_id}->{section_id}",
                    from_id=doc_node_id,
                    to_id=section_id,
                    type=RelationType.CONTAINS,
                    evidence_text=f"Section \"{chunk.title}\" in document {source_file}",
                    confidence=1.0,
                    source_uri=source_uri,
                ))

        return nodes, edges
