"""S3 I/O operations for the pipeline."""
import os
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig


class S3IO:
    """S3 read/write operations."""

    def __init__(self, bucket: str, region: str = "ap-northeast-1"):
        self.bucket = bucket
        self.region = region
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                config=BotoConfig(read_timeout=120, retries={"max_attempts": 3}),
            )
        return self._client

    def list_objects(self, prefix: str, extensions: Optional[list] = None) -> list:
        """List objects under a prefix, optionally filtering by extension."""
        objects = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                if extensions:
                    if not any(key.lower().endswith(ext) for ext in extensions):
                        continue
                objects.append({
                    "key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "etag": obj.get("ETag", "").strip('"'),
                })
        return objects

    def download_file(self, key: str, local_path: Path) -> Path:
        """Download a file from S3 to local path."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(local_path))
        return local_path

    def upload_file(self, local_path: Path, key: str):
        """Upload a local file to S3."""
        self.client.upload_file(str(local_path), self.bucket, key)

    def sync_directory(self, local_dir: Path, s3_prefix: str):
        """Sync a local directory to S3 prefix."""
        for root, dirs, files in os.walk(local_dir):
            for fname in files:
                local_file = Path(root) / fname
                relative = local_file.relative_to(local_dir)
                s3_key = f"{s3_prefix.rstrip('/')}/{relative}"
                self.upload_file(local_file, s3_key)
