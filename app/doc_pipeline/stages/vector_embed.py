"""Stage 7: Vector embedding — embed chunks into LanceDB via Bedrock Titan Embed V2.

Schema must match app/dual_rag/vector_store_loader.py exactly so both pipelines
share the same table.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pyarrow as pa

from ..config import PipelineConfig, config as _default_config
from ..models import Chunk
from ..utils.bedrock_client import embed_text, make_embed_client

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024


def _lancedb_schema() -> pa.Schema:
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("embedding", pa.list_(pa.float32(), EMBEDDING_DIM)),
        pa.field("chunk_type", pa.string()),
        pa.field("sheet_index", pa.int32()),
        pa.field("sheet_name", pa.string()),
        pa.field("workbook_name", pa.string()),
        pa.field("source_pdf_s3_path", pa.string()),
        pa.field("source_excel_s3_path", pa.string()),
        pa.field("source_markdown_s3_path", pa.string()),
        pa.field("systems", pa.string()),
        pa.field("apis", pa.string()),
        pa.field("related_sheets", pa.string()),
    ])


def _chunk_to_row(chunk: Chunk, embedding: list[float]) -> dict:
    return {
        "id": chunk.id,
        "text": chunk.text,
        "embedding": embedding,
        "chunk_type": chunk.chunk_type,
        "sheet_index": chunk.sheet_index,
        "sheet_name": chunk.sheet_name,
        "workbook_name": chunk.workbook_name,
        "source_pdf_s3_path": chunk.source_pdf_s3_path,
        "source_excel_s3_path": chunk.source_excel_s3_path,
        "source_markdown_s3_path": chunk.source_markdown_s3_path,
        "systems": chunk.systems,
        "apis": chunk.apis,
        "related_sheets": chunk.related_sheets,
    }


def embed_chunks(
    chunks: list[Chunk],
    cfg: Optional[PipelineConfig] = None,
    mode: str = "append",
) -> int:
    """Embed chunks and upsert into LanceDB.

    mode:
      "append"  — add rows to existing table (or create if absent)
      "replace" — drop all rows for this workbook, then add
      "rebuild"  — drop entire table, recreate from scratch
    """
    import lancedb  # type: ignore

    cfg = cfg or _default_config
    db_path = cfg.lancedb_path
    collection = cfg.vector_collection

    Path(db_path).mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(db_path)

    bedrock = make_embed_client(cfg.aws_region)

    if mode == "rebuild":
        if collection in db.table_names():
            db.drop_table(collection)
            logger.info("Dropped table '%s' for full rebuild", collection)
        table = db.create_table(collection, schema=_lancedb_schema())
        logger.info("Created table '%s'", collection)
    elif collection not in db.table_names():
        table = db.create_table(collection, schema=_lancedb_schema())
        logger.info("Created table '%s' (first time)", collection)
    else:
        table = db.open_table(collection)
        if mode == "replace" and chunks:
            workbook = chunks[0].workbook_name
            # Delete rows belonging to this workbook only
            try:
                table.delete(f"workbook_name = '{workbook}'")
                logger.info("Deleted existing rows for workbook '%s'", workbook)
            except Exception as e:
                logger.warning("Could not delete workbook rows: %s", e)

    rows: list[dict] = []
    errors = 0
    batch = cfg.embed_batch_size

    for i, chunk in enumerate(chunks):
        try:
            vec = embed_text(bedrock, cfg.embed_model_id, chunk.embedding_text, cfg.embed_dimensions)
            rows.append(_chunk_to_row(chunk, vec))
        except Exception as e:
            logger.warning("Embedding failed for chunk %s: %s", chunk.id, e)
            errors += 1
            continue

        if len(rows) >= batch:
            table.add(rows)
            logger.info("  Flushed batch at chunk %d/%d (errors: %d)", i + 1, len(chunks), errors)
            rows = []

    if rows:
        table.add(rows)

    written = len(chunks) - errors
    logger.info("Vector store: %d/%d chunks written to '%s'", written, len(chunks), collection)
    return written
