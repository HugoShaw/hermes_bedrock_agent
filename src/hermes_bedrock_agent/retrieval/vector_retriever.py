"""Vector retrieval from LanceDB."""

from __future__ import annotations

import logging
from typing import Optional

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import RetrievedChunk
from ..knowledge_base.vector_store import query_vector_store

logger = logging.getLogger(__name__)


def retrieve_chunks(
    query: str,
    top_k: int = 5,
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    project_id: str = "",
) -> list[RetrievedChunk]:
    """Retrieve top-K chunks from LanceDB for a text query."""
    cfg = cfg or _default_config
    raw_results = query_vector_store(
        query_text=query, cfg=cfg, top_k=top_k,
        store_path=store_path, collection=collection,
        project_id=project_id,
    )

    chunks: list[RetrievedChunk] = []
    for row in raw_results:
        distance = row.get("_distance", 0.0)
        # LanceDB returns cosine distance ∈ [0, 2]. Convert to similarity ∈ [0, 1].
        # Values > 1.0 occur due to ANN approximation; clamp to 0.
        score = max(0.0, 1.0 - distance)
        chunks.append(RetrievedChunk(
            chunk_id=row.get("id", ""),
            content=row.get("text", ""),
            chunk_type=row.get("chunk_type", ""),
            sheet_index=row.get("sheet_index", 0),
            sheet_name=row.get("sheet_name", ""),
            score=round(score, 4),
            source_pdf_s3_path=row.get("source_pdf_s3_path", ""),
            source_excel_s3_path=row.get("source_excel_s3_path", ""),
            project_id=row.get("project_id", project_id),
        ))
    return chunks
