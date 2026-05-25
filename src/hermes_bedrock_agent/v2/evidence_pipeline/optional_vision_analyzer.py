"""
Optional VLM analyzer — Bedrock Claude Sonnet を使って画像を解析する (オプション)。

有効化条件:
  - BEDROCK_VLM_MODEL_ID (または VISION_LLM_MODEL_ID) が設定されている
  - 解析対象画像が選定基準を満たす

選定基準:
  - シート名に対象キーワードを含む (高優先)
  - ファイルサイズ >= 50KB (常に解析)
  - ファイルサイズ 10KB-50KB (中優先、コネクタ有り/ビジュアルコンテキストで選択)
  - ファイルサイズ < 5KB (アイコン扱い、スキップ)

出力:
  - visual_analysis_records.jsonl
  - reports/vlm_image_selection_report.md
  - bedrock_vlm_raw_responses.jsonl
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# デフォルトの VLM プロンプト
_DEFAULT_PROMPT = (
    "この画像はビジネス文書 (Excel シート) から抽出されたものです。\n"
    "以下の点を日本語で詳しく説明してください：\n\n"
    "1. 図の種類 (フローチャート、API呼出フロー、ネットワーク図、組織図、表、シーケンス図、その他)\n"
    "2. 可視テキスト: 画像内に読み取れるすべてのテキスト（システム名、API名、操作名など）\n"
    "3. システム名称: 識別できるシステム・サービス名 (ANDPAD, SAP, DataSpider, 中間F等)\n"
    "4. API・操作: API名、HTTPメソッド、エンドポイント、操作内容\n"
    "5. フロー・処理順序: 矢印や番号で示される処理の流れ（登録→変更→取消 等）\n"
    "6. 接続関係: 矢印・コネクタで示されるシステム間・ステップ間の関係\n"
    "7. 業務オブジェクト: 発注、注文、取消、再発注などの業務概念\n"
    "8. フィールド・テーブル: データ項目やテーブル名が見える場合\n"
    "9. 業務ルール: 条件分岐、バリデーション、制約\n"
    "10. グラフ候補関係: ノード→エッジ→ノードの形式で関係を列挙\n"
    "11. 人工審核注意点: 解析が不確実な部分、確認が必要な箇所\n\n"
    "回答は構造化された箇条書きで、できるだけ詳しく記述してください。"
)

# シート選定キーワード
_TARGET_SHEET_KEYWORDS = (
    "概要", "フローチャート", "フロー", "flow", "overview",
    "API呼出順序", "API", "REST", "ANDPAD", "DataSpider", "SAP",
    "発注", "取消", "登録", "変更", "architecture", "diagram",
)


class OptionalVisionAnalyzer:
    """Bedrock Claude Sonnet VLM による画像解析 (オプション機能)。

    Parameters
    ----------
    model_id:
        Bedrock の VLM モデル ID。
        None の場合は環境変数 BEDROCK_VLM_MODEL_ID / VISION_LLM_MODEL_ID を参照。
    region:
        AWS リージョン。
    dataset, run_id:
        パイプライン識別子。
    prompt:
        VLM に渡すプロンプト。None の場合はデフォルトを使用。
    max_images:
        1回のパイプライン実行で解析する最大画像数 (コスト制御)。
    """

    def __init__(
        self,
        model_id: str | None = None,
        region: str = "ap-northeast-1",
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_evidence_v1",
        prompt: str | None = None,
        max_images: int = 20,
    ) -> None:
        self.model_id = model_id or os.environ.get("BEDROCK_VLM_MODEL_ID") or os.environ.get("VISION_LLM_MODEL_ID", "")
        self.region = region
        self.dataset = dataset
        self.run_id = run_id
        self.prompt = prompt or _DEFAULT_PROMPT
        self.max_images = max_images
        self._client: Any = None
        self._selection_log: list[dict[str, Any]] = []
        self._raw_responses: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return bool(self.model_id)

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client("bedrock-runtime", region_name=self.region)
            except Exception as exc:
                logger.error("Failed to create Bedrock client: %s", exc)
                raise
        return self._client

    def select_images(
        self,
        image_records: list[dict[str, Any]],
        prescan_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """解析対象画像を選定基準に従って絞り込む。"""
        if not self.enabled:
            logger.debug("VLM analysis disabled (no model_id configured)")
            return []

        prescan_by_sheet: dict[str, dict[str, Any]] = {r["sheet_name"]: r for r in prescan_records}
        selected: list[dict[str, Any]] = []
        self._selection_log = []

        for rec in image_records:
            sheet_name = rec.get("anchor_sheet", "")
            local_path = rec.get("local_path", "")
            prescan = prescan_by_sheet.get(sheet_name, {})

            try:
                file_size = Path(local_path).stat().st_size if local_path else 0
            except (OSError, FileNotFoundError):
                file_size = 0

            reason = None
            priority = "low"

            # Rule 1: Sheet name matches target keywords
            if _is_target_sheet(sheet_name):
                reason = f"sheet_name_match: {sheet_name}"
                priority = "high"

            # Rule 2: Large image (>= 50KB) - always analyze
            elif file_size >= 50_000:
                reason = f"large_image: {file_size} bytes"
                priority = "high"

            # Rule 3: Medium image (10KB-50KB) with visual context
            elif file_size >= 10_000:
                if prescan.get("has_connectors") or prescan.get("has_images"):
                    reason = f"medium_image_visual_context: {file_size} bytes, connectors={prescan.get('has_connectors')}"
                    priority = "medium"
                else:
                    reason = f"medium_image_no_visual_context: {file_size} bytes"
                    priority = "medium"  # Still include medium images

            # Rule 4: Small image (< 5KB) - likely icon, skip
            elif file_size < 5_000:
                reason = f"small_icon_skipped: {file_size} bytes"
                priority = "skip"

            # Rule 5: Sheet has connectors
            elif prescan.get("has_connectors"):
                reason = f"sheet_has_connectors: connector_count={prescan.get('connector_count', 0)}"
                priority = "medium"

            # Default: include if not tiny
            else:
                reason = f"default_include: {file_size} bytes"
                priority = "medium"

            log_entry = {
                "image_path": local_path,
                "workbook_name": rec.get("workbook_name", ""),
                "sheet_name": sheet_name,
                "file_size": file_size,
                "priority": priority,
                "selected": priority != "skip",
                "reason": reason,
            }
            self._selection_log.append(log_entry)

            if priority != "skip":
                selected.append(rec)

        result = selected[: self.max_images]
        logger.info(
            "Selected %d/%d images for VLM analysis (skipped %d small icons)",
            len(result),
            len(image_records),
            len(image_records) - len(selected),
        )
        return result

    def analyze(
        self,
        image_records: list[dict[str, Any]],
        prescan_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """選定した画像を VLM で解析し、解析レコードを返す。"""
        if not self.enabled:
            logger.info("VLM analysis skipped (disabled)")
            return []

        targets = self.select_images(image_records, prescan_records)
        if not targets:
            return []

        results: list[dict[str, Any]] = []
        for rec in targets:
            analysis = self._analyze_one(rec)
            if analysis:
                results.append(analysis)

        logger.info("VLM analysis complete: %d records", len(results))
        return results

    def _analyze_one(self, image_rec: dict[str, Any]) -> dict[str, Any] | None:
        """1枚の画像を VLM で解析する。エラー時は None を返す。"""
        local_path = image_rec.get("local_path", "")
        if not local_path or not Path(local_path).exists():
            logger.warning("Image not found: %s", local_path)
            return None

        img_path = Path(local_path)
        fmt = image_rec.get("format", "png").lower()
        mime_type = _mime_type(fmt)

        try:
            img_bytes = img_path.read_bytes()
        except OSError as exc:
            logger.error("Failed to read image %s: %s", local_path, exc)
            return None

        b64_data = base64.standard_b64encode(img_bytes).decode("ascii")

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_data,
                            },
                        },
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ],
        }

        try:
            client = self._get_client()
            response = client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            response_body = json.loads(response["body"].read())
            analysis_text = _extract_text_from_response(response_body)
        except Exception as exc:
            logger.error("VLM analysis failed for %s: %s", local_path, exc)
            return None

        self._raw_responses.append({
            "image_id": image_rec.get("image_id", ""),
            "local_path": local_path,
            "model_id": self.model_id,
            "response_body": response_body,
            "analysis_text": analysis_text,
        })

        return {
            "image_id": image_rec.get("image_id", ""),
            "local_path": local_path,
            "media_zip_path": image_rec.get("media_zip_path", ""),
            "workbook_name": image_rec.get("workbook_name", ""),
            "anchor_sheet": image_rec.get("anchor_sheet", ""),
            "anchor_sheet_index": image_rec.get("anchor_sheet_index"),
            "analysis_text": analysis_text,
            "model_id": self.model_id,
            "prompt": self.prompt,
            "dataset": self.dataset,
            "run_id": self.run_id,
            "source_file": image_rec.get("source_file", ""),
            "source_s3_uri": image_rec.get("source_s3_uri", ""),
        }

    def write_jsonl(self, records: list[dict[str, Any]], output_dir: str) -> str:
        """解析レコードを visual_analysis_records.jsonl に書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = str(out / "visual_analysis_records.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote %d VLM analysis records → %s", len(records), path)
        return path

    def write_selection_report(self, output_dir: str) -> str:
        """Write VLM image selection report."""
        out = Path(output_dir) / "reports"
        out.mkdir(parents=True, exist_ok=True)
        path = str(out / "vlm_image_selection_report.md")

        with open(path, "w", encoding="utf-8") as f:
            f.write("# VLM Image Selection Report\n\n")
            f.write(f"Total images: {len(self._selection_log)}\n")
            selected = [x for x in self._selection_log if x["selected"]]
            skipped = [x for x in self._selection_log if not x["selected"]]
            f.write(f"Selected: {len(selected)}\n")
            f.write(f"Skipped: {len(skipped)}\n\n")

            f.write("## Selected Images\n\n")
            for entry in selected:
                f.write(f"### {Path(entry['image_path']).name}\n")
                f.write(f"- Workbook: {entry['workbook_name']}\n")
                f.write(f"- Sheet: {entry['sheet_name']}\n")
                f.write(f"- Size: {entry['file_size']:,} bytes\n")
                f.write(f"- Priority: {entry['priority']}\n")
                f.write(f"- Reason: {entry['reason']}\n\n")

            if skipped:
                f.write("## Skipped Images\n\n")
                for entry in skipped:
                    f.write(f"### {Path(entry['image_path']).name}\n")
                    f.write(f"- Sheet: {entry['sheet_name']}\n")
                    f.write(f"- Size: {entry['file_size']:,} bytes\n")
                    f.write(f"- Reason: {entry['reason']}\n\n")

        logger.info("Wrote VLM selection report → %s", path)
        return path

    def write_raw_responses(self, output_dir: str) -> str:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = str(out / "bedrock_vlm_raw_responses.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for rec in self._raw_responses:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote %d raw VLM responses → %s", len(self._raw_responses), path)
        return path


# ---- helpers ----------------------------------------------------------

def _is_target_sheet(sheet_name: str) -> bool:
    name_lower = sheet_name.lower()
    return any(kw.lower() in name_lower for kw in _TARGET_SHEET_KEYWORDS)


def _mime_type(fmt: str) -> str:
    _MAP = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
        "svg": "image/svg+xml",
        "webp": "image/webp",
    }
    return _MAP.get(fmt.lower(), "image/png")


def _extract_text_from_response(body: dict[str, Any]) -> str:
    """Bedrock レスポンスボディからテキストを抽出する。"""
    # Claude Messages API 形式
    content = body.get("content", [])
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(parts).strip()
    # フォールバック
    return str(body.get("completion", body.get("text", "")))
