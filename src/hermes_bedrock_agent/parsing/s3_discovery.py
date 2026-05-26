"""Stage 1: S3 Discovery — scan a prefix, classify files, build a WorkManifest."""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import PurePosixPath
from typing import Optional

from ..clients.s3 import download_file, list_objects, parse_s3_uri
from ..config import Config, config as _default_config
from .models import FileType, S3File, WorkManifest

logger = logging.getLogger(__name__)

_EXT_MAP: dict[str, FileType] = {
    ".xlsx": FileType.EXCEL,
    ".xls": FileType.EXCEL,
    ".xlsm": FileType.EXCEL,
    ".pdf": FileType.PDF,
    ".png": FileType.IMAGE,
    ".jpg": FileType.IMAGE,
    ".jpeg": FileType.IMAGE,
    ".tiff": FileType.IMAGE,
    ".tif": FileType.IMAGE,
    ".mmd": FileType.MERMAID,
    ".md": FileType.MARKDOWN,
}

_SKIP_PATTERNS = ("~$*", ".*", ".~lock.*")


def _classify(key: str) -> FileType:
    return _EXT_MAP.get(PurePosixPath(key).suffix.lower(), FileType.UNKNOWN)


def _should_skip(key: str) -> bool:
    name = PurePosixPath(key).name
    return any(fnmatch.fnmatch(name, pat) for pat in _SKIP_PATTERNS)


def discover(
    s3_prefix: str,
    cfg: Optional[Config] = None,
    file_types: Optional[list[FileType]] = None,
    subdir_filter: Optional[str] = None,
    pattern_filter: Optional[str] = None,
) -> WorkManifest:
    """Scan an S3 prefix and return a WorkManifest."""
    cfg = cfg or _default_config

    if s3_prefix.startswith("s3://"):
        rest = s3_prefix[5:]
        bucket, _, prefix = rest.partition("/")
    else:
        bucket = cfg.s3_bucket
        prefix = s3_prefix

    logger.info("Scanning s3://%s/%s …", bucket, prefix)
    raw = list_objects(bucket, prefix, region=cfg.aws_region)
    logger.info("  Found %d raw objects", len(raw))

    files: list[S3File] = []
    for obj in raw:
        key: str = obj["Key"]
        size: int = obj.get("Size", 0)
        if _should_skip(key) or size == 0:
            continue
        ft = _classify(key)
        if file_types and ft not in file_types:
            continue
        if subdir_filter and subdir_filter not in key:
            continue
        if pattern_filter and not fnmatch.fnmatch(PurePosixPath(key).name, pattern_filter):
            continue
        files.append(S3File(key=key, size=size, file_type=ft))

    excel_files = [f for f in files if f.file_type == FileType.EXCEL]
    ground_truth: dict[str, S3File] = {
        PurePosixPath(f.key).stem: f
        for f in files
        if f.file_type in (FileType.MERMAID, FileType.MARKDOWN)
    }

    manifest = WorkManifest(
        s3_prefix=f"s3://{bucket}/{prefix}",
        files=files,
        excel_files=excel_files,
        ground_truth_files=ground_truth,
    )
    logger.info(
        "  Manifest: %d total, %d excel, %d ground-truth",
        len(files), len(excel_files), len(ground_truth),
    )
    return manifest


def download_excel_files(
    manifest: WorkManifest,
    local_base: str,
    cfg: Optional[Config] = None,
) -> WorkManifest:
    """Download all excel files in the manifest to local_base/<filename>."""
    cfg = cfg or _default_config
    bucket, _ = parse_s3_uri(manifest.s3_prefix)

    updated: list[S3File] = []
    for sf in manifest.excel_files:
        filename = PurePosixPath(sf.key).name
        local_path = os.path.join(local_base, filename)
        if not os.path.exists(local_path):
            logger.info("  Downloading %s → %s", sf.key, local_path)
            download_file(bucket, sf.key, local_path, region=cfg.aws_region)
        else:
            logger.info("  Already local: %s", local_path)
        updated.append(sf.model_copy(update={"local_path": local_path}))

    return manifest.model_copy(update={"excel_files": updated})
