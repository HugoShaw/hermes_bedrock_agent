"""Low-level S3 client wrapper.

Handles S3 object listing, downloading, and metadata retrieval.
Does NOT contain business logic like file routing or content parsing.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.configs.settings import S3Settings, get_settings

logger = get_logger(__name__)


@dataclass
class S3Object:
    """Metadata about an S3 object discovered during scanning."""

    bucket: str
    key: str
    size: int
    last_modified: Optional[datetime]
    etag: str
    content_type: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"

    @property
    def extension(self) -> str:
        return Path(self.key).suffix.lower()

    @property
    def filename(self) -> str:
        return Path(self.key).name


class S3Client:
    """Low-level S3 operations — scan, download, head.

    Handles paginated listing, byte-level downloads, and object metadata.
    Does NOT interpret file contents or apply business logic.
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        boto_client: Optional[Any] = None,
    ) -> None:
        """Initialize S3 client.

        Args:
            bucket: Default bucket name. If None, read from settings.
            region: AWS region. If None, read from settings.
            boto_client: Optional pre-built boto3 client (for testing/mocking).
        """
        settings = get_settings().s3
        self._bucket = bucket or settings.bucket
        self._region = region or settings.region
        self._provided_client = boto_client
        self._client: Optional[Any] = boto_client

    @property
    def client(self) -> Any:
        """Lazily create boto3 S3 client."""
        if self._client is None:
            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    @property
    def bucket(self) -> str:
        return self._bucket

    def list_objects(
        self,
        prefix: str = "",
        max_keys: Optional[int] = None,
        extensions: Optional[set[str]] = None,
    ) -> list[S3Object]:
        """List objects in the bucket with optional filtering.

        Args:
            prefix: Key prefix to filter by.
            max_keys: Maximum number of objects to return.
            extensions: Set of allowed file extensions (e.g. {'.pdf', '.md'}).

        Returns:
            List of S3Object metadata records.

        Raises:
            S3ClientError: On AWS API errors.
        """
        objects: list[S3Object] = []
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    # Skip directory markers
                    if key.endswith("/"):
                        continue

                    # Extension filter
                    if extensions:
                        ext = Path(key).suffix.lower()
                        if ext not in extensions:
                            continue

                    s3_obj = S3Object(
                        bucket=self._bucket,
                        key=key,
                        size=obj.get("Size", 0),
                        last_modified=obj.get("LastModified"),
                        etag=obj.get("ETag", "").strip('"'),
                        content_type=self._infer_content_type(key),
                    )
                    objects.append(s3_obj)

                    if max_keys and len(objects) >= max_keys:
                        return objects

        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(exc))
            logger.error("S3 list failed [%s]: %s", code, message)
            raise S3ClientError(f"S3 list [{code}]: {message}", code=code) from exc
        except BotoCoreError as exc:
            logger.error("S3 SDK error: %s", exc)
            raise S3ClientError(f"AWS SDK error: {exc}") from exc

        logger.debug("Listed %d objects from s3://%s/%s", len(objects), self._bucket, prefix)
        return objects

    def download_bytes(self, key: str) -> bytes:
        """Download an S3 object as bytes.

        Args:
            key: Object key in the bucket.

        Returns:
            Raw file bytes.

        Raises:
            S3ClientError: On download failure.
        """
        try:
            response = self.client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 download failed for %s: %s", key, exc)
            raise S3ClientError(f"S3 download failed: {key} - {exc}") from exc

    def download_to_file(self, key: str, dest: Optional[Path] = None) -> Path:
        """Download an S3 object to a local file.

        Args:
            key: Object key in the bucket.
            dest: Destination path. If None, uses a temp file.

        Returns:
            Path to the downloaded file.

        Raises:
            S3ClientError: On download failure.
        """
        if dest is None:
            ext = Path(key).suffix
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            dest = Path(tmp.name)
            tmp.close()

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self._bucket, key, str(dest))
            return dest
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 download to file failed for %s: %s", key, exc)
            raise S3ClientError(f"S3 download failed: {key} - {exc}") from exc

    def head_object(self, key: str) -> dict[str, Any]:
        """Get object metadata without downloading content.

        Args:
            key: Object key.

        Returns:
            Head response dict (ContentLength, ContentType, LastModified, etc.)

        Raises:
            S3ClientError: On failure (including 404).
        """
        try:
            return self.client.head_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise S3ClientError(f"S3 head failed: {key} - {exc}") from exc

    def object_exists(self, key: str) -> bool:
        """Check if an object exists in the bucket."""
        try:
            self.client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "404":
                return False
            raise S3ClientError(f"S3 head failed: {key}") from exc

    @staticmethod
    def _infer_content_type(key: str) -> str:
        """Infer content type from file extension."""
        ext = Path(key).suffix.lower()
        mapping = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".sql": "text/x-sql",
            ".ddl": "text/x-sql",
            ".py": "text/x-python",
            ".yaml": "text/yaml",
            ".yml": "text/yaml",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".csv": "text/csv",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        return mapping.get(ext, "application/octet-stream")


class S3ClientError(Exception):
    """Raised when an S3 API call fails."""

    def __init__(self, message: str, code: str = "Unknown") -> None:
        super().__init__(message)
        self.code = code
