"""Graph builder - assembles nodes and edges from extracted data."""
from __future__ import annotations

import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.embeddings.base_embedder import BaseEmbedder
from hermes_bedrock_agent.s3_graph_etl.extractors.entity_normalizer import EntityNormalizer
from hermes_bedrock_agent.s3_graph_etl.extractors.evidence_builder import EvidenceBuilder
from hermes_bedrock_agent.s3_graph_etl.extractors.hierarchy_extractor import HierarchyExtractor
from hermes_bedrock_agent.s3_graph_etl.extractors.relation_extractor import RelationExtractor
from hermes_bedrock_agent.s3_graph_etl.schemas import DocumentChunk, GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Build a complete graph from DocumentChunks."""

    def __init__(self, embedder: BaseEmbedder | None = None, skip_embedding: bool = False) -> None:
        self.hierarchy_extractor = HierarchyExtractor()
        self.relation_extractor = RelationExtractor()
        self.normalizer = EntityNormalizer()
        self.evidence_builder = EvidenceBuilder()
        self.embedder = embedder
        self.skip_embedding = skip_embedding

    def build(self, chunks: list[DocumentChunk]) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Build graph nodes and edges from document chunks."""
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []

        # Group chunks by source file
        by_file: dict[str, list[DocumentChunk]] = {}
        for chunk in chunks:
            by_file.setdefault(chunk.source_uri, []).append(chunk)

        # Extract hierarchy per file
        for uri, file_chunks in by_file.items():
            h_nodes, h_edges = self.hierarchy_extractor.extract(file_chunks)
            all_nodes.extend(h_nodes)
            all_edges.extend(h_edges)

        # Extract entities and relations from all chunks
        r_nodes, r_edges = self.relation_extractor.extract(chunks)
        all_nodes.extend(r_nodes)
        all_edges.extend(r_edges)

        # Normalize (deduplicate)
        all_nodes, all_edges = self.normalizer.normalize(all_nodes, all_edges)

        # Enrich with evidence
        all_nodes, all_edges = self.evidence_builder.enrich(all_nodes, all_edges)

        # Generate embeddings
        if self.embedder and not self.skip_embedding:
            all_nodes = self._add_embeddings(all_nodes)

        logger.info("Built graph: %d nodes, %d edges", len(all_nodes), len(all_edges))
        return all_nodes, all_edges

    def _add_embeddings(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """Add embeddings to nodes that have text content."""
        texts_to_embed: list[tuple[int, str]] = []
        for i, node in enumerate(nodes):
            embed_text = node.name
            if node.text:
                embed_text += " " + node.text[:500]
            texts_to_embed.append((i, embed_text))

        if not texts_to_embed:
            return nodes

        try:
            embeddings = self.embedder.embed_batch([t for _, t in texts_to_embed])
            result = list(nodes)
            for (idx, _), embedding in zip(texts_to_embed, embeddings):
                result[idx] = result[idx].model_copy(update={"embedding": embedding})
            return result
        except Exception as exc:
            logger.warning("Embedding failed, skipping: %s", exc)
            return nodes
