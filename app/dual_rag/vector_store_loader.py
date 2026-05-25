"""Vector store loader: embeds chunks using Bedrock Titan Embed V2 and stores in LanceDB.

Collection name: murata_excel_vlm_dual_rag
Schema: id, text, embedding, chunk_type, sheet_index, sheet_name,
        source_pdf_s3_path, source_excel_s3_path, systems, apis
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import boto3
import pyarrow as pa

import lancedb

from .config import config
from .schemas import Chunk

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # Titan Embed V2 dimension


def _get_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=config.aws_region)


def _embed_text(client, text: str) -> list[float]:
    """Call Bedrock Titan Embed V2 and return the embedding vector."""
    body = json.dumps({"inputText": text, "dimensions": EMBEDDING_DIM, "normalize": True})
    response = client.invoke_model(
        modelId=config.bedrock_embedding_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["embedding"]


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
        pa.field("systems", pa.string()),   # JSON-encoded list
        pa.field("apis", pa.string()),      # JSON-encoded list
        pa.field("related_sheets", pa.string()),  # JSON-encoded list
    ])


def _chunk_to_row(chunk: Chunk, embedding: list[float]) -> dict:
    return {
        "id": chunk.chunk_id,
        "text": chunk.content,
        "embedding": embedding,
        "chunk_type": chunk.chunk_type,
        "sheet_index": chunk.sheet_index,
        "sheet_name": chunk.sheet_name,
        "workbook_name": chunk.workbook_name,
        "source_pdf_s3_path": chunk.source_pdf_s3_path,
        "source_excel_s3_path": chunk.source_excel_s3_path,
        "source_markdown_s3_path": chunk.source_markdown_s3_path,
        "systems": json.dumps(chunk.systems, ensure_ascii=False),
        "apis": json.dumps(chunk.apis, ensure_ascii=False),
        "related_sheets": json.dumps(chunk.related_sheets),
    }


def load_vector_store(
    chunks: list[Chunk],
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    batch_size: int = 25,
) -> int:
    """Embed all chunks and upsert into LanceDB.

    Returns the number of records successfully written.
    """
    db_path = store_path or config.vector_local_store_path
    coll_name = collection or config.vector_collection

    Path(db_path).mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(db_path)

    # Drop and recreate for idempotency
    existing = db.table_names()
    if coll_name in existing:
        db.drop_table(coll_name)
        logger.info("Dropped existing table '%s' for clean rebuild", coll_name)

    schema = _lancedb_schema()
    table = db.create_table(coll_name, schema=schema)

    bedrock = _get_bedrock_client()
    rows: list[dict] = []
    errors = 0
    total = len(chunks)

    for i, chunk in enumerate(chunks):
        try:
            embedding = _embed_text(bedrock, chunk.embedding_text)
            rows.append(_chunk_to_row(chunk, embedding))
        except Exception as exc:
            logger.warning("Embedding failed for chunk %s: %s", chunk.chunk_id, exc)
            errors += 1
            continue

        # Flush batch
        if len(rows) >= batch_size:
            table.add(rows)
            logger.info("Ingested batch %d/%d (errors so far: %d)", i + 1, total, errors)
            rows = []

    # Flush remainder
    if rows:
        table.add(rows)

    written = total - errors
    logger.info(
        "Vector store loaded: %d/%d chunks written to '%s' at %s",
        written, total, coll_name, db_path,
    )
    return written


def query_vector_store(
    query_text: str,
    top_k: int = 5,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
) -> list[dict]:
    """Query LanceDB with a text query; returns top-k results with metadata."""
    db_path = store_path or config.vector_local_store_path
    coll_name = collection or config.vector_collection

    db = lancedb.connect(db_path)
    if coll_name not in db.table_names():
        raise ValueError(f"Collection '{coll_name}' not found in {db_path}")

    bedrock = _get_bedrock_client()
    query_embedding = _embed_text(bedrock, query_text)

    table = db.open_table(coll_name)
    results = (
        table.search(query_embedding)
        .limit(top_k)
        .to_list()
    )
    return results
