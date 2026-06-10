"""Shared parsing utilities: hashing, S3 download, filename sanitization."""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path, PurePosixPath


def compute_content_hash(path: Path, max_bytes: int = 65536) -> str:
    """SHA-256 of first max_bytes of file content."""
    raw = path.read_bytes()[:max_bytes]
    return hashlib.sha256(raw).hexdigest()[:16]


def download_s3_file(s3_uri: str, local_path: Path) -> None:
    """Download a single S3 file to local_path."""
    import boto3

    parts = s3_uri[5:].split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    boto3.client("s3").download_file(bucket, key, str(local_path))


def sanitize_filename(relative_path: str) -> str:
    """Generate a safe output filename from relative_path."""
    normalized = unicodedata.normalize("NFC", relative_path)
    p = PurePosixPath(normalized)
    parts = p.parts
    ext = p.suffix.lstrip(".")
    if len(parts) > 1:
        name = "__".join(parts[-2:])
    else:
        name = parts[0] if parts else "unknown"
    stem = PurePosixPath(name).stem
    safe = stem.replace("/", "_").replace("\\", "_").replace(" ", "_")
    if ext and ext not in ("md", ""):
        safe = f"{safe}_{ext}"
    if len(safe) > 120:
        safe = safe[:120]
    return safe
