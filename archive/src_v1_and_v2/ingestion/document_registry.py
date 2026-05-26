"""Document registry — registration, deduplication, and change detection.

Manages the lifecycle of SourceDocument records:
- Assigns stable document_id from S3 URI
- Calculates content_hash for incremental processing
- Infers source_type from file extension
- Detects new or changed documents vs. a previous registry snapshot
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.document import SourceDocument, SourceType
from hermes_bedrock_agent.utils.hashing import content_hash, make_document_id

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Extension → SourceType mapping
# ---------------------------------------------------------------------------

_EXTENSION_TYPE_MAP: dict[str, SourceType] = {
    # Text / Markdown
    ".md": SourceType.MARKDOWN,
    ".markdown": SourceType.MARKDOWN,
    ".txt": SourceType.TEXT,
    # Code
    ".py": SourceType.CODE,
    ".java": SourceType.CODE,
    ".js": SourceType.CODE,
    ".ts": SourceType.CODE,
    ".tsx": SourceType.CODE,
    ".jsx": SourceType.CODE,
    ".go": SourceType.CODE,
    ".rs": SourceType.CODE,
    ".c": SourceType.CODE,
    ".cpp": SourceType.CODE,
    ".h": SourceType.CODE,
    # SQL / DDL
    ".sql": SourceType.SQL,
    ".ddl": SourceType.SQL,
    # Config / Data
    ".yaml": SourceType.CONFIG,
    ".yml": SourceType.CONFIG,
    ".json": SourceType.CONFIG,
    ".xml": SourceType.CONFIG,
    ".toml": SourceType.CONFIG,
    # PDF
    ".pdf": SourceType.PDF,
    # Office
    ".docx": SourceType.DOCX,
    ".doc": SourceType.DOCX,
    ".pptx": SourceType.PPTX,
    ".xlsx": SourceType.SPREADSHEET,
    ".xls": SourceType.SPREADSHEET,
    ".csv": SourceType.SPREADSHEET,
    # Image
    ".png": SourceType.IMAGE,
    ".jpg": SourceType.IMAGE,
    ".jpeg": SourceType.IMAGE,
    ".gif": SourceType.IMAGE,
    ".bmp": SourceType.IMAGE,
    ".tiff": SourceType.IMAGE,
    ".svg": SourceType.IMAGE,
}


def infer_source_type(filename: str) -> SourceType:
    """Infer the SourceType from a filename or key.

    Args:
        filename: File name or S3 key.

    Returns:
        Inferred SourceType enum value.
    """
    ext = Path(filename).suffix.lower()
    return _EXTENSION_TYPE_MAP.get(ext, SourceType.UNKNOWN)


def build_document_id(source_uri: str) -> str:
    """Generate a stable document_id from the source URI.

    Uses SHA-256 of the normalized URI for deterministic IDs.

    Args:
        source_uri: S3 URI or local file path.

    Returns:
        Hex string document_id (prefix: doc_).
    """
    return make_document_id(source_uri)


def calculate_content_hash(data: bytes) -> str:
    """Calculate SHA-256 content hash from file bytes.

    Args:
        data: Raw file content bytes.

    Returns:
        Hex digest of the content hash.
    """
    return content_hash(data)


def register_documents(
    file_records: list[dict],
    content_bytes_map: Optional[dict[str, bytes]] = None,
) -> list[SourceDocument]:
    """Register a batch of file records as SourceDocuments.

    Args:
        file_records: List of dicts with keys: uri, key, size, last_modified, etag, content_type.
            Typically from S3Client.list_objects() converted to dicts.
        content_bytes_map: Optional mapping of URI → file bytes for hash calculation.
            If not provided, content_hash will be derived from etag.

    Returns:
        List of SourceDocument models with stable IDs.
    """
    documents: list[SourceDocument] = []
    now = datetime.now(timezone.utc)

    for record in file_records:
        uri = record["uri"]
        key = record.get("key", "")

        # Compute content_hash
        if content_bytes_map and uri in content_bytes_map:
            c_hash = calculate_content_hash(content_bytes_map[uri])
        else:
            # Fallback to etag as a proxy for content identity
            etag = record.get("etag", "")
            c_hash = etag if etag else ""

        doc = SourceDocument(
            document_id=build_document_id(uri),
            source_uri=uri,
            source_type=infer_source_type(key or uri),
            filename=Path(key or uri).name,
            file_size=record.get("size", 0),
            content_hash=c_hash,
            s3_bucket=record.get("bucket", ""),
            s3_key=key,
            s3_etag=record.get("etag", ""),
            last_modified=record.get("last_modified"),
            created_at=now,
        )
        documents.append(doc)

    logger.info("Registered %d documents", len(documents))
    return documents


def detect_new_or_changed(
    current: list[SourceDocument],
    previous: list[SourceDocument],
) -> tuple[list[SourceDocument], list[SourceDocument]]:
    """Detect new and changed documents by comparing content_hash.

    Args:
        current: Current scan results.
        previous: Previous registry snapshot.

    Returns:
        Tuple of (new_documents, changed_documents).
    """
    prev_map = {doc.document_id: doc for doc in previous}

    new_docs: list[SourceDocument] = []
    changed_docs: list[SourceDocument] = []

    for doc in current:
        prev = prev_map.get(doc.document_id)
        if prev is None:
            new_docs.append(doc)
        elif doc.content_hash and doc.content_hash != prev.content_hash:
            changed_docs.append(doc)

    logger.info(
        "Incremental check: %d new, %d changed (of %d total)",
        len(new_docs),
        len(changed_docs),
        len(current),
    )
    return new_docs, changed_docs
