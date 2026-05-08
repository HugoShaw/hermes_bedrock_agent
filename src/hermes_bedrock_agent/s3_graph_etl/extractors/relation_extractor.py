"""Relation extractor - extract entity relations from chunks using LLM or rules."""
from __future__ import annotations

import logging
from typing import Any

from hermes_bedrock_agent.s3_graph_etl.schemas import (
    DetectedEntity,
    DetectedRelation,
    DocumentChunk,
    GraphEdge,
    GraphNode,
)

logger = logging.getLogger(__name__)


class RelationExtractor:
    """Extract entities and relations from DocumentChunks.

    Uses detected_entities and detected_relations from chunks
    (populated by LLM parsers) and converts them to graph nodes/edges.
    """

    def extract(self, chunks: list[DocumentChunk]) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Extract graph nodes and edges from chunk-level entity/relation detections."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_entities: dict[str, GraphNode] = {}

        for chunk in chunks:
            # Process entities
            for entity in chunk.detected_entities:
                entity_id = self._make_entity_id(entity)
                if entity_id not in seen_entities:
                    node = GraphNode(
                        id=entity_id,
                        label=entity.label,
                        name=entity.name,
                        text=entity.properties.get("description", ""),
                        source_uri=chunk.source_uri,
                        source_file=chunk.source_file,
                        evidence_text=chunk.evidence_text,
                        confidence=chunk.confidence,
                        properties=entity.properties,
                    )
                    seen_entities[entity_id] = node
                    nodes.append(node)

            # Process relations
            for relation in chunk.detected_relations:
                from_id = self._make_entity_id_from_name(relation.from_name)
                to_id = self._make_entity_id_from_name(relation.to_name)
                edge_id = f"rel:{from_id}-[{relation.relation_type}]->{to_id}"

                edges.append(GraphEdge(
                    id=edge_id,
                    from_id=from_id,
                    to_id=to_id,
                    type=relation.relation_type,
                    evidence_text=chunk.evidence_text,
                    confidence=chunk.confidence,
                    source_uri=chunk.source_uri,
                    properties=relation.properties,
                ))

        return nodes, edges

    @staticmethod
    def _make_entity_id(entity: DetectedEntity) -> str:
        """Create deterministic entity ID from label + name."""
        return f"{entity.label.lower()}:{entity.name.lower().replace(' ', '_')}"

    @staticmethod
    def _make_entity_id_from_name(name: str) -> str:
        """Create entity ID from just a name (used for relation endpoints)."""
        return f"entity:{name.lower().replace(' ', '_')}"
