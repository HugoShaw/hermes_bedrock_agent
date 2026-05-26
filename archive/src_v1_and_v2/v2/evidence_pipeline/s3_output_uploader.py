"""
S3 output uploader — ローカル出力ディレクトリを S3 にアップロードする。

`aws s3 sync` を subprocess 経由で呼び出す。

出力:
  - reports/s3_upload_report.md … アップロード結果レポート
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class S3OutputUploader:
    """ローカル出力ディレクトリを S3 にアップロードするクラス。

    Parameters
    ----------
    bucket:
        S3 バケット名。
    target_prefix:
        アップロード先 S3 プレフィックス (例: outputs/sample_20260519_evidence_v1)。
    latest_prefix:
        latest エイリアスプレフィックス (例: outputs/latest)。None の場合は使用しない。
    region:
        AWS リージョン。
    dry_run:
        True の場合、実際のアップロードを行わず内容を表示するだけ (--dryrun)。
    dataset, run_id:
        パイプライン識別子。
    """

    def __init__(
        self,
        bucket: str,
        target_prefix: str,
        latest_prefix: str | None = None,
        region: str = "ap-northeast-1",
        dry_run: bool = False,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_evidence_v1",
    ) -> None:
        self.bucket = bucket
        self.target_prefix = target_prefix.strip("/")
        self.latest_prefix = latest_prefix.strip("/") if latest_prefix else None
        self.region = region
        self.dry_run = dry_run
        self.dataset = dataset
        self.run_id = run_id

    def upload(self, local_dir: str) -> dict[str, Any]:
        """ローカルディレクトリを S3 にアップロードする。

        Parameters
        ----------
        local_dir:
            アップロード元ローカルディレクトリ。

        Returns
        -------
        dict with keys: success, target_uri, latest_uri, stdout, stderr, error
        """
        local_path = Path(local_dir)
        if not local_path.exists():
            error_msg = f"Local directory not found: {local_dir}"
            logger.error(error_msg)
            return _make_result(success=False, error=error_msg)

        target_uri = f"s3://{self.bucket}/{self.target_prefix}/"
        result = _make_result(success=True, target_uri=target_uri)

        # メインアップロード
        sync_result = self._run_sync(str(local_path), target_uri)
        result["stdout"] = sync_result["stdout"]
        result["stderr"] = sync_result["stderr"]

        if sync_result["returncode"] != 0:
            result["success"] = False
            result["error"] = f"aws s3 sync failed (rc={sync_result['returncode']}): {sync_result['stderr'][:500]}"
            logger.error("S3 upload failed: %s", result["error"])
            return result

        logger.info("Uploaded %s → %s", local_dir, target_uri)

        # latest プレフィックスへも同期
        if self.latest_prefix:
            latest_uri = f"s3://{self.bucket}/{self.latest_prefix}/"
            result["latest_uri"] = latest_uri
            latest_result = self._run_sync(str(local_path), latest_uri)
            if latest_result["returncode"] != 0:
                logger.warning(
                    "latest sync failed (non-fatal): %s",
                    latest_result["stderr"][:200],
                )
                result["latest_sync_error"] = latest_result["stderr"][:200]
            else:
                logger.info("Also synced to latest: %s", latest_uri)

        return result

    def _run_sync(self, local_dir: str, s3_uri: str) -> dict[str, Any]:
        """aws s3 sync を実行して結果を返す。"""
        cmd = [
            "aws", "s3", "sync",
            local_dir,
            s3_uri,
            "--region", self.region,
            "--no-progress",
        ]
        if self.dry_run:
            cmd.append("--dryrun")

        logger.debug("Running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "Command timed out after 300s"}
        except FileNotFoundError:
            return {"returncode": -1, "stdout": "", "stderr": "aws CLI not found. Install awscli."}
        except Exception as exc:
            return {"returncode": -1, "stdout": "", "stderr": str(exc)}

    def write_report(self, upload_result: dict[str, Any], output_dir: str) -> str:
        """アップロード結果を Markdown レポートに書き出す。

        Returns
        -------
        レポートファイルのパス。
        """
        reports_dir = Path(output_dir) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = str(reports_dir / "s3_upload_report.md")

        now = datetime.now(timezone.utc).isoformat()
        success = upload_result.get("success", False)
        status_icon = "✓" if success else "✗"
        status_text = "SUCCESS" if success else "FAILED"

        lines: list[str] = [
            "# S3 Upload Report",
            "",
            f"**Status:** {status_icon} {status_text}  ",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}",
            "",
            "## Upload Details",
            "",
            f"- **Target URI:** {upload_result.get('target_uri', 'N/A')}",
            f"- **Latest URI:** {upload_result.get('latest_uri', 'N/A')}",
            f"- **Dry run:** {self.dry_run}",
            f"- **Region:** {self.region}",
            "",
        ]

        if upload_result.get("error"):
            lines += [
                "## Error",
                "",
                "```",
                upload_result["error"],
                "```",
                "",
            ]

        if upload_result.get("latest_sync_error"):
            lines += [
                "## Latest Sync Warning",
                "",
                f"*{upload_result['latest_sync_error']}*",
                "",
            ]

        stdout = upload_result.get("stdout", "").strip()
        if stdout:
            lines += [
                "## Output",
                "",
                "```",
                stdout[:3000],
                "```" if len(stdout) <= 3000 else "```\n*(truncated)*",
                "",
            ]

        stderr = upload_result.get("stderr", "").strip()
        if stderr and not success:
            lines += [
                "## stderr",
                "",
                "```",
                stderr[:1000],
                "```",
                "",
            ]

        content = "\n".join(lines)
        Path(report_path).write_text(content, encoding="utf-8")
        logger.info("Wrote upload report → %s", report_path)
        return report_path


# ---- helpers ----------------------------------------------------------

def _make_result(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "success": False,
        "target_uri": "",
        "latest_uri": "",
        "stdout": "",
        "stderr": "",
        "error": None,
    }
    defaults.update(kwargs)
    return defaults
