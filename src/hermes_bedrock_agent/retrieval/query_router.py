"""Route a query through the full evidence flow:

  User question
    → Markdown chunk retrieval (LanceDB)
    → Graph context retrieval (Neptune: business + implementation)
    → PDF/PNG evidence resolution from chunk metadata
    → Evidence pack construction
    → Multimodal VLM answer generation
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import QAAnswerResponse, QAResponse, RetrievedChunk
from .graph_retriever import DualGraphContext, fetch_dual_graph_context, fetch_graph_context
from .vector_retriever import retrieve_chunks

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    top_k: int = 5,
    include_graph: bool = True,
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    project_id: str = "",
) -> QAResponse:
    """Step 1+2: Retrieve top-K chunks and optional graph context for a query."""
    cfg = cfg or _default_config
    chunks = retrieve_chunks(query, top_k=top_k, cfg=cfg, store_path=store_path, collection=collection, project_id=project_id)

    evidence_paths = list(dict.fromkeys(c.source_pdf_s3_path for c in chunks if c.source_pdf_s3_path))
    graph_context = None
    if include_graph and chunks:
        graph_context = fetch_graph_context(chunks, query=query, project_id=project_id)

    return QAResponse(
        query=query,
        chunks=chunks,
        evidence_paths=evidence_paths,
        graph_context=graph_context,
    )


def answer(
    query: str,
    top_k: int = 5,
    include_graph: bool = True,
    include_evidence_images: bool = True,
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    project_id: str = "",
) -> QAAnswerResponse:
    """Full evidence flow: retrieve → graph → evidence images → VLM answer.

    Evidence pack sent to VLM:
      1. Markdown chunks (text retrieval)
      2. Business Semantic Graph (system architecture, data flows)
      3. Implementation Graph (APIs, fields, rules, conditions)
      4. PDF/PNG evidence (visual verification)
    """
    from .answer_generator import generate_answer, load_evidence_images

    cfg = cfg or _default_config

    # Step 1: Markdown chunk retrieval
    chunks = retrieve_chunks(query, top_k=top_k, cfg=cfg, store_path=store_path, collection=collection, project_id=project_id)
    logger.info("Retrieved %d chunks", len(chunks))

    # Step 2: Dual-layer graph context retrieval
    dual_graph: Optional[DualGraphContext] = None
    if include_graph and chunks:
        dual_graph = fetch_dual_graph_context(chunks, query=query, project_id=project_id)
        if dual_graph:
            logger.info(
                "Graph context: business=%d/%d, implementation=%d/%d (nodes/edges)",
                len(dual_graph.business.nodes), len(dual_graph.business.edges),
                len(dual_graph.implementation.nodes), len(dual_graph.implementation.edges),
            )

    # Step 3: PDF/PNG evidence resolution from chunk metadata
    evidence_images: list = []
    if include_evidence_images and chunks:
        evidence_images = load_evidence_images(chunks, cfg.project_root)
        logger.info("Loaded %d evidence image(s)", len(evidence_images))

    # Step 4: Evidence pack construction + VLM answer generation
    return generate_answer(
        query=query,
        retrieved_chunks=chunks,
        evidence_images=evidence_images,
        graph_context=dual_graph.to_merged_context() if dual_graph else None,
        business_graph=dual_graph.business if dual_graph else None,
        implementation_graph=dual_graph.implementation if dual_graph else None,
        cfg=cfg,
    )


def format_response(response: QAResponse, verbose: bool = False) -> str:
    """Format a QA response for terminal display with full evidence tracing."""
    lines: list[str] = [f"\n── Query: {response.query}", f"── Retrieved {len(response.chunks)} chunk(s)\n"]

    for i, chunk in enumerate(response.chunks, 1):
        lines.append(f"[{i}] {chunk.sheet_name} (sheet {chunk.sheet_index}) — {chunk.chunk_type}")
        lines.append(f"    Score: {chunk.score:.4f}")
        lines.append(f"    Evidence PDF: {chunk.source_pdf_s3_path}")
        if verbose:
            preview = chunk.content[:300].replace("\n", " ")
            lines.append(f"    Content: {preview}...")
        lines.append("")

    if response.evidence_paths:
        lines.append("── Evidence PDFs (traceable from chunk metadata):")
        for path in response.evidence_paths:
            lines.append(f"    {path}")
        lines.append("")

    if response.graph_context:
        lines.append(
            f"── Graph context: {len(response.graph_context.nodes)} nodes, "
            f"{len(response.graph_context.edges)} edges"
        )

    if isinstance(response, QAAnswerResponse):
        lines.extend(["", "── Generated Answer:", response.answer, ""])
        if response.evidence_images_used:
            lines.append("── Evidence images sent to VLM:")
            for p in response.evidence_images_used:
                lines.append(f"    {p}")
        if response.graph_context_text:
            lines.append(f"── Graph context text length: {len(response.graph_context_text)} chars")
        lines.append(
            f"── Tokens: {response.input_tokens} in / {response.output_tokens} out"
            f"  |  Model: {response.model_id}"
        )

    return "\n".join(lines)
