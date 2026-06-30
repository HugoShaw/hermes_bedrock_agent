"""Project scanner: walk S3 or local directories to build a ProjectManifest."""

from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from typing import Optional

import boto3

from ..models.document import (
    ProjectFile,
    ProjectManifest,
    SourceType,
    classify_extension,
    should_skip,
)

logger = logging.getLogger(__name__)


def scan_s3_project(
    bucket: str,
    prefix: str,
    project_id: str,
    display_name: str = "",
) -> ProjectManifest:
    """Walk an S3 prefix recursively and build a ProjectManifest."""
    s3 = boto3.client("s3")
    prefix = prefix.rstrip("/") + "/"

    files: list[ProjectFile] = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj["Size"]

            rel_path = key[len(prefix):]
            if not rel_path:
                continue

            filename = PurePosixPath(rel_path).name
            if should_skip(filename):
                continue

            # Skip directories (zero-byte keys ending with /)
            if key.endswith("/") and size == 0:
                continue

            source_type = classify_extension(filename)
            parent = str(PurePosixPath(rel_path).parent)
            if parent == ".":
                parent = ""

            files.append(ProjectFile(
                path=f"s3://{bucket}/{key}",
                source_type=source_type,
                size_bytes=size,
                relative_path=rel_path,
                parent_folder=parent,
            ))

    manifest = ProjectManifest(
        project_id=project_id,
        display_name=display_name or project_id,
        source_location=f"s3://{bucket}/{prefix}",
        files=files,
    )

    logger.info(
        "Scanned s3://%s/%s: %d files (%s)",
        bucket, prefix, len(files),
        ", ".join(f"{k}={v}" for k, v in sorted(manifest.type_counts().items())),
    )
    return manifest


def scan_local_project(
    path: str | Path,
    project_id: str,
    display_name: str = "",
) -> ProjectManifest:
    """Walk a local directory recursively and build a ProjectManifest."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    files: list[ProjectFile] = []

    for item in sorted(root.rglob("*")):
        if item.is_dir():
            continue
        if should_skip(item.name):
            continue

        rel_path = str(item.relative_to(root))
        source_type = classify_extension(item.name)
        parent = str(item.parent.relative_to(root))
        if parent == ".":
            parent = ""

        files.append(ProjectFile(
            path=str(item),
            source_type=source_type,
            size_bytes=item.stat().st_size,
            relative_path=rel_path,
            parent_folder=parent,
        ))

    manifest = ProjectManifest(
        project_id=project_id,
        display_name=display_name or project_id,
        source_location=str(root),
        files=files,
    )

    logger.info(
        "Scanned %s: %d files (%s)",
        root, len(files),
        ", ".join(f"{k}={v}" for k, v in sorted(manifest.type_counts().items())),
    )
    return manifest


def get_project_sheet_count(
    project_id: str, manifest_dir: Optional[Path] = None
) -> Optional[int]:
    """Load a project manifest and return the Excel file count.

    Returns None if manifest not found or field missing.
    """
    if manifest_dir is None:
        manifest_dir = Path("outputs") / project_id
    manifest_path = manifest_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path) as f:
            data = json.load(f)
        return data.get("parseable_counts", {}).get("excel_count", None)
    except (json.JSONDecodeError, OSError):
        return None
