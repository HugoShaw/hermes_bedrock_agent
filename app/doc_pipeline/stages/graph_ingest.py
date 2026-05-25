"""Stage 8: Graph ingestion — extract entities/relations and write to Neptune Analytics.

Delegates entity extraction to app/dual_rag/graph_builder.py to keep graph logic DRY.
The dual_rag Chunk schema differs slightly from doc_pipeline Chunk; we convert here.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import PipelineConfig, config as _default_config
from ..models import Chunk as PipelineChunk, IngestStats

logger = logging.getLogger(__name__)


def _to_dual_rag_chunk(pc: PipelineChunk):
    """Convert a doc_pipeline Chunk to the app.dual_rag Chunk format."""
    from app.dual_rag.schemas import Chunk as DualChunk

    return DualChunk(
        chunk_id=pc.id,
        content=pc.text,
        chunk_type=pc.chunk_type,
        sheet_index=pc.sheet_index,
        sheet_name=pc.sheet_name,
        workbook_name=pc.workbook_name,
        source_pdf_s3_path=pc.source_pdf_s3_path,
        source_excel_s3_path=pc.source_excel_s3_path,
        source_markdown_s3_path=pc.source_markdown_s3_path,
        related_sheets=[int(s) for s in pc.related_sheets.split("|") if s.strip().isdigit()],
        systems=[s for s in pc.systems.split("|") if s],
        apis=[a for a in pc.apis.split("|") if a],
        fields=[],
        embedding_text=pc.embedding_text,
    )


def ingest_to_graph(
    chunks: list[PipelineChunk],
    cfg: Optional[PipelineConfig] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Extract entities from chunks and load into Neptune.

    Returns dict with node_count, edge_count, error_count.
    """
    cfg = cfg or _default_config

    from app.dual_rag.graph_builder import build_graph

    dual_chunks = [_to_dual_rag_chunk(c) for c in chunks]
    stats = build_graph(dual_chunks, graph_id=cfg.neptune_graph_id, dry_run=dry_run)
    logger.info(
        "Neptune: +%d nodes, +%d edges, %d errors",
        stats.get("node_count", 0),
        stats.get("edge_count", 0),
        stats.get("error_count", 0),
    )
    return stats
