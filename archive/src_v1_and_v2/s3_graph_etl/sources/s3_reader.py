"""S3 reader - scan and download objects from S3."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Iterator

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.config import S3Config
from hermes_bedrock_agent.s3_graph_etl.schemas import FileRecord

logger = logging.getLogger(__name__)


class S3Reader:
    """Scan and read files from an S3 bucket."""

    SUPPORTED_EXTENSIONS = {
        ".pdf", ".txt", ".md", ".markdown",
        ".docx", ".doc",
        ".sql", ".ddl",
        ".py", ".java", ".js", ".ts", ".tsx", ".jsx",
        ".yaml", ".yml", ".json", ".xml",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff",
        ".xlsx", ".xls", ".csv",
        ".pptx",
    }

    def __init__(self, config: S3Config | None = None) -> None:
        if config is None:
            config = S3Config.from_env()
        self.config = config
        self._client = boto3.client("s3", region_name=config.region)

    def scan(self, prefix: str | None = None, max_files: int | None = None) -> list[FileRecord]:
        """Scan S3 for supported files and return FileRecords."""
        use_prefix = prefix if prefix is not None else self.config.prefix
        records: list[FileRecord] = []

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.config.bucket, Prefix=use_prefix)

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    ext = Path(key).suffix.lower()

                    if ext not in self.SUPPORTED_EXTENSIONS:
                        continue
                    if key.endswith("/"):
                        continue

                    record = FileRecord(
                        uri=f"s3://{self.config.bucket}/{key}",
                        bucket=self.config.bucket,
                        key=key,
                        size=obj.get("Size", 0),
                        last_modified=str(obj.get("LastModified", "")),
                        etag=obj.get("ETag", "").strip('"'),
                        content_type=self._guess_content_type(ext),
                    )
                    records.append(record)

                    if max_files and len(records) >= max_files:
                        return records

        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 scan failed: %s", exc)
            raise

        logger.info("Scanned %d supported files from s3://%s/%s", len(records), self.config.bucket, use_prefix)
        return records

    def download_to_temp(self, key: str) -> Path:
        """Download an S3 object to a temporary file and return the path."""
        ext = Path(key).suffix
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            self._client.download_file(self.config.bucket, key, tmp.name)
            return Path(tmp.name)
        except (ClientError, BotoCoreError) as exc:
            logger.error("Download failed for %s: %s", key, exc)
            raise

    def download_bytes(self, key: str) -> bytes:
        """Download an S3 object as bytes."""
        try:
            response = self._client.get_object(Bucket=self.config.bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            logger.error("Download bytes failed for %s: %s", key, exc)
            raise

    @staticmethod
    def _guess_content_type(ext: str) -> str:
        mapping = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".sql": "text/x-sql",
            ".ddl": "text/x-sql",
            ".py": "text/x-python",
            ".java": "text/x-java",
            ".js": "text/javascript",
            ".ts": "text/typescript",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".csv": "text/csv",
        }
        return mapping.get(ext, "application/octet-stream")
