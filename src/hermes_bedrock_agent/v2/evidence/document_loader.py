"""
Document loader for the V2 evidence pipeline.

Scans the configured S3 prefix, downloads each supported file, and emits
a DocumentRecord for each one. No V1 code is imported; boto3 is used directly.

Doc-type inference rules
------------------------
Extension-first, then path/name heuristics:

  .sql / .ddl             → database_doc
  .java / .py / .js / .ts → source_code
  .xml / .yaml / .yml
   / .json / .properties  → config
  .xlsx / .csv            → business_doc
  .pptx                   → business_doc
  .docx  (操作手册 in path) → operation_doc
  .docx  (支払|申請|MDW)   → business_doc
  .docx  (other)          → business_doc
  .md / .txt              → classified further by content
  unknown ext             → unknown
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord

logger = logging.getLogger(__name__)

# Extensions the loader will process
SUPPORTED_EXTENSIONS = {
    ".sql", ".ddl",
    ".java", ".py", ".js", ".ts",
    ".docx",
    ".xlsx", ".csv",
    ".xml", ".yaml", ".yml", ".json", ".properties",
    ".pptx",
    ".md", ".txt",
}


def _infer_doc_type(key: str) -> str:
    """Return a doc_type string from an S3 key."""
    p = Path(key)
    ext = p.suffix.lower()
    name = p.name
    key_lower = key.lower()

    if ext in (".sql", ".ddl"):
        return "database_doc"
    if ext in (".java", ".py", ".js", ".ts"):
        return "source_code"
    if ext in (".xml", ".yaml", ".yml", ".json", ".properties"):
        return "config"
    if ext in (".xlsx", ".csv"):
        return "business_doc"
    if ext == ".pptx":
        return "business_doc"
    if ext == ".docx":
        if "操作手册" in key or "操作手册" in name:
            return "operation_doc"
        if re.search(r"支払|申請|MDW", key):
            return "business_doc"
        return "business_doc"
    if ext in (".md", ".txt"):
        return "unknown"  # further refined by content in structure parser
    return "unknown"


def _infer_language(key: str) -> str:
    """Best-effort language guess from the S3 key path."""
    key_lower = key.lower()
    # Murata docs are predominantly Japanese
    if any(ch in key for ch in "あいうえおかきくけこ"):
        return "ja"
    if re.search(r"[一-鿿]", key):
        # Could be CJK — default ja for Murata
        return "ja"
    if re.search(r"[぀-ゟ゠-ヿ]", key):
        return "ja"
    return "ja"  # Murata corpus default


def _make_title(key: str) -> str:
    """Derive a human-readable title from the S3 key."""
    return Path(key).stem


class DocumentLoader:
    """Load S3 files and produce DocumentRecord objects.

    Parameters
    ----------
    bucket:
        S3 bucket name (e.g. ``s3-hulftchina-rd``).
    prefix:
        S3 key prefix to scan (e.g. ``Murata/``).
    dataset:
        Dataset label written into every DocumentRecord.
    run_id:
        Run identifier written into every DocumentRecord.
    project:
        Project name written into every DocumentRecord.
    region:
        AWS region for the S3 client.
    max_files:
        Hard limit on the number of files loaded (useful in dev).
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        dataset: str = "murata",
        run_id: str = "murata_semantic_v2",
        project: str = "murata",
        region: str = "ap-northeast-1",
        max_files: int | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.dataset = dataset
        self.run_id = run_id
        self.project = project
        self.region = region
        self.max_files = max_files
        self._s3 = boto3.client("s3", region_name=region)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_keys(self) -> list[str]:
        """Return all supported S3 keys under *prefix*."""
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        try:
            pages = paginator.paginate(Bucket=self.bucket, Prefix=self.prefix)
            for page in pages:
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    if key.endswith("/"):
                        continue
                    ext = Path(key).suffix.lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue
                    keys.append(key)
                    if self.max_files and len(keys) >= self.max_files:
                        return keys
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 list failed for s3://%s/%s: %s", self.bucket, self.prefix, exc)
            raise
        logger.info("Found %d supported files under s3://%s/%s", len(keys), self.bucket, self.prefix)
        return keys

    def load(self, keys: list[str] | None = None) -> list[tuple[DocumentRecord, bytes]]:
        """Download S3 files and build DocumentRecord + raw bytes pairs.

        Args:
            keys: Explicit list of S3 keys. Calls ``list_keys()`` when None.

        Returns:
            List of ``(DocumentRecord, raw_bytes)`` tuples. Files that fail
            to download are skipped with a warning.
        """
        if keys is None:
            keys = self.list_keys()

        results: list[tuple[DocumentRecord, bytes]] = []
        for key in keys:
            try:
                raw = self._download_bytes(key)
            except Exception as exc:
                logger.warning("Skipping %s — download failed: %s", key, exc)
                continue

            doc = self._make_record(key, raw)
            results.append((doc, raw))

        logger.info("Loaded %d documents from S3", len(results))
        return results

    def load_records_only(self, keys: list[str] | None = None) -> list[DocumentRecord]:
        """Return DocumentRecord objects without holding raw bytes in memory."""
        pairs = self.load(keys)
        return [doc for doc, _ in pairs]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _download_bytes(self, key: str) -> bytes:
        response = self._s3.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def _make_record(self, key: str, raw: bytes) -> DocumentRecord:
        doc_type = _infer_doc_type(key)
        language = _infer_language(key)
        title = _make_title(key)
        size = len(raw)

        # Refine doc_type for text/md files using content signals
        ext = Path(key).suffix.lower()
        if ext in (".txt", ".md") and doc_type == "unknown":
            doc_type = _classify_text_content(raw, key)

        document_id = DocumentRecord.generate_id(key, self.dataset)
        return DocumentRecord(
            document_id=document_id,
            project=self.project,
            dataset=self.dataset,
            run_id=self.run_id,
            source_path=key,
            doc_type=doc_type,
            title=title,
            language=language,
            metadata={
                "s3_bucket": self.bucket,
                "s3_key": key,
                "size_bytes": size,
                "extension": ext,
            },
        )


def _classify_text_content(raw: bytes, key: str) -> str:
    """Classify a text/md file's doc_type based on its content."""
    try:
        text = raw.decode("utf-8", errors="replace")[:2000]
    except Exception:
        return "unknown"

    text_lower = text.lower()
    key_lower = key.lower()

    # SQL content signals
    sql_keywords = ("create table", "create index", "insert into", "select ", "alter table", "drop table")
    if any(kw in text_lower for kw in sql_keywords):
        return "database_doc"

    # Code signals
    if re.search(r"(public class|import java|def |class |function |const |var |let )", text):
        return "source_code"

    # Config signals
    if re.search(r"(<\?xml|<!DOCTYPE|<root>|<config>)", text):
        return "config"

    # Operation manual signals
    if "操作" in text or "手順" in text or "マニュアル" in text:
        return "operation_doc"

    # Business doc signals
    if re.search(r"(仕様|設計|フロー|業務|申請|支払|承認)", text):
        return "business_doc"

    return "unknown"
