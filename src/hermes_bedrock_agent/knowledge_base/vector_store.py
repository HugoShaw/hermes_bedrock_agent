"""Embed chunks using Bedrock Titan Embed V2 and store in LanceDB."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import boto3
import pyarrow as pa

import lancedb

from ..config import Config, config as _default_config
from .schemas import Chunk

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024


def _get_bedrock_client(region: str):
    return boto3.client("bedrock-runtime", region_name=region)


def _embed_text(client, model_id: str, text: str) -> list[float]:
    body = json.dumps({"inputText": text, "dimensions": EMBEDDING_DIM, "normalize": True})
    response = client.invoke_model(
        modelId=model_id, body=body,
        contentType="application/json", accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


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
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    batch_size: int = 25,
) -> int:
    """Embed all chunks and upsert into LanceDB. Returns number of records written."""
    cfg = cfg or _default_config
    db_path = store_path or cfg.lancedb_path
    coll_name = collection or cfg.vector_collection

    Path(db_path).mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(db_path)

    if coll_name in db.table_names():
        db.drop_table(coll_name)
        logger.info("Dropped existing table '%s' for clean rebuild", coll_name)

    table = db.create_table(coll_name, schema=_lancedb_schema())
    bedrock = _get_bedrock_client(cfg.aws_region)
    rows: list[dict] = []
    errors = 0

    for i, chunk in enumerate(chunks):
        try:
            embedding = _embed_text(bedrock, cfg.embed_model_id, chunk.embedding_text)
            rows.append(_chunk_to_row(chunk, embedding))
        except Exception as exc:
            logger.warning("Embedding failed for chunk %s: %s", chunk.chunk_id, exc)
            errors += 1
            continue

        if len(rows) >= batch_size:
            table.add(rows)
            logger.info("Ingested batch %d/%d (errors: %d)", i + 1, len(chunks), errors)
            rows = []

    if rows:
        table.add(rows)

    written = len(chunks) - errors
    logger.info("Vector store loaded: %d/%d chunks → '%s' at %s", written, len(chunks), coll_name, db_path)
    return written


def query_vector_store(
    query_text: str,
    cfg: Optional[Config] = None,
    top_k: int = 5,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
) -> list[dict]:
    """Query LanceDB with a text query; returns top-k results with metadata."""
    cfg = cfg or _default_config
    db_path = store_path or cfg.lancedb_path
    coll_name = collection or cfg.vector_collection

    db = lancedb.connect(db_path)
    if coll_name not in db.table_names():
        raise ValueError(f"Collection '{coll_name}' not found in {db_path}")

    bedrock = _get_bedrock_client(cfg.aws_region)
    query_embedding = _embed_text(bedrock, cfg.embed_model_id, query_text)
    table = db.open_table(coll_name)
    return table.search(query_embedding).limit(top_k).to_list()
