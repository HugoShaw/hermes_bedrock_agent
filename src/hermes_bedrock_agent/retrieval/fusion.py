"""Fusion — merge text and graph evidence with deduplication and ranking.

Provides:
- Reciprocal Rank Fusion (RRF)
- Weighted score fusion
- Deduplication by chunk_id / source_chunk_id / source_uri+page
- Preserves graph_paths in merged output
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.retrieval import (
    FusedContext,
    GraphEvidence,
    TextEvidence,
)

logger = get_logger(__name__)


class FusionStrategy(str, Enum):
    """Available fusion strategies."""

    RRF = "rrf"
    WEIGHTED = "weighted"
    INTERLEAVE = "interleave"


@dataclass
class FusionConfig:
    """Configuration for evidence fusion."""

    strategy: FusionStrategy = FusionStrategy.RRF
    rrf_k: int = 60  # RRF constant (standard = 60)
    text_weight: float = 0.6
    graph_weight: float = 0.4
    max_text_evidence: int = 10
    max_graph_evidence: int = 10
    deduplicate: bool = True


def fuse_evidence(
    text_evidence: list[TextEvidence],
    graph_evidence: list[GraphEvidence],
    *,
    query: str = "",
    config: Optional[FusionConfig] = None,
    kb_evidence: Optional[list[TextEvidence]] = None,
) -> FusedContext:
    """Fuse text and graph evidence into unified context.

    Deduplicates, re-ranks, and merges results from multiple retrieval
    sources into a single FusedContext for answer generation.

    Args:
        text_evidence: Results from OpenSearch text retriever.
        graph_evidence: Results from Neptune graph retriever.
        query: Original user query.
        config: Fusion configuration.
        kb_evidence: Optional results from Bedrock KB retriever.

    Returns:
        FusedContext with deduplicated, ranked evidence.
    """
    cfg = config or FusionConfig()

    # Merge KB evidence into text evidence (both are TextEvidence)
    all_text = list(text_evidence)
    if kb_evidence:
        all_text.extend(kb_evidence)

    # Deduplicate
    if cfg.deduplicate:
        all_text = _deduplicate_text_evidence(all_text)
        graph_evidence = _deduplicate_graph_evidence(graph_evidence)

    # Apply fusion strategy
    if cfg.strategy == FusionStrategy.RRF:
        all_text, graph_evidence = _apply_rrf(
            all_text, graph_evidence, rrf_k=cfg.rrf_k
        )
    elif cfg.strategy == FusionStrategy.WEIGHTED:
        all_text, graph_evidence = _apply_weighted(
            all_text, graph_evidence,
            text_weight=cfg.text_weight,
            graph_weight=cfg.graph_weight,
        )
    # INTERLEAVE: no re-scoring, just trim

    # Trim to max counts
    all_text = all_text[: cfg.max_text_evidence]
    graph_evidence = graph_evidence[: cfg.max_graph_evidence]

    # Update ranks
    for i, ev in enumerate(all_text):
        all_text[i] = ev.model_copy(update={"rank": i})
    for i, ev in enumerate(graph_evidence):
        graph_evidence[i] = ev.model_copy(update={"rank": i})

    # Estimate tokens (~4 chars per token for mixed CJK/English)
    total_chars = sum(len(e.content) for e in all_text)
    total_chars += sum(len(e.content) for e in graph_evidence)
    token_estimate = total_chars // 3  # Conservative for CJK

    return FusedContext(
        query=query,
        text_evidence=all_text,
        graph_evidence=graph_evidence,
        fusion_strategy=cfg.strategy.value,
        total_evidence_count=len(all_text) + len(graph_evidence),
        total_token_estimate=token_estimate,
    )


def _deduplicate_text_evidence(
    evidence: list[TextEvidence],
) -> list[TextEvidence]:
    """Deduplicate text evidence by chunk_id.

    Keeps the highest-scored version when duplicates exist.
    Also deduplicates by source_uri + page combination.
    """
    seen_chunk_ids: dict[str, TextEvidence] = {}
    seen_uri_pages: dict[str, TextEvidence] = {}

    for ev in evidence:
        # Primary dedup: chunk_id
        if ev.chunk_id:
            if ev.chunk_id in seen_chunk_ids:
                existing = seen_chunk_ids[ev.chunk_id]
                if ev.score > existing.score:
                    seen_chunk_ids[ev.chunk_id] = ev
            else:
                seen_chunk_ids[ev.chunk_id] = ev
            continue

        # Secondary dedup: source_uri + page
        if ev.source_uri:
            key = f"{ev.source_uri}:{ev.page or 0}"
            if key in seen_uri_pages:
                existing = seen_uri_pages[key]
                if ev.score > existing.score:
                    seen_uri_pages[key] = ev
            else:
                seen_uri_pages[key] = ev
            continue

        # No dedup key — always include
        seen_chunk_ids[ev.evidence_id] = ev

    # Merge both pools
    all_unique = list(seen_chunk_ids.values()) + list(seen_uri_pages.values())
    # Sort by score descending
    all_unique.sort(key=lambda e: e.score, reverse=True)
    return all_unique


def _deduplicate_graph_evidence(
    evidence: list[GraphEvidence],
) -> list[GraphEvidence]:
    """Deduplicate graph evidence by entity_id or path signature.

    Preserves path descriptions even when entities overlap.
    """
    seen_entities: set[str] = set()
    seen_paths: set[str] = set()
    unique: list[GraphEvidence] = []

    for ev in evidence:
        # Entity-level evidence: dedup by entity_id
        if ev.entity_id and not ev.path_description:
            if ev.entity_id in seen_entities:
                continue
            seen_entities.add(ev.entity_id)
            unique.append(ev)
            continue

        # Path-level evidence: dedup by path signature
        if ev.path_description:
            path_key = ev.path_description
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            unique.append(ev)
            continue

        # Fallback: use evidence_id
        unique.append(ev)

    return unique


def _apply_rrf(
    text_evidence: list[TextEvidence],
    graph_evidence: list[GraphEvidence],
    *,
    rrf_k: int = 60,
) -> tuple[list[TextEvidence], list[GraphEvidence]]:
    """Apply Reciprocal Rank Fusion scoring.

    RRF score = sum(1 / (k + rank_i)) across all result lists.
    """
    # Score text evidence
    text_scores: dict[int, float] = {}
    for i, ev in enumerate(text_evidence):
        text_scores[i] = 1.0 / (rrf_k + i)

    # Score graph evidence
    graph_scores: dict[int, float] = {}
    for i, ev in enumerate(graph_evidence):
        graph_scores[i] = 1.0 / (rrf_k + i)

    # Re-sort text by RRF score
    text_ranked = sorted(
        range(len(text_evidence)),
        key=lambda i: text_scores.get(i, 0),
        reverse=True,
    )
    ranked_text = []
    for idx in text_ranked:
        ev = text_evidence[idx]
        ranked_text.append(ev.model_copy(update={"score": text_scores[idx]}))

    # Re-sort graph by RRF score
    graph_ranked = sorted(
        range(len(graph_evidence)),
        key=lambda i: graph_scores.get(i, 0),
        reverse=True,
    )
    ranked_graph = []
    for idx in graph_ranked:
        ev = graph_evidence[idx]
        ranked_graph.append(ev.model_copy(update={"score": graph_scores[idx]}))

    return ranked_text, ranked_graph


def _apply_weighted(
    text_evidence: list[TextEvidence],
    graph_evidence: list[GraphEvidence],
    *,
    text_weight: float = 0.6,
    graph_weight: float = 0.4,
) -> tuple[list[TextEvidence], list[GraphEvidence]]:
    """Apply weighted score fusion."""
    weighted_text = []
    for ev in text_evidence:
        new_score = ev.score * text_weight
        weighted_text.append(ev.model_copy(update={"score": new_score}))
    weighted_text.sort(key=lambda e: e.score, reverse=True)

    weighted_graph = []
    for ev in graph_evidence:
        new_score = ev.score * graph_weight
        weighted_graph.append(ev.model_copy(update={"score": new_score}))
    weighted_graph.sort(key=lambda e: e.score, reverse=True)

    return weighted_text, weighted_graph
