"""OpenSearch loader — builds bulk records and indexes into OpenSearch.

Provides:
- build_opensearch_record(): single ChunkEmbedding → OS record dict
- build_bulk_records(): batch ChunkEmbeddings → bulk records
- build_index_mapping(): generates knn_vector index mapping
- create_index_if_not_exists(): creates OS index with mapping
- bulk_index_chunks(): calls OpenSearch bulk API
- write_opensearch_bulk_jsonl(): writes records to JSONL artifact

Business logic lives HERE. Underlying OpenSearch calls go through
clients/opensearch_client.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.knowledge_store.jsonl_store import ensure_parent_dir, write_jsonl
from hermes_bedrock_agent.schemas.chunk import ChunkEmbedding

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def build_opensearch_record(
    embedding: ChunkEmbedding,
    *,
    vector_field: str = "embedding",
    text_field: str = "text",
) -> dict[str, Any]:
    """Convert a ChunkEmbedding to an OpenSearch document record.

    The resulting dict is ready for bulk indexing.
    NEVER includes image_base64.

    Args:
        embedding: Source ChunkEmbedding.
        vector_field: OpenSearch field name for the vector (default: "embedding").
        text_field: OpenSearch field name for the text (default: "text").
    """
    record = {
        "chunk_id": embedding.chunk_id,
        "document_id": embedding.document_id,
        text_field: embedding.content,
        vector_field: embedding.embedding,
        "source_uri": embedding.source_uri,
        "source_type": embedding.source_type,
        "page": embedding.page,
        "section_title": embedding.section_title,
        "visual_block_ids": embedding.visual_block_ids,
        "acl": embedding.acl,
        "content_hash": embedding.content_hash,
        "embedding_model": embedding.embedding_model,
        "metadata": {
            "chunk_type": embedding.chunk_type.value if embedding.chunk_type else "",
            "language": embedding.language,
            "embedding_dimension": embedding.embedding_dimension,
            **(embedding.metadata or {}),
        },
    }
    return record


def build_bulk_records(
    embeddings: list[ChunkEmbedding],
    *,
    vector_field: str = "embedding",
    text_field: str = "text",
) -> list[dict[str, Any]]:
    """Convert a list of ChunkEmbeddings to OpenSearch bulk records.

    Returns list of dicts ready for bulk indexing.
    """
    records = []
    for emb in embeddings:
        record = build_opensearch_record(emb, vector_field=vector_field, text_field=text_field)
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Index mapping
# ---------------------------------------------------------------------------


def build_index_mapping(
    dimension: int = 1024,
    vector_field: str = "embedding",
    text_field: str = "text",
    engine: str = "nmslib",
    space_type: str = "cosinesimil",
    ef_construction: int = 512,
    m: int = 16,
) -> dict[str, Any]:
    """Build OpenSearch index mapping with knn_vector support.

    Args:
        dimension: Embedding vector dimension.
        vector_field: Name of the vector field.
        text_field: Name of the text field.
        engine: ANN engine (nmslib, faiss, lucene).
        space_type: Distance metric.
        ef_construction: HNSW construction parameter.
        m: HNSW M parameter.

    Returns:
        Complete index settings + mappings dict.
    """
    return {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
            },
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                text_field: {"type": "text", "analyzer": "standard"},
                vector_field: {
                    "type": "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": space_type,
                        "engine": engine,
                        "parameters": {
                            "ef_construction": ef_construction,
                            "m": m,
                        },
                    },
                },
                "source_uri": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "page": {"type": "integer"},
                "section_title": {"type": "text"},
                "visual_block_ids": {"type": "keyword"},
                "acl": {"type": "keyword"},
                "content_hash": {"type": "keyword"},
                "embedding_model": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": True},
            },
        },
    }


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------


def create_index_if_not_exists(
    os_client,
    index_name: str,
    dimension: int = 1024,
    vector_field: str = "embedding",
    text_field: str = "text",
    *,
    dry_run: bool = False,
) -> bool:
    """Create OpenSearch index with knn mapping if it doesn't exist.

    Args:
        os_client: OpenSearch client (from clients/opensearch_client.py).
        index_name: Target index name.
        dimension: Vector dimension.
        vector_field: Vector field name.
        text_field: Text field name.
        dry_run: If True, only check existence, don't create.

    Returns:
        True if index was created, False if already existed.
    """
    try:
        exists = os_client.indices.exists(index=index_name)
    except Exception as e:
        logger.error(f"Failed to check index existence: {e}")
        raise

    if exists:
        logger.info(f"Index '{index_name}' already exists, skipping creation")
        return False

    if dry_run:
        logger.info(f"[DRY RUN] Would create index '{index_name}' (dim={dimension})")
        return False

    mapping = build_index_mapping(
        dimension=dimension,
        vector_field=vector_field,
        text_field=text_field,
    )

    try:
        os_client.indices.create(index=index_name, body=mapping)
        logger.info(f"Created index '{index_name}' (dim={dimension}, field={vector_field})")
        return True
    except Exception as e:
        logger.error(f"Failed to create index '{index_name}': {e}")
        raise


# ---------------------------------------------------------------------------
# Bulk indexing
# ---------------------------------------------------------------------------


def bulk_index_chunks(
    os_client,
    index_name: str,
    embeddings: list[ChunkEmbedding],
    *,
    batch_size: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bulk index ChunkEmbeddings into OpenSearch.

    Args:
        os_client: OpenSearch client.
        index_name: Target index.
        embeddings: List of ChunkEmbeddings to index.
        batch_size: Records per bulk request.
        dry_run: If True, build records but don't send to OpenSearch.

    Returns:
        Summary dict: {total, indexed, errors, dry_run}.
    """
    records = build_bulk_records(embeddings)
    total = len(records)
    indexed = 0
    errors = 0

    if dry_run:
        logger.info(f"[DRY RUN] Would index {total} records to '{index_name}'")
        return {"total": total, "indexed": 0, "errors": 0, "dry_run": True}

    # Process in batches
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        bulk_body = _build_bulk_body(batch, index_name)

        try:
            response = os_client.bulk(body=bulk_body)
            if response.get("errors"):
                for item in response.get("items", []):
                    action = item.get("index", item.get("create", {}))
                    if action.get("error"):
                        errors += 1
                        logger.warning(
                            f"Bulk error for {action.get('_id')}: "
                            f"{action['error'].get('reason', 'unknown')}"
                        )
                    else:
                        indexed += 1
            else:
                indexed += len(batch)
        except Exception as e:
            logger.error(f"Bulk request failed for batch {i // batch_size}: {e}")
            errors += len(batch)

    logger.info(
        f"Bulk index complete: {indexed}/{total} indexed, {errors} errors "
        f"(index={index_name})"
    )
    return {"total": total, "indexed": indexed, "errors": errors, "dry_run": False}


def _build_bulk_body(records: list[dict], index_name: str) -> str:
    """Build OpenSearch bulk request body (NDJSON format)."""
    lines: list[str] = []
    for record in records:
        # Action line
        action = {"index": {"_index": index_name, "_id": record["chunk_id"]}}
        lines.append(json.dumps(action))
        # Document line
        lines.append(json.dumps(record))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# JSONL output
# ---------------------------------------------------------------------------


def write_opensearch_bulk_jsonl(
    embeddings: list[ChunkEmbedding],
    output_path: Path | str,
    *,
    dry_run: bool = False,
    persist_inline_image_base64: bool = False,
) -> int:
    """Write OpenSearch bulk records to JSONL file.

    Each line is a complete OpenSearch document (no action metadata).
    Never includes image_base64 regardless of config (not relevant for OS records).

    Args:
        embeddings: ChunkEmbeddings to write.
        output_path: Target JSONL file path.
        dry_run: If True, don't actually write.
        persist_inline_image_base64: Ignored (always False for OS records).

    Returns:
        Number of records written.
    """
    records = build_bulk_records(embeddings)
    path = Path(output_path)
    ensure_parent_dir(path)

    count = write_jsonl(records, path, dry_run=dry_run, persist_inline_image_base64=False)
    logger.info(f"Wrote {count} OpenSearch bulk records to {path} (dry_run={dry_run})")
    return count
