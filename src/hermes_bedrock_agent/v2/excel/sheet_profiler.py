"""
Sheet profiler — analyze sheet content and infer sheet types.

Profiles each sheet by:
- Counting rows, columns, non-empty cells
- Detecting merged cells, formulas, comments
- Sampling non-empty cells for content analysis
- Inferring sheet type from sheet name and content keywords
"""
from __future__ import annotations

import logging
import re
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_schema import (
    ExcelSheetRecord,
    ExcelCellEvidence,
    ALLOWED_SHEET_TYPES,
)

logger = logging.getLogger(__name__)

# Sheet type inference keywords
SHEET_TYPE_KEYWORDS: dict[str, list[str]] = {
    "field_mapping_sheet": [
        "マッピング", "項目", "mapping", "field", "フィールド", "対応表",
        "映射", "字段", "カラム", "column", "テーブル", "table",
    ],
    "api_interface_sheet": [
        "API", "IF", "インターフェース", "interface", "接口",
        "endpoint", "リクエスト", "レスポンス", "request", "response",
    ],
    "data_dictionary_sheet": [
        "データ辞書", "data dictionary", "DB", "テーブル定義", "table definition",
        "データベース", "database", "カラム定義", "数据库", "数据字典",
    ],
    "business_process_sheet": [
        "業務", "処理", "フロー", "申請", "承認", "支払", "仕訳",
        "process", "flow", "业务", "流程", "申请", "审批", "付款",
    ],
    "code_master_sheet": [
        "コード", "マスタ", "code", "master", "区分", "種別",
        "错误码", "エラーコード", "error", "message",
    ],
    "business_rule_sheet": [
        "ルール", "rule", "条件", "判定", "バリデーション",
        "validation", "check", "规则", "条件",
    ],
    "test_case_sheet": [
        "テスト", "test", "ケース", "case", "テストケース",
        "测试", "用例", "expected", "actual",
    ],
    "screen_definition_sheet": [
        "画面", "screen", "UI", "レイアウト", "layout",
        "入力", "表示", "画面定義", "界面",
    ],
    "system_config_sheet": [
        "設定", "config", "パラメータ", "parameter", "環境",
        "environment", "配置", "设定",
    ],
    "operation_sheet": [
        "操作", "手順", "operation", "procedure", "運用",
        "manual", "手册", "操作手順",
    ],
}


class SheetProfiler:
    """Profile Excel sheets and infer their types.

    Parameters
    ----------
    sample_cells : int
        Maximum number of non-empty cells to sample for type inference.
    max_cell_text_length : int
        Maximum text length per cell to keep in samples.
    """

    def __init__(
        self,
        sample_cells: int = 200,
        max_cell_text_length: int = 500,
    ) -> None:
        self.sample_cells = sample_cells
        self.max_cell_text_length = max_cell_text_length

    def profile_sheet(
        self,
        ws: Any,
        sheet_record: ExcelSheetRecord,
        workbook_id: str,
    ) -> tuple[ExcelSheetRecord, list[ExcelCellEvidence]]:
        """Profile a single worksheet and return updated record + cell samples.

        Parameters
        ----------
        ws : openpyxl Worksheet
            The worksheet object.
        sheet_record : ExcelSheetRecord
            Pre-populated sheet record (from WorkbookLoader).
        workbook_id : str
            Parent workbook ID.

        Returns
        -------
        Tuple of (updated ExcelSheetRecord, list of sampled ExcelCellEvidence)
        """
        cell_samples: list[ExcelCellEvidence] = []
        sampled_texts: list[str] = []
        sample_count = 0

        max_row = ws.max_row or 0
        max_col = ws.max_column or 0

        # Sample non-empty cells
        for row in ws.iter_rows(min_row=1, max_row=min(max_row, 500), max_col=min(max_col, 100)):
            for cell in row:
                if cell.value is None:
                    continue
                if sample_count >= self.sample_cells:
                    break

                cell_ref = cell.coordinate
                value_str = str(cell.value)[:self.max_cell_text_length] if cell.value else None
                formula_str = None
                comment_str = None
                merged_parent = None

                # Check for formula
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_str = cell.value[:self.max_cell_text_length]
                    value_str = formula_str

                # Check for comment
                if cell.comment:
                    comment_str = str(cell.comment.text)[:self.max_cell_text_length]

                # Record for sampling
                cell_ev = ExcelCellEvidence(
                    cell_id=ExcelCellEvidence.generate_id(sheet_record.sheet_id, cell_ref),
                    workbook_id=workbook_id,
                    sheet_id=sheet_record.sheet_id,
                    sheet_name=sheet_record.sheet_name,
                    cell_ref=cell_ref,
                    value=value_str,
                    formula=formula_str,
                    comment=comment_str,
                    merged_parent=merged_parent,
                    style_hint={},
                    metadata={},
                )
                cell_samples.append(cell_ev)
                if value_str:
                    sampled_texts.append(value_str)
                sample_count += 1

            if sample_count >= self.sample_cells:
                break

        # Infer sheet type
        sheet_type, confidence = self._infer_sheet_type(
            sheet_record.sheet_name,
            sampled_texts,
        )

        # Update record
        sheet_record.guessed_sheet_type = sheet_type
        sheet_record.confidence = confidence
        sheet_record.metadata["sampled_cell_count"] = len(cell_samples)

        return sheet_record, cell_samples

    def _infer_sheet_type(
        self,
        sheet_name: str,
        sampled_texts: list[str],
    ) -> tuple[str, float]:
        """Infer sheet type from sheet name and sampled text content.

        Returns (sheet_type, confidence).
        """
        # Combine sheet name and sample text for keyword matching
        combined_text = sheet_name + " " + " ".join(sampled_texts[:50])
        combined_lower = combined_text.lower()

        scores: dict[str, float] = {}
        for stype, keywords in SHEET_TYPE_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                kw_lower = kw.lower()
                # Sheet name match is worth more
                if kw_lower in sheet_name.lower():
                    score += 3.0
                # Content match
                if kw_lower in combined_lower:
                    score += 1.0
            if score > 0:
                scores[stype] = score

        if not scores:
            return "unknown_sheet", 0.0

        best_type = max(scores, key=scores.get)  # type: ignore
        best_score = scores[best_type]

        # Normalize confidence (heuristic)
        confidence = min(best_score / 10.0, 1.0)

        return best_type, round(confidence, 2)
