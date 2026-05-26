"""
V2 Context Reranker — Deterministic reranking and deduplication of retrieval results.

Reranks graph items and evidence chunks based on query relevance,
evidence quality, and intent-driven layer priorities. No LLM required.
"""

from __future__ import annotations

from typing import Any

from hermes_bedrock_agent.v2.retrieval.vector_evidence_retriever import tokenize, token_overlap_score


# Intent → layer priority (higher = more important)
INTENT_LAYER_PRIORITY = {
    'definition': {'vector_evidence': 3, 'business_graph': 2, 'implementation_graph': 1},
    'business_process': {'business_graph': 3, 'vector_evidence': 2, 'implementation_graph': 1},
    'relationship': {'business_graph': 2, 'implementation_graph': 2, 'vector_evidence': 2},
    'dependency': {'implementation_graph': 3, 'business_graph': 2, 'vector_evidence': 1},
    'api_code_db': {'implementation_graph': 3, 'vector_evidence': 2, 'business_graph': 1},
    'impact_analysis': {'business_graph': 3, 'implementation_graph': 3, 'vector_evidence': 2},
    'troubleshooting': {'vector_evidence': 3, 'implementation_graph': 2, 'business_graph': 1},
    'workflow_generation': {'business_graph': 3, 'implementation_graph': 2, 'vector_evidence': 2},
    'unknown': {'vector_evidence': 2, 'business_graph': 2, 'implementation_graph': 2},
}


class ContextReranker:
    """Deterministic reranker for retrieved graph items and evidence chunks."""

    def rerank_graph_items(
        self,
        query: str,
        items: list[dict[str, Any]],
        intent: str,
        source: str = 'business_graph',
    ) -> list[dict[str, Any]]:
        """Rerank graph items (nodes, edges, neighbors) based on relevance."""
        query_tokens = tokenize(query)
        layer_priority = INTENT_LAYER_PRIORITY.get(intent, INTENT_LAYER_PRIORITY['unknown'])
        source_boost = layer_priority.get(source, 1)

        scored: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            score = item.get('score', 0.0) * source_boost

            # Exact name match boost
            name = item.get('name', '') or item.get('display_name', '')
            name_overlap = token_overlap_score(query_tokens, name)
            score += name_overlap * 2.0

            # Type priority
            item_type = item.get('type', '')
            if item_type == 'node':
                score *= 1.5
            elif item_type == 'neighbor':
                score *= 0.7
            elif item_type == 'edge':
                score *= 0.5

            # Evidence quality boost
            evidence_ids = item.get('evidence_chunk_ids', [])
            if evidence_ids:
                score *= (1.0 + min(len(evidence_ids), 5) * 0.1)

            scored.append((score, item))

        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored]

    def rerank_evidence_chunks(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        intent: str,
    ) -> list[dict[str, Any]]:
        """Rerank evidence chunks based on relevance to query and intent."""
        query_tokens = tokenize(query)

        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in chunks:
            score = chunk.get('score', 0.0)

            # Title/heading relevance
            title = chunk.get('title', '')
            title_overlap = token_overlap_score(query_tokens, title)
            score += title_overlap * 1.5

            # Chunk type relevance based on intent
            chunk_type = chunk.get('chunk_type', '')
            if intent in ('definition', 'business_process'):
                if chunk_type in ('summary', 'section'):
                    score *= 1.3
            elif intent in ('api_code_db', 'dependency'):
                if chunk_type in ('code', 'sql', 'config'):
                    score *= 1.3
            elif intent == 'troubleshooting':
                if chunk_type in ('operation', 'config'):
                    score *= 1.2

            scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])
        return [chunk for _, chunk in scored]

    def deduplicate_context(
        self,
        items: list[dict[str, Any]],
        key_field: str = 'chunk_id',
    ) -> list[dict[str, Any]]:
        """Remove duplicate items based on a key field."""
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []

        for item in items:
            key = item.get(key_field, '')
            if not key:
                # Items without key are kept
                deduped.append(item)
                continue
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        return deduped

    def limit_noisy_items(
        self,
        items: list[dict[str, Any]],
        max_items: int = 20,
        min_score: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Remove low-scoring items and limit total count."""
        filtered = [item for item in items if item.get('score', 0.0) >= min_score]
        return filtered[:max_items]
