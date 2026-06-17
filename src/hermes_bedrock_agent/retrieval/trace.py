"""Retrieval trace collection for QA terminal debug mode."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VectorTrace:
    """Trace data from vector retrieval."""
    collection: str = ""
    project_filter: str = ""
    sheet_filter: list[int] = field(default_factory=list)
    embedding_model: str = ""
    embedding_latency_ms: float = 0.0
    search_latency_ms: float = 0.0
    raw_results_count: int = 0
    raw_results: list[dict] = field(default_factory=list)
    keyword_boost_applied: list[dict] = field(default_factory=list)
    keyword_boost_skipped: bool = False
    final_chunks_count: int = 0


@dataclass
class GraphTrace:
    """Trace data from graph retrieval."""
    query_terms: list[str] = field(default_factory=list)
    node_matches: list[dict] = field(default_factory=list)
    sheet_expansion: list[int] = field(default_factory=list)
    system_expansion: list[str] = field(default_factory=list)
    hint_quality: str = ""
    hint_quality_reason: str = ""
    business_nodes: int = 0
    business_edges: int = 0
    implementation_nodes: int = 0
    implementation_edges: int = 0
    edge_confidence_summary: dict = field(default_factory=dict)
    low_confidence_edges: list[dict] = field(default_factory=list)
    neptune_queries: int = 0
    graph_latency_ms: float = 0.0


@dataclass
class IsolationTrace:
    """Trace data for project isolation verification."""
    project_id: str = ""
    vector_isolated: bool = True
    graph_nodes_without_project_id: list[dict] = field(default_factory=list)
    cross_project_nodes: list[dict] = field(default_factory=list)
    violations_count: int = 0


@dataclass
class TimingTrace:
    """Per-stage timing breakdown."""
    graph_exploration_ms: float = 0.0
    graph_context_build_ms: float = 0.0
    vector_embedding_ms: float = 0.0
    vector_search_ms: float = 0.0
    merge_boost_ms: float = 0.0
    evidence_images_ms: float = 0.0
    answer_generation_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class HybridTrace:
    """Trace data from hybrid retrieval pipeline."""
    normalized_query: str = ""
    intent_label: str = ""
    intent_confidence: float = 0.0
    business_query: str = ""
    technical_query: str = ""
    keyword_query: str = ""
    vector_hits_count: int = 0
    keyword_hits_count: int = 0
    merged_count: int = 0
    dedup_removed: int = 0


@dataclass
class RerankTrace:
    """Trace data from reranking stage."""
    enabled: bool = False
    model_id: str = ""
    candidate_count: int = 0
    final_count: int = 0
    reranked: bool = False
    error: str = ""
    latency_ms: float = 0.0
    rank_comparison: list[dict] = field(default_factory=list)


@dataclass
class RetrievalTrace:
    """Complete retrieval trace for one query."""
    enabled: bool = False
    vector: VectorTrace = field(default_factory=VectorTrace)
    graph: GraphTrace = field(default_factory=GraphTrace)
    isolation: IsolationTrace = field(default_factory=IsolationTrace)
    timing: TimingTrace = field(default_factory=TimingTrace)
    hybrid: HybridTrace = field(default_factory=HybridTrace)
    rerank: RerankTrace = field(default_factory=RerankTrace)


class Timer:
    """Simple context-manager timer for instrumentation."""
    def __init__(self):
        self._start = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
