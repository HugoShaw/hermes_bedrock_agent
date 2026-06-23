"""Vector retrieval from LanceDB."""

from __future__ import annotations

import logging
import math
from typing import Optional

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import RetrievedChunk
from ..knowledge_base.vector_store import query_vector_store
from .trace import VectorTrace

logger = logging.getLogger(__name__)


def _safe_str(val: object) -> str:
    """Convert a pandas row value to a clean string, handling NaN/None/float safely."""
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
        return str(val)
    s = str(val).strip()
    if s in ("nan", "None", "null"):
        return ""
    return s


def retrieve_chunks(
    query: str,
    top_k: int = 5,
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    project_id: str = "",
    trace: Optional[VectorTrace] = None,
) -> list[RetrievedChunk]:
    """Retrieve top-K chunks from LanceDB for a text query."""
    cfg = cfg or _default_config
    raw_results = query_vector_store(
        query_text=query, cfg=cfg, top_k=top_k,
        store_path=store_path, collection=collection,
        project_id=project_id,
        trace=trace,
    )

    chunks: list[RetrievedChunk] = []
    for row in raw_results:
        distance = row.get("_distance", 0.0)
        score = 1.0 / (1.0 + distance)
        # parsed_markdown_path may not exist as a column in LanceDB;
        # fall back to source_markdown_file which is semantically equivalent.
        parsed_md = _safe_str(row.get("parsed_markdown_path", "")) or _safe_str(row.get("source_markdown_file", ""))
        chunks.append(RetrievedChunk(
            chunk_id=_safe_str(row.get("id", "")),
            content=_safe_str(row.get("text", "")),
            chunk_type=_safe_str(row.get("chunk_type", "")),
            sheet_index=row.get("sheet_index", 0),
            sheet_name=_safe_str(row.get("sheet_name", "")),
            score=round(score, 4),
            source_pdf_s3_path=_safe_str(row.get("source_pdf_s3_path", "")),
            source_excel_s3_path=_safe_str(row.get("source_excel_s3_path", "")),
            project_id=_safe_str(row.get("project_id", "")) or project_id,
            parsed_markdown_path=parsed_md,
            document_id=_safe_str(row.get("document_id", "")),
            document_name=_safe_str(row.get("document_name", "")),
            document_type=_safe_str(row.get("document_type", "")),
            source_markdown_file=_safe_str(row.get("source_markdown_file", "")),
            evidence_path=_safe_str(row.get("evidence_path", "")),
            evidence_paths=_safe_str(row.get("evidence_paths", "")),
            source_file=_safe_str(row.get("source_file", "")),
            source_type=_safe_str(row.get("source_type", "")),
            parser_type=_safe_str(row.get("parser_type", "")),
        ))

    if trace is not None:
        trace.final_chunks_count = len(chunks)

    return chunks
