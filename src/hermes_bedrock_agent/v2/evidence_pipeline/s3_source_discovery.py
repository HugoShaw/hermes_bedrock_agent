"""
S3 source discovery — S3プレフィックス配下の全ファイルを再帰的にリストし分類する。

出力:
  - s3_file_manifest.jsonl  … 全ファイルのメタデータ
  - reports/s3_discovery_report.md … Markdown形式の一覧表
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# 拡張子ごとの分類
EXCEL_EXTENSIONS = frozenset({".xlsx", ".xlsm", ".xls"})
MERMAID_EXTENSIONS = frozenset({".mmd", ".mermaid"})
DOCUMENT_EXTENSIONS = frozenset({".csv", ".txt", ".md", ".pdf", ".docx", ".pptx"})
ALL_KNOWN_EXTENSIONS = EXCEL_EXTENSIONS | MERMAID_EXTENSIONS | DOCUMENT_EXTENSIONS


def _classify(ext: str) -> str:
    if ext in EXCEL_EXTENSIONS:
        return "excel"
    if ext in MERMAID_EXTENSIONS:
        return "mermaid"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "other"


class S3SourceDiscovery:
    """Discover and download source files from S3.

    Parameters
    ----------
    bucket:
        S3バケット名。
    prefix:
        S3キープレフィックス (例: 'サンプル20260519/')。
    region:
        AWSリージョン。
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        region: str = "ap-northeast-1",
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.region = region
        self._s3 = boto3.client("s3", region_name=region)

    def discover(self) -> dict[str, Any]:
        """S3プレフィックス配下を再帰的にリストし、ファイル種別を分類する。

        Returns
        -------
        dict with keys:
            all_files, excel_files, mermaid_files, other_files,
            total_count, excel_count, mermaid_count, error
        """
        all_files: list[dict[str, Any]] = []
        error: str | None = None

        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=self.prefix)
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue
                    ext = Path(key).suffix.lower()
                    entry: dict[str, Any] = {
                        "key": key,
                        "s3_uri": f"s3://{self.bucket}/{key}",
                        "file_name": Path(key).name,
                        "extension": ext,
                        "file_class": _classify(ext),
                        "size_bytes": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                    }
                    all_files.append(entry)
        except (ClientError, BotoCoreError) as exc:
            error = str(exc)
            logger.error("S3 discovery failed for s3://%s/%s: %s", self.bucket, self.prefix, exc)

        excel_files = [f for f in all_files if f["file_class"] == "excel"]
        mermaid_files = [f for f in all_files if f["file_class"] == "mermaid"]
        other_files = [f for f in all_files if f["file_class"] not in ("excel", "mermaid")]

        logger.info(
            "S3 discovery: %d total (%d excel, %d mermaid, %d other) under s3://%s/%s",
            len(all_files), len(excel_files), len(mermaid_files), len(other_files),
            self.bucket, self.prefix,
        )

        return {
            "all_files": all_files,
            "excel_files": excel_files,
            "mermaid_files": mermaid_files,
            "other_files": other_files,
            "total_count": len(all_files),
            "excel_count": len(excel_files),
            "mermaid_count": len(mermaid_files),
            "error": error,
        }

    def write_manifest(self, output_path: str, discovery: dict[str, Any]) -> None:
        """全ファイルのマニフェストをJSONL形式で出力する。"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            for entry in discovery["all_files"]:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote manifest: %d entries → %s", len(discovery["all_files"]), output_path)

    def write_report(self, output_path: str, discovery: dict[str, Any]) -> None:
        """S3探索レポートをMarkdown形式で出力する。"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# S3 Source Discovery Report",
            "",
            f"**S3 URI:** s3://{self.bucket}/{self.prefix}",
            f"**Total files:** {discovery['total_count']}",
            f"**Excel files:** {discovery['excel_count']}",
            f"**Mermaid files:** {discovery['mermaid_count']}",
            f"**Other files:** {len(discovery['other_files'])}",
            "",
        ]
        if discovery.get("error"):
            lines += ["## Error", "", f"```\n{discovery['error']}\n```", ""]

        def _table(title: str, files: list[dict[str, Any]]) -> list[str]:
            if not files:
                return []
            rows = [
                f"## {title}",
                "",
                "| # | File | Ext | Size (KB) | S3 Key |",
                "|---|------|-----|-----------|--------|",
            ]
            for i, f in enumerate(files, 1):
                kb = f["size_bytes"] / 1024
                rows.append(f"| {i} | {f['file_name']} | {f['extension']} | {kb:.1f} | {f['key']} |")
            rows.append("")
            return rows

        lines += _table("Excel Files", discovery["excel_files"])
        lines += _table("Mermaid Files", discovery["mermaid_files"])
        lines += _table("Other Files", discovery["other_files"])

        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        logger.info("Wrote discovery report → %s", output_path)

    def download_file(self, s3_key: str, local_path: str) -> str:
        """S3オブジェクトをローカルパスにダウンロードする。

        Returns the local_path on success.
        """
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(self.bucket, s3_key, local_path)
        logger.debug("Downloaded s3://%s/%s → %s", self.bucket, s3_key, local_path)
        return local_path

    def download_all(
        self,
        discovery: dict[str, Any],
        local_dir: str,
        file_classes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """マニフェスト内の全ファイル(または指定クラスのみ)をダウンロードする。

        Parameters
        ----------
        discovery:
            discover() の返却値。
        local_dir:
            ダウンロード先ディレクトリ。
        file_classes:
            対象クラスのリスト (例: ["excel", "mermaid"])。None の場合は全件。

        Returns
        -------
        各エントリに ``local_path`` キーを追加したリスト。
        """
        results: list[dict[str, Any]] = []
        for entry in discovery["all_files"]:
            if file_classes is not None and entry["file_class"] not in file_classes:
                continue
            # S3キーのディレクトリ構造をローカルに再現
            rel_key = entry["key"]
            if self.prefix and rel_key.startswith(self.prefix):
                rel_key = rel_key[len(self.prefix):]
            local_path = os.path.join(local_dir, rel_key)
            try:
                self.download_file(entry["key"], local_path)
                entry = dict(entry)
                entry["local_path"] = local_path
                entry["download_error"] = None
            except (ClientError, BotoCoreError, OSError) as exc:
                logger.warning("Failed to download %s: %s", entry["key"], exc)
                entry = dict(entry)
                entry["local_path"] = None
                entry["download_error"] = str(exc)
            results.append(entry)
        return results
