"""
V2 Hybrid Context Builder — Assembles structured context from multi-path retrieval results.

Combines business graph, implementation graph, and vector evidence results
into a structured HybridContext ready for answer generation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.retrieval.business_graph_retriever import BusinessGraphRetriever
from hermes_bedrock_agent.v2.retrieval.context_reranker import ContextReranker
from hermes_bedrock_agent.v2.retrieval.evidence_coverage_stats import (
    compute_evidence_coverage_stats,
    format_evidence_coverage_context,
)
from hermes_bedrock_agent.v2.retrieval.implementation_graph_retriever import ImplementationGraphRetriever
from hermes_bedrock_agent.v2.retrieval.query_router import QueryRouter
from hermes_bedrock_agent.v2.retrieval.vector_evidence_retriever import VectorEvidenceRetriever
from hermes_bedrock_agent.v2.schemas.retrieval_schema import (
    HybridContext,
    QueryIntent,
    RetrievalPlan,
    RetrievalResult,
)


class HybridContextBuilder:
    """Assembles structured hybrid context from multi-path retrieval."""

    def __init__(
        self,
        output_dir: str | Path,
        top_k_evidence: int = 10,
        top_k_graph: int = 10,
        graph_depth: int = 1,
    ):
        self.output_dir = Path(output_dir)
        self.top_k_evidence = top_k_evidence
        self.top_k_graph = top_k_graph
        self.graph_depth = graph_depth

        # Initialize components
        self.router = QueryRouter()
        self.vector_retriever = VectorEvidenceRetriever(output_dir)
        self.business_retriever = BusinessGraphRetriever(output_dir)
        self.implementation_retriever = ImplementationGraphRetriever(output_dir)
        self.reranker = ContextReranker()

    def build_context(
        self,
        query: str,
        plan: RetrievalPlan | None = None,
    ) -> HybridContext:
        """Build structured hybrid context from query."""
        # Route query if plan not provided
        if plan is None:
            plan = self.router.route(query)

        intent = plan.intent

        # Special handling for evidence_coverage intent (P0 fix)
        if intent == 'evidence_coverage':
            return self._build_evidence_coverage_context(query, plan)

        # Execute retrieval paths
        business_result: RetrievalResult | None = None
        impl_result: RetrievalResult | None = None
        evidence_result: RetrievalResult | None = None

        if plan.need_business_graph:
            business_result = self.business_retriever.retrieve(
                query, top_k=self.top_k_graph, depth=self.graph_depth
            )

        if plan.need_implementation_graph:
            impl_result = self.implementation_retriever.retrieve(
                query, top_k=self.top_k_graph, depth=self.graph_depth
            )

        if plan.need_vector_evidence:
            evidence_result = self.vector_retriever.retrieve(
                query, top_k=self.top_k_evidence
            )

        # Also fetch evidence for matched graph nodes' evidence_chunk_ids
        graph_evidence_ids: list[str] = []
        if business_result:
            graph_evidence_ids.extend(
                business_result.metadata.get('evidence_chunk_ids', [])[:20]
            )
        if impl_result:
            graph_evidence_ids.extend(
                impl_result.metadata.get('evidence_chunk_ids', [])[:20]
            )

        # Fetch linked evidence
        linked_evidence: RetrievalResult | None = None
        if graph_evidence_ids:
            linked_evidence = self.vector_retriever.retrieve_by_chunk_ids(
                list(set(graph_evidence_ids))[:30]
            )

        # Assemble context
        business_context = self._build_business_context(business_result, intent)
        implementation_context = self._build_implementation_context(impl_result, intent)
        evidence_context = self._build_evidence_context(
            evidence_result, linked_evidence, intent
        )
        reasoning_constraints = self._build_constraints(plan, business_result, impl_result)

        # Metadata
        metadata: dict[str, Any] = {
            'intent': intent,
            'primary_path': plan.primary_path,
            'secondary_paths': plan.secondary_paths,
            'business_nodes_matched': (
                business_result.metadata.get('matched_nodes', 0)
                if business_result else 0
            ),
            'implementation_nodes_matched': (
                impl_result.metadata.get('matched_nodes', 0)
                if impl_result else 0
            ),
            'evidence_chunks_matched': (
                evidence_result.metadata.get('total_matched', 0)
                if evidence_result else 0
            ),
            'graph_evidence_fetched': len(graph_evidence_ids),
            'total_context_items': (
                len(business_context) + len(implementation_context) + len(evidence_context)
            ),
        }

        return HybridContext(
            query=query,
            business_context=business_context,
            implementation_context=implementation_context,
            evidence_context=evidence_context,
            reasoning_constraints=reasoning_constraints,
            metadata=metadata,
        )

    def _build_evidence_coverage_context(
        self,
        query: str,
        plan: RetrievalPlan,
    ) -> HybridContext:
        """Build HybridContext with evidence coverage stats injected (P0 fix).

        Instead of retrieving graph/evidence, computes actual coverage stats
        from JSONL metadata and injects them as reasoning constraints.
        """
        stats = compute_evidence_coverage_stats(self.output_dir)
        stats_text = format_evidence_coverage_context(stats)

        # Build constraints with evidence coverage facts
        constraints = [
            "IMPORTANT: This is an evidence coverage / gap analysis question.",
            "Answer using the actual evidence coverage statistics below.",
            "Do NOT say that nodes lack evidence if nodes_without_evidence_links = 0.",
            "Distinguish between: (a) missing evidence links, (b) weak evidence quality, "
            "(c) missing source documents (e.g. API docs), (d) isolated nodes.",
            "If coverage = 100%, state explicitly that no nodes/edges are missing evidence links.",
            "Then explain what DOES need manual supplement (documentation quality, not link gaps).",
            "",
            stats_text,
        ]

        return HybridContext(
            query=query,
            business_context=[],
            implementation_context=[],
            evidence_context=[],
            reasoning_constraints=constraints,
            metadata={
                'intent': 'evidence_coverage',
                'primary_path': plan.primary_path,
                'secondary_paths': plan.secondary_paths,
                'evidence_coverage_stats': stats,
                'requires_evidence_coverage_stats': True,
            },
        )

    def _build_business_context(
        self,
        result: RetrievalResult | None,
        intent: str,
    ) -> list[dict[str, Any]]:
        """Build business context section from retrieval result."""
        if not result or not result.items:
            return []

        # Separate nodes and edges
        nodes = [i for i in result.items if i.get('type') in ('node', 'neighbor', 'center_node')]
        edges = [i for i in result.items if i.get('type') == 'edge']

        # Rerank nodes
        reranked_nodes = self.reranker.rerank_graph_items(
            result.metadata.get('query', ''), nodes, intent, 'business_graph'
        )

        # Deduplicate
        seen_ids: set[str] = set()
        context_items: list[dict[str, Any]] = []

        for node in reranked_nodes[:15]:
            nid = node.get('node_id', '')
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            context_items.append({
                'type': 'business_node',
                'node_id': nid,
                'label': node.get('label', ''),
                'name': node.get('name', ''),
                'display_name': node.get('display_name', ''),
                'aliases': node.get('aliases', []),
                'relation_context': node.get('relation', ''),
            })

        # Add key edges
        for edge in edges[:10]:
            context_items.append({
                'type': 'business_edge',
                'relation_type': edge.get('relation_type', ''),
                'source_node_id': edge.get('source_node_id', ''),
                'target_node_id': edge.get('target_node_id', ''),
            })

        return context_items

    def _build_implementation_context(
        self,
        result: RetrievalResult | None,
        intent: str,
    ) -> list[dict[str, Any]]:
        """Build implementation context section from retrieval result."""
        if not result or not result.items:
            return []

        nodes = [i for i in result.items if i.get('type') in ('node', 'neighbor')]
        edges = [i for i in result.items if i.get('type') == 'edge']

        reranked_nodes = self.reranker.rerank_graph_items(
            result.metadata.get('query', ''), nodes, intent, 'implementation_graph'
        )

        seen_ids: set[str] = set()
        context_items: list[dict[str, Any]] = []

        for node in reranked_nodes[:15]:
            nid = node.get('node_id', '')
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            context_items.append({
                'type': 'implementation_node',
                'node_id': nid,
                'label': node.get('label', ''),
                'name': node.get('name', ''),
                'display_name': node.get('display_name', ''),
                'aliases': node.get('aliases', []),
                'relation_context': node.get('relation', ''),
            })

        for edge in edges[:10]:
            context_items.append({
                'type': 'implementation_edge',
                'relation_type': edge.get('relation_type', ''),
                'source_node_id': edge.get('source_node_id', ''),
                'target_node_id': edge.get('target_node_id', ''),
            })

        return context_items

    def _build_evidence_context(
        self,
        query_evidence: RetrievalResult | None,
        linked_evidence: RetrievalResult | None,
        intent: str,
    ) -> list[dict[str, Any]]:
        """Build evidence context section combining query-matched and graph-linked evidence."""
        all_chunks: list[dict[str, Any]] = []

        if query_evidence and query_evidence.items:
            all_chunks.extend(query_evidence.items)

        if linked_evidence and linked_evidence.items:
            all_chunks.extend(linked_evidence.items)

        # Deduplicate by chunk_id
        deduped = self.reranker.deduplicate_context(all_chunks, 'chunk_id')

        # Rerank evidence
        reranked = self.reranker.rerank_evidence_chunks(
            query_evidence.metadata.get('query', '') if query_evidence else '',
            deduped,
            intent,
        )

        # Limit to top items
        context_items: list[dict[str, Any]] = []
        for chunk in reranked[:15]:
            context_items.append({
                'type': 'evidence_chunk',
                'chunk_id': chunk.get('chunk_id', ''),
                'chunk_type': chunk.get('chunk_type', ''),
                'title': chunk.get('title', ''),
                'heading_path': chunk.get('heading_path', ''),
                'source_path': chunk.get('source_path', ''),
                'text': chunk.get('text', '')[:300],
                'score': chunk.get('score', 0.0),
            })

        return context_items

    def _build_constraints(
        self,
        plan: RetrievalPlan,
        business_result: RetrievalResult | None,
        impl_result: RetrievalResult | None,
    ) -> list[str]:
        """Build reasoning constraints for answer generation."""
        constraints = [
            "Answer only from retrieved evidence and graph context.",
            "Cite source_path when referencing specific evidence.",
            "This is a heuristic baseline retrieval (keyword matching, no vector embeddings).",
        ]

        # Check for API gap
        if plan.need_implementation_graph and impl_result:
            impl_labels = set()
            for item in impl_result.items:
                if item.get('type') == 'node':
                    impl_labels.add(item.get('label', ''))
            if 'API' not in impl_labels:
                constraints.append(
                    "⚠️ API node count = 0. No API documentation available in source corpus. "
                    "Cannot answer API-specific questions with full confidence."
                )

        # Business vs implementation coverage
        if business_result and not business_result.items:
            constraints.append(
                "No matching business graph nodes found. Answer relies on evidence only."
            )
        if impl_result and not impl_result.items:
            constraints.append(
                "No matching implementation graph nodes found. Answer relies on evidence only."
            )

        return constraints

    def build_debug_record(
        self,
        query: str,
        plan: RetrievalPlan,
        business_result: RetrievalResult | None,
        impl_result: RetrievalResult | None,
        evidence_result: RetrievalResult | None,
        context: HybridContext,
    ) -> dict[str, Any]:
        """Build a debug record showing full retrieval trace."""
        return {
            'query': query,
            'intent': plan.intent,
            'primary_path': plan.primary_path,
            'secondary_paths': plan.secondary_paths,
            'need_business_graph': plan.need_business_graph,
            'need_implementation_graph': plan.need_implementation_graph,
            'need_vector_evidence': plan.need_vector_evidence,
            'need_graph_expansion': plan.need_graph_expansion,
            'business_matched_nodes': (
                business_result.metadata.get('matched_nodes', 0)
                if business_result else 0
            ),
            'business_neighbor_nodes': (
                business_result.metadata.get('neighbor_nodes', 0)
                if business_result else 0
            ),
            'implementation_matched_nodes': (
                impl_result.metadata.get('matched_nodes', 0)
                if impl_result else 0
            ),
            'implementation_neighbor_nodes': (
                impl_result.metadata.get('neighbor_nodes', 0)
                if impl_result else 0
            ),
            'evidence_chunks_matched': (
                evidence_result.metadata.get('total_matched', 0)
                if evidence_result else 0
            ),
            'evidence_items_returned': len(evidence_result.items) if evidence_result else 0,
            'context_business_items': len(context.business_context),
            'context_implementation_items': len(context.implementation_context),
            'context_evidence_items': len(context.evidence_context),
            'context_total_items': context.total_items,
            'context_total_chars': context.total_chars,
            'reasoning_constraints': context.reasoning_constraints,
            'warnings': [c for c in context.reasoning_constraints if '⚠️' in c],
        }
