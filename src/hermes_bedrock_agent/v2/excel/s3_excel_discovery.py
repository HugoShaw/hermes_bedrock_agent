"""
S3 Excel discovery — list and classify Excel files under an S3 prefix.

Discovers all Excel-compatible files (.xlsx, .xlsm, .xls) and also
lists non-Excel files for awareness. Outputs a file manifest (JSONL)
and a discovery report (Markdown).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}
ALL_SUPPORTED_EXTENSIONS = {
    ".xlsx", ".xlsm", ".xls", ".csv", ".txt", ".md", ".pdf", ".docx",
}


class S3ExcelDiscovery:
    """Discover Excel and other files under an S3 prefix.

    Parameters
    ----------
    bucket : str
        S3 bucket name.
    prefix : str
        S3 key prefix (e.g. 'サンプル20260519/').
    region : str
        AWS region.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        region: str = "ap-northeast-1",
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self._s3 = boto3.client("s3", region_name=region)

    def discover(self) -> dict[str, Any]:
        """List all objects under the prefix recursively.

        Returns
        -------
        dict with keys:
            - all_files: list of dicts {key, size, extension, is_excel, last_modified}
            - excel_files: filtered list of excel-only entries
            - non_excel_files: filtered list of non-excel entries
            - total_count: int
            - excel_count: int
            - error: str or None
        """
        all_files: list[dict[str, Any]] = []
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=self.prefix)
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue
                    ext = Path(key).suffix.lower()
                    entry = {
                        "key": key,
                        "size": obj["Size"],
                        "extension": ext,
                        "is_excel": ext in EXCEL_EXTENSIONS,
                        "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                        "file_name": Path(key).name,
                    }
                    all_files.append(entry)
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 discovery failed: %s", exc)
            return {
                "all_files": [],
                "excel_files": [],
                "non_excel_files": [],
                "total_count": 0,
                "excel_count": 0,
                "error": str(exc),
            }

        excel_files = [f for f in all_files if f["is_excel"]]
        non_excel_files = [f for f in all_files if not f["is_excel"]]

        logger.info(
            "S3 discovery: %d total files, %d Excel, %d non-Excel under s3://%s/%s",
            len(all_files), len(excel_files), len(non_excel_files),
            self.bucket, self.prefix,
        )

        return {
            "all_files": all_files,
            "excel_files": excel_files,
            "non_excel_files": non_excel_files,
            "total_count": len(all_files),
            "excel_count": len(excel_files),
            "error": None,
        }

    def write_manifest(self, output_path: str, discovery: dict[str, Any]) -> None:
        """Write file manifest as JSONL."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for entry in discovery["all_files"]:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote %d entries to %s", len(discovery["all_files"]), output_path)

    def write_report(self, output_path: str, discovery: dict[str, Any]) -> None:
        """Write discovery report as Markdown."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# S3 Discovery Report",
            "",
            f"**S3 URI:** s3://{self.bucket}/{self.prefix}",
            f"**Total files:** {discovery['total_count']}",
            f"**Excel files:** {discovery['excel_count']}",
            f"**Non-Excel files:** {len(discovery['non_excel_files'])}",
            "",
        ]

        if discovery.get("error"):
            lines.extend([
                "## Error",
                "",
                f"```\n{discovery['error']}\n```",
                "",
            ])

        if discovery["excel_files"]:
            lines.extend([
                "## Excel Files",
                "",
                "| # | File Name | Extension | Size (KB) | Path |",
                "|---|-----------|-----------|-----------|------|",
            ])
            for i, f in enumerate(discovery["excel_files"], 1):
                size_kb = f["size"] / 1024
                lines.append(f"| {i} | {f['file_name']} | {f['extension']} | {size_kb:.1f} | {f['key']} |")
            lines.append("")

        if discovery["non_excel_files"]:
            lines.extend([
                "## Non-Excel Files",
                "",
                "| # | File Name | Extension | Size (KB) | Path |",
                "|---|-----------|-----------|-----------|------|",
            ])
            for i, f in enumerate(discovery["non_excel_files"], 1):
                size_kb = f["size"] / 1024
                lines.append(f"| {i} | {f['file_name']} | {f['extension']} | {size_kb:.1f} | {f['key']} |")
            lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("Wrote discovery report to %s", output_path)

    def download_file(self, key: str, local_path: str) -> str:
        """Download a single S3 object to a local path.

        Returns the local_path on success.
        """
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(self.bucket, key, local_path)
        logger.info("Downloaded s3://%s/%s -> %s", self.bucket, key, local_path)
        return local_path
