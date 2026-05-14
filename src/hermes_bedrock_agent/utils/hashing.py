"""Stable ID generation and content hashing utilities.

All IDs in the system are deterministic SHA-256 hashes of their
composite key fields, ensuring stability across re-runs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_hex(data: str | bytes) -> str:
    """Compute SHA-256 hex digest of string or bytes.

    Args:
        data: Input string (UTF-8 encoded) or raw bytes.

    Returns:
        64-character lowercase hex string.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(content: str | bytes) -> str:
    """Hash text or binary content for deduplication/change detection.

    Args:
        content: Text or binary content to hash.

    Returns:
        SHA-256 hex digest of the content.
    """
    return sha256_hex(content)


def file_hash(path: Path | str, chunk_size: int = 8192) -> str:
    """Compute SHA-256 of a file's contents (streaming).

    Args:
        path: File path to hash.
        chunk_size: Read buffer size in bytes.

    Returns:
        SHA-256 hex digest.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def make_document_id(source_uri: str) -> str:
    """Generate stable document_id from source URI.

    Args:
        source_uri: Full S3 URI or file path.

    Returns:
        Deterministic document ID (sha256 hex prefix, 16 chars).
    """
    return f"doc_{sha256_hex(source_uri)[:16]}"


def make_chunk_id(document_id: str, chunk_index: int, content_hash: str) -> str:
    """Generate stable chunk_id.

    Args:
        document_id: Parent document ID.
        chunk_index: Sequential chunk index.
        content_hash: SHA-256 of chunk content.

    Returns:
        Deterministic chunk ID.
    """
    composite = f"{document_id}:{chunk_index}:{content_hash}"
    return f"chunk_{sha256_hex(composite)[:16]}"


def make_visual_id(document_id: str, page: int = 1, image_id: str = "") -> str:
    """Generate stable visual_id for a VisualBlock.

    Args:
        document_id: Parent document ID.
        page: Page number in the document.
        image_id: Image identifier within document.

    Returns:
        Deterministic visual block ID.
    """
    composite = f"{document_id}:{page}:{image_id}"
    return f"vis_{sha256_hex(composite)[:16]}"


def make_entity_id(entity_type: str, canonical_name: str) -> str:
    """Generate stable entity_id.

    Args:
        entity_type: Entity type label.
        canonical_name: Normalized entity name.

    Returns:
        Deterministic entity ID.
    """
    composite = f"{entity_type}:{canonical_name.lower().strip()}"
    return f"ent_{sha256_hex(composite)[:16]}"


def make_relation_id(source_entity_id: str, relation_type: str, target_entity_id: str) -> str:
    """Generate stable relation_id.

    Args:
        source_entity_id: Source entity ID.
        relation_type: Relation type label.
        target_entity_id: Target entity ID.

    Returns:
        Deterministic relation ID.
    """
    composite = f"{source_entity_id}:{relation_type}:{target_entity_id}"
    return f"rel_{sha256_hex(composite)[:16]}"


def make_evidence_id(element_id: str, chunk_id: str) -> str:
    """Generate stable evidence_id.

    Args:
        element_id: Entity or relation ID.
        chunk_id: Source chunk ID.

    Returns:
        Deterministic evidence ID.
    """
    composite = f"{element_id}:{chunk_id}"
    return f"evi_{sha256_hex(composite)[:16]}"
