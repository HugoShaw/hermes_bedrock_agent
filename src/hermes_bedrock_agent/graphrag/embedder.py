"""Bedrock embeddings for GraphRAG chunks and entities."""

from __future__ import annotations

import io
import json
from pathlib import Path

import boto3
import numpy as np
from botocore.exceptions import BotoCoreError, ClientError


def _bedrock_runtime_client(region: str) -> object:
    return boto3.client("bedrock-runtime", region_name=region)


def embed_text(
    text: str,
    model: str = "amazon.titan-embed-text-v2:0",
    region: str = "ap-northeast-1",
) -> np.ndarray:
    """Embed *text* using Amazon Bedrock Titan Embeddings V2.

    Returns a float32 numpy array of the embedding vector.
    """
    client = _bedrock_runtime_client(region)
    body = json.dumps({"inputText": text})
    try:
        response = client.invoke_model(
            modelId=model,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        vector = result["embedding"]
        return np.array(vector, dtype=np.float32)
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(f"Bedrock embedding call failed: {exc}") from exc


def serialize_embedding(embedding: np.ndarray) -> bytes:
    """Serialize a numpy float32 array to bytes using numpy.save."""
    buf = io.BytesIO()
    np.save(buf, embedding)
    return buf.getvalue()


def deserialize_embedding(blob: bytes) -> np.ndarray:
    """Deserialize a numpy array from bytes produced by :func:`serialize_embedding`."""
    buf = io.BytesIO(blob)
    return np.load(buf)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def find_similar_chunks(
    query_embedding: np.ndarray,
    chunk_rows: list,  # sqlite3.Row list with 'id' and 'embedding' fields
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Find top-k most similar chunks by cosine similarity.

    *chunk_rows* must have ``id`` (str) and ``embedding`` (bytes | None) fields.
    Returns list of ``(chunk_id, score)`` sorted by score descending.
    """
    scores: list[tuple[str, float]] = []
    for row in chunk_rows:
        if row["embedding"] is None:
            continue
        vec = deserialize_embedding(bytes(row["embedding"]))
        score = cosine_similarity(query_embedding, vec)
        scores.append((row["id"], score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


def find_similar_entities(
    query_embedding: np.ndarray,
    entity_rows: list,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Find top-k most similar entities by cosine similarity."""
    scores: list[tuple[str, float]] = []
    for row in entity_rows:
        if row["embedding"] is None:
            continue
        vec = deserialize_embedding(bytes(row["embedding"]))
        score = cosine_similarity(query_embedding, vec)
        scores.append((row["id"], score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


def batch_embed_chunks(
    db_path: Path,
    model: str = "amazon.titan-embed-text-v2:0",
    region: str = "ap-northeast-1",
) -> tuple[int, int]:
    """Embed all chunks and entities that lack embeddings.

    Returns ``(embedded_count, skipped_count)`` where skipped means already
    had an embedding.
    """
    from hermes_bedrock_agent.graphrag import db as db_mod

    db_mod.init_db(db_path)
    embedded = 0
    skipped = 0

    with db_mod.get_connection(db_path) as conn:
        pending_chunks = db_mod.get_chunks_without_embedding(conn)
        pending_entities = db_mod.get_entities_without_embedding(conn)

    # Re-open for writing to avoid holding a long transaction during HTTP calls
    for row in pending_chunks:
        vec = embed_text(row["text"], model=model, region=region)
        blob = serialize_embedding(vec)
        with db_mod.get_connection(db_path) as conn:
            db_mod.update_chunk_embedding(conn, row["id"], blob, model)
        embedded += 1

    for row in pending_entities:
        text = row["description"] or row["name"]
        vec = embed_text(text, model=model, region=region)
        blob = serialize_embedding(vec)
        with db_mod.get_connection(db_path) as conn:
            db_mod.update_entity_embedding(conn, row["id"], blob, model)
        embedded += 1

    return embedded, skipped
