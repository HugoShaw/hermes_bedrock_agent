"""Embed chunks using Bedrock Titan Embed V2 and store in LanceDB."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

import boto3
import pyarrow as pa

import lancedb

from ..config import Config, config as _default_config
from .schemas import Chunk

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024

_SAFE_PROJECT_ID_RE = re.compile(r'^[\w\-.　-鿿豈-﫿]+$')


def _validate_project_id(project_id: str) -> str:
    """Validate project_id contains only safe characters for LanceDB filters."""
    if not project_id:
        return ""
    if not _SAFE_PROJECT_ID_RE.match(project_id):
        raise ValueError(
            f"Invalid project_id '{project_id}': must contain only "
            "alphanumeric, underscore, hyphen, dot, or CJK characters"
        )
    return project_id


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
        # Generic fields
        pa.field("source_file", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("parser_type", pa.string()),
        pa.field("document_role", pa.string()),
        # Document-level provenance (graph linkage)
        pa.field("document_id", pa.string()),
        pa.field("document_name", pa.string()),
        pa.field("document_type", pa.string()),
        pa.field("unit_type", pa.string()),
        pa.field("source_markdown_file", pa.string()),
        pa.field("evidence_path", pa.string()),
        pa.field("evidence_paths", pa.string()),  # JSON array
        pa.field("content_hash", pa.string()),
        # Excel-specific (kept for backward compat)
        pa.field("sheet_index", pa.int32()),
        pa.field("sheet_name", pa.string()),
        pa.field("workbook_name", pa.string()),
        pa.field("source_pdf_s3_path", pa.string()),
        pa.field("source_excel_s3_path", pa.string()),
        pa.field("source_markdown_s3_path", pa.string()),
        pa.field("systems", pa.string()),
        pa.field("apis", pa.string()),
        pa.field("related_sheets", pa.string()),
        pa.field("project_id", pa.string()),
    ])


def _chunk_to_row(chunk: Chunk, embedding: list[float]) -> dict:
    return {
        "id": chunk.chunk_id,
        "text": chunk.content,
        "embedding": embedding,
        "chunk_type": chunk.chunk_type,
        "source_file": chunk.source_file,
        "source_type": chunk.source_type,
        "parser_type": chunk.parser_type,
        "document_role": chunk.document_role,
        # Document-level provenance (graph linkage)
        "document_id": chunk.document_id,
        "document_name": chunk.document_name,
        "document_type": chunk.document_type,
        "unit_type": chunk.unit_type,
        "source_markdown_file": chunk.source_markdown_file,
        "evidence_path": chunk.evidence_path,
        "evidence_paths": json.dumps(chunk.evidence_paths, ensure_ascii=False),
        "content_hash": chunk.content_hash,
        # Excel-specific
        "sheet_index": chunk.sheet_index,
        "sheet_name": chunk.sheet_name,
        "workbook_name": chunk.workbook_name,
        "source_pdf_s3_path": chunk.source_pdf_s3_path,
        "source_excel_s3_path": chunk.source_excel_s3_path,
        "source_markdown_s3_path": chunk.source_markdown_s3_path,
        "systems": json.dumps(chunk.systems, ensure_ascii=False),
        "apis": json.dumps(chunk.apis, ensure_ascii=False),
        "related_sheets": json.dumps(chunk.related_sheets),
        "project_id": chunk.project_id,
    }


def load_vector_store(
    chunks: list[Chunk],
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
    batch_size: int = 25,
    project_id: str = "",
    replace_project: bool = True,
) -> int:
    """Embed all chunks and upsert into LanceDB. Returns number of records written.

    Args:
        chunks: Chunk objects to embed and store.
        cfg: Optional config override.
        store_path: Optional LanceDB path override.
        collection: Optional collection name override.
        batch_size: Number of embeddings per API call batch.
        project_id: Project scope for deletion/filtering.
        replace_project: If True (default), deletes ALL existing rows for
            this project_id before inserting. Set False to append without
            deleting — use this when loading workbook-by-workbook into the
            same project to avoid overwriting earlier workbooks' chunks.
    """
    cfg = cfg or _default_config

    if replace_project and not project_id:
        raise ValueError(
            "load_vector_store: replace_project=True requires a non-empty project_id. "
            "Refusing to drop the entire table. Pass replace_project=False to append."
        )

    db_path = store_path or cfg.lancedb_path
    coll_name = collection or cfg.vector_collection

    if not project_id:
        logger.warning(
            "load_vector_store: no project_id — rebuilding entire table. "
            "All existing project data will be deleted."
        )

    Path(db_path).mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(db_path)

    if coll_name in db.table_names():
        table = db.open_table(coll_name)
        # Schema evolution: add any columns present in the target schema
        # but missing from the existing table (backwards-compatible migration)
        existing_cols = set(table.schema.names)
        target_schema = _lancedb_schema()
        for field in target_schema:
            if field.name not in existing_cols and field.name != "embedding":
                try:
                    if pa.types.is_int32(field.type):
                        table.add_columns({field.name: "CAST(NULL AS INTEGER)"})
                    else:
                        table.add_columns({field.name: "CAST(NULL AS STRING)"})
                    logger.info("Schema evolution: added column '%s' to table '%s'", field.name, coll_name)
                except Exception as exc:
                    logger.warning("Could not add column '%s': %s", field.name, exc)
        if project_id and replace_project:
            # Delete only rows belonging to this project, preserving other projects
            _validate_project_id(project_id)
            try:
                table.delete(f"project_id = '{project_id}'")
                logger.info("Deleted existing rows for project '%s' from '%s'", project_id, coll_name)
            except Exception as exc:
                logger.warning("Could not delete project rows (may be old schema): %s", exc)
                db.drop_table(coll_name)
                table = db.create_table(coll_name, schema=_lancedb_schema())
        elif not project_id:
            db.drop_table(coll_name)
            logger.info("Dropped existing table '%s' for clean rebuild", coll_name)
            table = db.create_table(coll_name, schema=_lancedb_schema())
        else:
            # append_only mode: just add to existing table
            logger.info("Appending to existing table '%s' (replace_project=False)", coll_name)
    else:
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
    project_id: str = "",
    sheet_filter: Optional[list[int]] = None,
    trace: Optional["VectorTrace"] = None,
) -> list[dict]:
    """Query LanceDB with a text query; returns top-k results with metadata.

    Args:
        query_text: Text query to embed and search for.
        cfg: Optional config override.
        top_k: Number of results to return.
        store_path: Optional LanceDB path override.
        collection: Optional collection name override.
        project_id: Project ID filter (scopes retrieval to one project).
        sheet_filter: Optional list of sheet indices to restrict results to.
            Combined with project_id filter using AND when both are specified.
        trace: Optional VectorTrace to populate with debug info.
    """
    cfg = cfg or _default_config
    db_path = store_path or cfg.lancedb_path
    coll_name = collection or cfg.vector_collection

    if trace is not None:
        trace.collection = coll_name
        trace.project_filter = project_id
        trace.sheet_filter = list(sheet_filter) if sheet_filter else []
        trace.embedding_model = cfg.embed_model_id

    if not project_id:
        logger.warning(
            "query_vector_store: no project_id set — retrieval will search across ALL projects"
        )

    db = lancedb.connect(db_path)
    if coll_name not in db.table_names():
        raise ValueError(f"Collection '{coll_name}' not found in {db_path}")

    bedrock = _get_bedrock_client(cfg.aws_region)

    if trace is not None:
        from ..retrieval.trace import Timer
        with Timer() as embed_timer:
            query_embedding = _embed_text(bedrock, cfg.embed_model_id, query_text)
        trace.embedding_latency_ms = embed_timer.elapsed_ms
    else:
        query_embedding = _embed_text(bedrock, cfg.embed_model_id, query_text)

    table = db.open_table(coll_name)
    search = table.search(query_embedding)

    filters: list[str] = []
    if project_id:
        _validate_project_id(project_id)
        filters.append(f"project_id = '{project_id}'")
    if sheet_filter:
        validated = [int(i) for i in sheet_filter]
        idx_str = ", ".join(str(i) for i in validated)
        filters.append(f"sheet_index IN ({idx_str})")

    if filters:
        search = search.where(" AND ".join(filters), prefilter=True)

    if trace is not None:
        from ..retrieval.trace import Timer
        with Timer() as search_timer:
            results = search.limit(top_k).to_list()
        trace.search_latency_ms = search_timer.elapsed_ms
        trace.raw_results_count = len(results)
        trace.raw_results = [
            {"id": r.get("id", ""), "_distance": r.get("_distance", 0.0),
             "chunk_type": r.get("chunk_type", ""), "sheet_index": r.get("sheet_index", 0)}
            for r in results[:10]
        ]
        return results
    else:
        return search.limit(top_k).to_list()
