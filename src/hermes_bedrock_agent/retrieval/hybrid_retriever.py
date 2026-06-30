"""Hybrid retrieval: orchestrates vector + keyword search, merges, deduplicates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import RetrievedChunk
from .keyword_retriever import keyword_search
from .query_preprocessing import (
    QueryIntent,
    RewrittenQueries,
    detect_intent,
    normalize_query,
    rewrite_queries,
)
from .trace import HybridTrace
from .vector_retriever import retrieve_chunks

logger = logging.getLogger(__name__)


@dataclass
class HybridResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    vector_hits: list[RetrievedChunk] = field(default_factory=list)
    keyword_hits: list[RetrievedChunk] = field(default_factory=list)
    merged_count: int = 0
    dedup_removed: int = 0
    rewritten: Optional[RewrittenQueries] = None
    trace: Optional[HybridTrace] = None


def _row_to_chunk(row: dict, score: float, project_id: str) -> RetrievedChunk:
    """Convert a raw LanceDB row dict to a RetrievedChunk."""
    return RetrievedChunk(
        chunk_id=row.get("id", ""),
        content=row.get("text", ""),
        chunk_type=row.get("chunk_type", ""),
        sheet_index=row.get("sheet_index", 0),
        sheet_name=row.get("sheet_name", ""),
        score=round(score, 4),
        source_pdf_s3_path=row.get("source_pdf_s3_path", ""),
        source_excel_s3_path=row.get("source_excel_s3_path", ""),
        project_id=row.get("project_id", project_id),
        parsed_markdown_path=row.get("parsed_markdown_path", ""),
        document_id=row.get("document_id", ""),
        document_name=row.get("document_name", ""),
        document_type=row.get("document_type", ""),
        source_markdown_file=row.get("source_markdown_file", ""),
        evidence_path=row.get("evidence_path", ""),
        evidence_paths=str(row.get("evidence_paths", "")),
        source_file=row.get("source_file", ""),
        source_type=row.get("source_type", ""),
        parser_type=row.get("parser_type", ""),
    )


def hybrid_retrieve(
    query: str,
    top_k: int = 5,
    project_id: str = "",
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    debug: bool = False,
    trace: Optional[HybridTrace] = None,
) -> HybridResult:
    """Run the full hybrid retrieval pipeline.

    Pipeline:
    1. normalize_query(query)
    2. detect_intent(normalized_query)
    3. rewrite_queries(normalized_query, intent)
    4. Vector search: use original normalized query (best for embedding similarity)
    5. Keyword search: use keyword_query variant
    6. Merge results: union by chunk_id, score = max(vector_score, keyword_score * 0.9)
    7. Deduplicate by chunk_id
    8. Sort by merged score descending
    9. Return top_k with full provenance metadata
    """
    cfg = cfg or _default_config

    # Step 1: Normalize
    normalized = normalize_query(query)

    # Step 2: Detect intent
    intent = detect_intent(normalized)

    # Step 3: Rewrite queries
    rewritten = rewrite_queries(normalized, intent)

    # Populate trace if provided
    if trace is not None:
        trace.normalized_query = normalized
        trace.intent_label = intent.label
        trace.intent_confidence = intent.confidence
        trace.business_query = rewritten.business_query
        trace.technical_query = rewritten.technical_query
        trace.keyword_query = rewritten.keyword_query

    # Step 4: Vector search (uses the normalized query for best embedding similarity)
    vector_chunks = retrieve_chunks(
        query=normalized,
        top_k=top_k * 2,  # Fetch extra for better merge pool
        cfg=cfg,
        store_path=store_path,
        collection=collection,
        project_id=project_id,
    )

    # Step 5: Keyword search (uses keyword_query variant)
    keyword_raw = keyword_search(
        query=rewritten.keyword_query,
        top_k=top_k * 2,
        project_id=project_id,
        cfg=cfg,
        store_path=store_path,
        collection=collection,
    )
    keyword_chunks = [
        _row_to_chunk(row, row.get("_keyword_score", 0.0), project_id)
        for row in keyword_raw
    ]

    if trace is not None:
        trace.vector_hits_count = len(vector_chunks)
        trace.keyword_hits_count = len(keyword_chunks)

    # Step 6+7: Merge and deduplicate by chunk_id
    merged: dict[str, RetrievedChunk] = {}

    for chunk in vector_chunks:
        merged[chunk.chunk_id] = chunk

    for chunk in keyword_chunks:
        keyword_score = chunk.score * 0.9  # Slight discount for keyword-only hits
        if chunk.chunk_id in merged:
            existing = merged[chunk.chunk_id]
            if keyword_score > existing.score:
                chunk.score = round(keyword_score, 4)
                merged[chunk.chunk_id] = chunk
        else:
            chunk.score = round(keyword_score, 4)
            merged[chunk.chunk_id] = chunk

    total_before_dedup = len(vector_chunks) + len(keyword_chunks)
    dedup_removed = total_before_dedup - len(merged)

    # Step 8: Sort by score descending
    sorted_chunks = sorted(merged.values(), key=lambda c: c.score, reverse=True)

    # Step 9: Optional reranking
    from .reranker import load_rerank_config, rerank_chunks
    rerank_cfg = load_rerank_config()
    if rerank_cfg.enabled:
        candidates = sorted_chunks[:rerank_cfg.candidate_k]
        rerank_result = rerank_chunks(
            query=normalized, chunks=candidates, rerank_cfg=rerank_cfg, cfg=cfg,
        )
        final_chunks = rerank_result.chunks
    else:
        final_chunks = sorted_chunks[:top_k]

    if trace is not None:
        trace.merged_count = len(merged)
        trace.dedup_removed = dedup_removed

    return HybridResult(
        chunks=final_chunks,
        vector_hits=vector_chunks,
        keyword_hits=keyword_chunks,
        merged_count=len(merged),
        dedup_removed=dedup_removed,
        rewritten=rewritten,
        trace=trace,
    )
