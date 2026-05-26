"""SQLite database layer for GraphRAG knowledge graph."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS gr_documents (
    id TEXT PRIMARY KEY,
    s3_key TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    char_count INTEGER,
    chunk_count INTEGER,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS gr_chunks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES gr_documents(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER,
    embedding BLOB,
    embedding_model TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS gr_entities (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    entity_type TEXT,
    description TEXT,
    mention_count INTEGER DEFAULT 0,
    embedding BLOB,
    embedding_model TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS gr_edges (
    id TEXT PRIMARY KEY,
    src_id TEXT NOT NULL,
    src_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    dst_type TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON gr_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_edges_src ON gr_edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON gr_edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_entities_name ON gr_entities(name);
"""


def init_db(db_path: Path) -> None:
    """Create the database directory and tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding a SQLite connection with row_factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------

def upsert_document(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    s3_key: str,
    filename: str,
    file_type: str,
    content_hash: str,
    char_count: int,
    chunk_count: int,
    created_at: str,
    updated_at: str,
) -> None:
    """Insert or replace a document record."""
    conn.execute(
        """
        INSERT INTO gr_documents (id, s3_key, filename, file_type, content_hash,
                                  char_count, chunk_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            content_hash = excluded.content_hash,
            char_count = excluded.char_count,
            chunk_count = excluded.chunk_count,
            updated_at = excluded.updated_at
        """,
        (doc_id, s3_key, filename, file_type, content_hash, char_count, chunk_count, created_at, updated_at),
    )


def get_document_by_s3_key(conn: sqlite3.Connection, s3_key: str) -> sqlite3.Row | None:
    """Fetch a document row by its S3 key."""
    return conn.execute("SELECT * FROM gr_documents WHERE s3_key = ?", (s3_key,)).fetchone()


def get_all_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all document rows."""
    return conn.execute("SELECT * FROM gr_documents ORDER BY created_at").fetchall()


def delete_document(conn: sqlite3.Connection, doc_id: str) -> None:
    """Delete document and cascade-delete its chunks and associated edges."""
    chunk_ids = [
        row[0] for row in conn.execute("SELECT id FROM gr_chunks WHERE doc_id = ?", (doc_id,)).fetchall()
    ]
    for cid in chunk_ids:
        conn.execute("DELETE FROM gr_edges WHERE src_id = ? OR dst_id = ?", (cid, cid))
    conn.execute("DELETE FROM gr_chunks WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM gr_edges WHERE src_id = ? OR dst_id = ?", (doc_id, doc_id))
    conn.execute("DELETE FROM gr_documents WHERE id = ?", (doc_id,))


# ---------------------------------------------------------------------------
# Chunk operations
# ---------------------------------------------------------------------------

def insert_chunk(
    conn: sqlite3.Connection,
    *,
    chunk_id: str,
    doc_id: str,
    chunk_index: int,
    text: str,
    token_count: int,
    created_at: str,
) -> None:
    """Insert a chunk record (replace on conflict)."""
    conn.execute(
        """
        INSERT OR REPLACE INTO gr_chunks (id, doc_id, chunk_index, text, token_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chunk_id, doc_id, chunk_index, text, token_count, created_at),
    )


def update_chunk_embedding(
    conn: sqlite3.Connection, chunk_id: str, embedding: bytes, model: str
) -> None:
    """Store the serialized embedding blob for a chunk."""
    conn.execute(
        "UPDATE gr_chunks SET embedding = ?, embedding_model = ? WHERE id = ?",
        (embedding, model, chunk_id),
    )


def get_chunks_without_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all chunk rows that have no embedding yet."""
    return conn.execute("SELECT * FROM gr_chunks WHERE embedding IS NULL").fetchall()


def get_all_chunks_with_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all chunk rows that have an embedding."""
    return conn.execute("SELECT * FROM gr_chunks WHERE embedding IS NOT NULL").fetchall()


def get_chunks_for_doc(conn: sqlite3.Connection, doc_id: str) -> list[sqlite3.Row]:
    """Return all chunks for a document, ordered by index."""
    return conn.execute(
        "SELECT * FROM gr_chunks WHERE doc_id = ? ORDER BY chunk_index", (doc_id,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Entity operations
# ---------------------------------------------------------------------------

def upsert_entity(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    name: str,
    entity_type: str,
    description: str,
    mention_count: int,
    created_at: str,
    updated_at: str,
) -> None:
    """Insert or update an entity record."""
    conn.execute(
        """
        INSERT INTO gr_entities (id, name, entity_type, description, mention_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            mention_count = mention_count + excluded.mention_count,
            updated_at = excluded.updated_at
        """,
        (entity_id, name, entity_type, description, mention_count, created_at, updated_at),
    )


def update_entity_embedding(
    conn: sqlite3.Connection, entity_id: str, embedding: bytes, model: str
) -> None:
    """Store the serialized embedding blob for an entity."""
    conn.execute(
        "UPDATE gr_entities SET embedding = ?, embedding_model = ? WHERE id = ?",
        (embedding, model, entity_id),
    )


def update_entity_description(conn: sqlite3.Connection, entity_id: str, description: str, updated_at: str) -> None:
    """Update description and clear embedding so it gets re-embedded."""
    conn.execute(
        "UPDATE gr_entities SET description = ?, embedding = NULL, embedding_model = NULL, updated_at = ? WHERE id = ?",
        (description, updated_at, entity_id),
    )


def get_entity_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Fetch entity by canonical name."""
    return conn.execute("SELECT * FROM gr_entities WHERE name = ?", (name,)).fetchone()


def get_entities_without_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return entity rows with no embedding."""
    return conn.execute("SELECT * FROM gr_entities WHERE embedding IS NULL").fetchall()


def get_all_entities_with_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return entity rows that have an embedding."""
    return conn.execute("SELECT * FROM gr_entities WHERE embedding IS NOT NULL").fetchall()


def get_all_entities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all entity rows."""
    return conn.execute("SELECT * FROM gr_entities ORDER BY mention_count DESC").fetchall()


def delete_entity(conn: sqlite3.Connection, entity_id: str) -> None:
    """Delete an entity and all its edges."""
    conn.execute("DELETE FROM gr_edges WHERE src_id = ? OR dst_id = ?", (entity_id, entity_id))
    conn.execute("DELETE FROM gr_entities WHERE id = ?", (entity_id,))


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------

def upsert_edge(
    conn: sqlite3.Connection,
    *,
    edge_id: str,
    src_id: str,
    src_type: str,
    dst_id: str,
    dst_type: str,
    edge_type: str,
    weight: float,
    metadata: str,
    created_at: str,
) -> None:
    """Insert or update an edge, accumulating weight on conflict."""
    conn.execute(
        """
        INSERT INTO gr_edges (id, src_id, src_type, dst_id, dst_type, edge_type, weight, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET weight = weight + excluded.weight
        """,
        (edge_id, src_id, src_type, dst_id, dst_type, edge_type, weight, metadata, created_at),
    )


def get_edges_for_node(conn: sqlite3.Connection, node_id: str) -> list[sqlite3.Row]:
    """Return all edges where node_id is src or dst."""
    return conn.execute(
        "SELECT * FROM gr_edges WHERE src_id = ? OR dst_id = ?", (node_id, node_id)
    ).fetchall()


def get_all_edges(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all edges."""
    return conn.execute("SELECT * FROM gr_edges").fetchall()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Return counts for documents, chunks, entities, edges, and embedding coverage."""
    doc_count = conn.execute("SELECT COUNT(*) FROM gr_documents").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM gr_chunks").fetchone()[0]
    entity_count = conn.execute("SELECT COUNT(*) FROM gr_entities").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM gr_edges").fetchone()[0]
    embedded_chunks = conn.execute("SELECT COUNT(*) FROM gr_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    embedded_entities = conn.execute("SELECT COUNT(*) FROM gr_entities WHERE embedding IS NOT NULL").fetchone()[0]
    total_embeddable = chunk_count + entity_count
    total_embedded = embedded_chunks + embedded_entities
    coverage_pct = int(100 * total_embedded / total_embeddable) if total_embeddable else 0
    return {
        "documents": doc_count,
        "chunks": chunk_count,
        "entities": entity_count,
        "edges": edge_count,
        "embedded_chunks": embedded_chunks,
        "embedded_entities": embedded_entities,
        "embedding_coverage_pct": coverage_pct,
    }


def wipe_all(conn: sqlite3.Connection) -> None:
    """Delete all rows from all graph tables."""
    for table in ("gr_edges", "gr_chunks", "gr_entities", "gr_documents"):
        conn.execute(f"DELETE FROM {table}")
