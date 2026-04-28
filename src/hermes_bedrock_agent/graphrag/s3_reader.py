"""S3 read/write helpers for GraphRAG."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TransferSpeedColumn

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def _s3_client(region: str) -> "S3Client":
    return boto3.client("s3", region_name=region)


def list_files(bucket: str, prefix: str, region: str = "ap-northeast-1") -> list[dict[str, object]]:
    """List S3 objects under *prefix* in *bucket*.

    Returns a list of dicts with keys: ``key``, ``size``, ``last_modified``.
    """
    client = _s3_client(region)
    paginator = client.get_paginator("list_objects_v2")
    results: list[dict[str, object]] = []
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                results.append(
                    {
                        "key": obj["Key"],
                        "size": obj.get("Size", 0),
                        "last_modified": str(obj.get("LastModified", "")),
                    }
                )
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(f"Failed to list S3 objects in s3://{bucket}/{prefix}: {exc}") from exc
    return results


def download_file(bucket: str, s3_key: str, region: str = "ap-northeast-1") -> bytes:
    """Download an S3 object into memory and return its raw bytes."""
    client = _s3_client(region)
    try:
        response = client.get_object(Bucket=bucket, Key=s3_key)
        return response["Body"].read()
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(f"Failed to download s3://{bucket}/{s3_key}: {exc}") from exc


def upload_file(
    local_path: Path,
    bucket: str,
    s3_key: str,
    region: str = "ap-northeast-1",
    show_progress: bool = True,
) -> None:
    """Upload *local_path* to s3://*bucket*/*s3_key* with optional rich progress bar."""
    client = _s3_client(region)
    file_size = local_path.stat().st_size

    if show_progress:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TransferSpeedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(f"Uploading {local_path.name}", total=file_size)

            def _callback(bytes_transferred: int) -> None:
                progress.update(task, advance=bytes_transferred)

            try:
                client.upload_file(
                    str(local_path),
                    bucket,
                    s3_key,
                    Callback=_callback,
                )
            except (ClientError, BotoCoreError) as exc:
                raise RuntimeError(f"Failed to upload {local_path} to s3://{bucket}/{s3_key}: {exc}") from exc
    else:
        try:
            client.upload_file(str(local_path), bucket, s3_key)
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to upload {local_path} to s3://{bucket}/{s3_key}: {exc}") from exc
