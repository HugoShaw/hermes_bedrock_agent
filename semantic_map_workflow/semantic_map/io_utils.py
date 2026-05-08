"""
S3 and local file I/O utilities for the semantic map workflow.

Provides helpers for listing, downloading, reading, and writing files both
locally and from Amazon S3, as well as stage-completion markers used by the
pipeline to implement idempotent restarts.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional boto3 import – only required for S3 operations
# ---------------------------------------------------------------------------
try:
    import boto3  # noqa: F401
    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover
    _BOTO3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Local file helpers
# ---------------------------------------------------------------------------

def list_local_files(
    root_dir: str,
    max_files: Optional[int] = None,
) -> list[dict]:
    """Return a list of file-info dicts for every file under *root_dir*.

    Each dict contains:
      - ``path``     – absolute path string
      - ``name``     – file name without directory
      - ``ext``      – lower-cased extension (e.g. ``".py"``)
      - ``size``     – file size in bytes
      - ``rel_path`` – path relative to *root_dir*

    Parameters
    ----------
    root_dir:
        Directory to walk recursively.
    max_files:
        When set, stop after collecting this many entries.

    Returns
    -------
    list[dict]
        Sorted by ``rel_path``.
    """
    root = Path(root_dir).resolve()
    if not root.is_dir():
        logger.warning("list_local_files: %s is not a directory", root_dir)
        return []

    results: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            abs_path = Path(dirpath) / fname
            try:
                size = abs_path.stat().st_size
            except OSError as exc:
                logger.debug("Cannot stat %s: %s", abs_path, exc)
                continue

            rel = abs_path.relative_to(root)
            results.append(
                {
                    "path": str(abs_path),
                    "name": fname,
                    "ext": abs_path.suffix.lower(),
                    "size": size,
                    "rel_path": str(rel),
                }
            )
            if max_files is not None and len(results) >= max_files:
                logger.debug(
                    "list_local_files: reached max_files=%d, stopping early",
                    max_files,
                )
                return results

    logger.debug("list_local_files: found %d files under %s", len(results), root_dir)
    return results


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _s3_client(aws_region: str):
    """Return a boto3 S3 client for *aws_region*."""
    if not _BOTO3_AVAILABLE:
        raise ImportError(
            "boto3 is required for S3 operations. Install it with: pip install boto3"
        )
    return boto3.client("s3", region_name=aws_region)


def list_s3_files(
    bucket: str,
    prefix: str,
    aws_region: str,
    max_files: Optional[int] = None,
) -> list[dict]:
    """Return a list of file-info dicts for every object under *bucket/prefix*.

    Each dict contains:
      - ``s3_key``   – full S3 object key
      - ``name``     – last path component of the key
      - ``ext``      – lower-cased extension
      - ``size``     – object size in bytes
      - ``rel_path`` – key with *prefix* stripped

    Parameters
    ----------
    bucket:
        S3 bucket name.
    prefix:
        Key prefix to list under (e.g. ``"data/docs/"``).
    aws_region:
        AWS region string.
    max_files:
        When set, stop after collecting this many entries.

    Returns
    -------
    list[dict]
    """
    client = _s3_client(aws_region)

    # Normalise prefix – ensure it ends with "/" if non-empty
    normalised_prefix = prefix.rstrip("/") + "/" if prefix else ""

    paginator = client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=normalised_prefix)

    results: list[dict] = []
    try:
        for page in pages:
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                # Skip "directory" placeholder objects
                if key.endswith("/"):
                    continue

                name = key.rsplit("/", 1)[-1]
                ext = Path(name).suffix.lower()
                rel = key[len(normalised_prefix):] if key.startswith(normalised_prefix) else key

                results.append(
                    {
                        "s3_key": key,
                        "name": name,
                        "ext": ext,
                        "size": obj.get("Size", 0),
                        "rel_path": rel,
                    }
                )

                if max_files is not None and len(results) >= max_files:
                    logger.debug(
                        "list_s3_files: reached max_files=%d, stopping early",
                        max_files,
                    )
                    return results
    except Exception as exc:
        logger.error("list_s3_files error for s3://%s/%s: %s", bucket, prefix, exc)
        raise

    logger.debug(
        "list_s3_files: found %d objects under s3://%s/%s",
        len(results),
        bucket,
        normalised_prefix,
    )
    return results


def download_s3_file(
    bucket: str,
    key: str,
    local_path: str,
    aws_region: str,
) -> str:
    """Download an S3 object to *local_path*.

    Creates any missing parent directories automatically.

    Parameters
    ----------
    bucket:
        S3 bucket name.
    key:
        Object key.
    local_path:
        Destination path on the local filesystem.
    aws_region:
        AWS region string.

    Returns
    -------
    str
        The resolved *local_path*.
    """
    client = _s3_client(aws_region)
    dest = Path(local_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("Downloading s3://%s/%s -> %s", bucket, key, dest)
    try:
        client.download_file(bucket, key, str(dest))
    except Exception as exc:
        logger.error(
            "download_s3_file failed for s3://%s/%s: %s", bucket, key, exc
        )
        raise

    return str(dest)


def ensure_local_copy(
    file_info: dict,
    bucket: str,
    tmp_dir: str,
    aws_region: str,
) -> str:
    """Ensure that the file described by *file_info* is available locally.

    If *file_info* contains an ``s3_key`` the object is downloaded to
    ``tmp_dir/<s3_key>`` unless that destination already exists (cache hit).
    Otherwise the ``path`` key is returned directly.

    Parameters
    ----------
    file_info:
        Dict as returned by :func:`list_local_files` or :func:`list_s3_files`.
    bucket:
        S3 bucket (used only when ``s3_key`` is present).
    tmp_dir:
        Local directory to cache downloaded files.
    aws_region:
        AWS region string.

    Returns
    -------
    str
        Absolute path to the local file.
    """
    if "s3_key" in file_info:
        s3_key: str = file_info["s3_key"]
        local_path = Path(tmp_dir) / s3_key
        if local_path.exists():
            logger.debug("Cache hit for s3://%s/%s -> %s", bucket, s3_key, local_path)
            return str(local_path)
        return download_s3_file(bucket, s3_key, str(local_path), aws_region)

    path = file_info.get("path", "")
    if not path:
        raise ValueError("file_info must contain either 's3_key' or 'path'")
    return path


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def write_jsonl(records: list[dict], path: str) -> None:
    """Write *records* as newline-delimited JSON (one record per line).

    Parameters
    ----------
    records:
        List of JSON-serialisable dicts.
    path:
        Destination file path.  Parent directories are created automatically.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.debug("write_jsonl: wrote %d records to %s", len(records), path)


def read_jsonl(path: str) -> list[dict]:
    """Read a newline-delimited JSON file and return a list of dicts.

    Lines that are blank or start with ``#`` are skipped.  Malformed lines
    are logged and skipped rather than raising.

    Parameters
    ----------
    path:
        Source file path.

    Returns
    -------
    list[dict]
    """
    records: list[dict] = []
    src = Path(path)
    if not src.exists():
        logger.warning("read_jsonl: file not found: %s", path)
        return records

    with src.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                logger.warning(
                    "read_jsonl: skipping malformed line %d in %s: %s",
                    lineno,
                    path,
                    exc,
                )

    logger.debug("read_jsonl: read %d records from %s", len(records), path)
    return records


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def write_json(data: Any, path: str, indent: int = 2) -> None:
    """Write *data* as pretty-printed JSON.

    Parameters
    ----------
    data:
        JSON-serialisable value.
    path:
        Destination file path.  Parent directories are created automatically.
    indent:
        JSON indentation level (default ``2``).
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)
    logger.debug("write_json: wrote to %s", path)


def read_json(path: str) -> dict:
    """Read a JSON file and return the parsed object.

    Parameters
    ----------
    path:
        Source file path.

    Returns
    -------
    dict
        Parsed JSON content (or empty dict if the file is missing/unreadable).
    """
    src = Path(path)
    if not src.exists():
        logger.warning("read_json: file not found: %s", path)
        return {}

    try:
        with src.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("read_json: failed to read %s: %s", path, exc)
        return {}


# ---------------------------------------------------------------------------
# Stage markers
# ---------------------------------------------------------------------------

def stage_output_exists(stage_dir: str, marker_file: str = "complete.json") -> bool:
    """Return ``True`` when *stage_dir/marker_file* exists and is non-empty.

    Parameters
    ----------
    stage_dir:
        Directory written by a pipeline stage.
    marker_file:
        Filename of the completion marker (default ``"complete.json"``).
    """
    marker = Path(stage_dir) / marker_file
    if not marker.exists():
        return False
    return marker.stat().st_size > 0


def write_stage_complete(stage_dir: str, metadata: dict) -> None:
    """Write a *complete.json* marker into *stage_dir*.

    The marker includes a UTC timestamp alongside any caller-supplied
    *metadata*.

    Parameters
    ----------
    stage_dir:
        Directory to write the marker into.  Created if it does not exist.
    metadata:
        Arbitrary metadata to embed in the marker (e.g. record counts, model
        version).
    """
    payload = {
        "completed_at": datetime.now(tz=timezone.utc).isoformat(),
        **metadata,
    }
    marker_path = str(Path(stage_dir) / "complete.json")
    write_json(payload, marker_path)
    logger.info("Stage complete marker written to %s", marker_path)
