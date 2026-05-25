"""S3 download/upload helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import boto3


def _s3_client(region: str = "ap-northeast-1"):
    return boto3.client("s3", region_name=region)


def list_objects(
    bucket: str,
    prefix: str,
    region: str = "ap-northeast-1",
) -> list[dict]:
    """Return all object metadata dicts under prefix (handles pagination)."""
    s3 = _s3_client(region)
    objects: list[dict] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects.extend(page.get("Contents", []))
    return objects


def download_file(
    bucket: str,
    key: str,
    local_path: str,
    region: str = "ap-northeast-1",
) -> str:
    """Download s3://bucket/key to local_path. Creates parent dirs. Returns local_path."""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    s3 = _s3_client(region)
    s3.download_file(bucket, key, local_path)
    return local_path


def upload_file(
    local_path: str,
    bucket: str,
    key: str,
    region: str = "ap-northeast-1",
) -> str:
    """Upload local_path to s3://bucket/key. Returns the S3 URI."""
    s3 = _s3_client(region)
    s3.upload_file(local_path, bucket, key)
    return f"s3://{bucket}/{key}"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse 's3://bucket/key' → (bucket, key)."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {uri}")
    rest = uri[5:]
    bucket, _, key = rest.partition("/")
    return bucket, key
