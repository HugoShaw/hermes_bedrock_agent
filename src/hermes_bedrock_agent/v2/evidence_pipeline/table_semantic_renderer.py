"""
テーブルセマンティックレンダラー — テーブル領域の意味的表現を生成するモジュール。

テーブル領域ごとに以下3種の EvidenceRecord を生成する:
- table_region: テーブル全体の意味的要約
- table_header_structure: ヘッダー構造・カラムグループ情報
- raw_table_markdown: 元テーブルの Markdown 保存
"""
from __future__ import annotations

import logging
from typing import Any

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)

_TABLE_TYPE_JP: dict[str, str] = {
    "field_mapping_table": "フィールドマッピングテーブル",
    "api_definition_table": "API定義テーブル",
    "data_dictionary_table": "データディクショナリテーブル",
    "business_rule_table": "業務ルールテーブル",
    "data_condition_table": "データ取得条件テーブル",
    "code_master_table": "コードマスタテーブル",
    "test_case_table": "テストケーステーブル",
    "screen_definition_table": "画面定義テーブル",
    "config_table": "設定テーブル",
    "unknown_table": "不明テーブル",
}


class TableSemanticRenderer:
    """テーブル領域の意味的 EvidenceRecord を生成するクラス。

    render_table_region() で1テーブル領域から3レコードを生成し、
    render_all() で複数領域を一括処理する。
    """

    def __init__(self, dataset: str, run_id: str) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def render_table_region(
        self,
        table_region: dict[str, Any],
        column_roles: dict[str, str],
        table_type: str,
    ) -> list[EvidenceRecord]:
        """テーブル領域から table_region / table_header_structure / raw_table_markdown を生成する。"""
        return [
            self._render_region_summary(table_region, column_roles, table_type),
            self._render_header_structure(table_region, column_roles, table_type),
            self._render_raw_markdown(table_region, table_type),
        ]

    def render_all(
        self,
        table_regions: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
        column_roles_map: dict[str, dict[str, str]],
    ) -> list[EvidenceRecord]:
        """全テーブル領域を処理して EvidenceRecord リストを返す。"""
        records: list[EvidenceRecord] = []
        for region, classification in zip(table_regions, classifications):
            table_type = classification.get("table_type", "unknown_table")
            region_id = region.get("table_region_id", "")
            column_roles = column_roles_map.get(region_id, {})
            try:
                recs = self.render_table_region(region, column_roles, table_type)
                records.extend(recs)
                logger.debug("Rendered %d records for region %s", len(recs), region_id)
            except Exception:
                logger.exception("Failed to render region %s", region_id)
        logger.info(
            "TableSemanticRenderer: generated %d records from %d regions",
            len(records),
            len(table_regions),
        )
        return records

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    def _render_region_summary(
        self,
        region: dict[str, Any],
        column_roles: dict[str, str],
        table_type: str,
    ) -> EvidenceRecord:
        sheet_name = region.get("sheet_name", "")
        columns: list[str] = region.get("columns", [])
        title = region.get("title", "") or sheet_name
        row_count = len(region.get("data_sample", []))
        systems = _extract_systems(region)
        keywords: list[str] = region.get("matched_keywords", [])

        col_str = ", ".join(columns[:10])
        systems_str = ", ".join(systems) if systems else "不明"
        kw_str = ", ".join(keywords) if keywords else ""
        table_type_jp = _TABLE_TYPE_JP.get(table_type, "不明テーブル")

        text_for_embedding = (
            f"[{table_type}] {sheet_name} — {title}. "
            f"Columns: {col_str}. "
            f"Systems: {systems_str}. "
            f"Keywords: {kw_str}"
        ).strip()

        text_for_llm = (
            f"このテーブルは{sheet_name}にある{table_type_jp}です。"
            f"カラムは{col_str}。"
            f"{row_count}行のデータがあります。"
        )

        text_for_display = (
            f"# {title}\n"
            f"シート: {sheet_name} | 種別: {table_type_jp}\n"
            f"カラム ({len(columns)}): {col_str}\n"
            f"行数: {row_count}"
        )

        return EvidenceRecord(
            record_type="table_region",
            dataset=self.dataset,
            run_id=self.run_id,
            source_file=region.get("source_file", ""),
            workbook_name=region.get("workbook_name", ""),
            sheet_name=sheet_name,
            sheet_index=region.get("sheet_index", 0),
            cell_range=region.get("cell_range", ""),
            column_names=columns,
            table_type=table_type,
            table_region_id=region.get("table_region_id", ""),
            column_roles=column_roles,
            text=title,
            text_for_embedding=text_for_embedding,
            text_for_llm=text_for_llm,
            text_for_display=text_for_display,
            keywords=keywords,
            entity_mentions=systems,
            confidence=region.get("confidence", 1.0),
            parser="TableSemanticRenderer",
            metadata={
                "row_count": row_count,
                "col_count": len(columns),
                "title": title,
                "systems": systems,
            },
        )

    def _render_header_structure(
        self,
        region: dict[str, Any],
        column_roles: dict[str, str],
        table_type: str,
    ) -> EvidenceRecord:
        sheet_name = region.get("sheet_name", "")
        columns: list[str] = region.get("columns", [])
        header_rows: list[Any] = region.get("header_rows", [])
        merged_cells: list[dict[str, Any]] = region.get("merged_cells", [])

        groups = _build_groups(merged_cells, columns)
        group_desc = "; ".join(
            f"{grp}: [{', '.join(cols)}]" for grp, cols in groups.items()
        ) or "グループなし"
        role_str = ", ".join(f"{col}={role}" for col, role in column_roles.items())

        text = (
            f"ヘッダー構造: {len(header_rows)}行ヘッダー, "
            f"マージグループ: {group_desc}. "
            f"カラムロール: {role_str}"
        )

        return EvidenceRecord(
            record_type="table_header_structure",
            dataset=self.dataset,
            run_id=self.run_id,
            source_file=region.get("source_file", ""),
            workbook_name=region.get("workbook_name", ""),
            sheet_name=sheet_name,
            sheet_index=region.get("sheet_index", 0),
            cell_range=region.get("cell_range", ""),
            column_names=columns,
            table_type=table_type,
            table_region_id=region.get("table_region_id", ""),
            column_roles=column_roles,
            text=text,
            text_for_embedding=text,
            text_for_llm=text,
            text_for_display=text,
            parser="TableSemanticRenderer",
            confidence=1.0,
            metadata={
                "header_rows": header_rows,
                "merged_cells": merged_cells,
                "groups": groups,
            },
        )

    def _render_raw_markdown(
        self,
        region: dict[str, Any],
        table_type: str,
    ) -> EvidenceRecord:
        sheet_name = region.get("sheet_name", "")
        columns: list[str] = region.get("columns", [])
        data_sample: list[dict[str, Any]] = region.get("data_sample", [])

        md_lines: list[str] = []
        if columns:
            md_lines.append("| " + " | ".join(str(c) for c in columns) + " |")
            md_lines.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in data_sample:
                vals = [str(row.get(col, "")) for col in columns]
                md_lines.append("| " + " | ".join(vals) + " |")

        markdown = "\n".join(md_lines)

        return EvidenceRecord(
            record_type="raw_table_markdown",
            dataset=self.dataset,
            run_id=self.run_id,
            source_file=region.get("source_file", ""),
            workbook_name=region.get("workbook_name", ""),
            sheet_name=sheet_name,
            sheet_index=region.get("sheet_index", 0),
            cell_range=region.get("cell_range", ""),
            column_names=columns,
            table_type=table_type,
            table_region_id=region.get("table_region_id", ""),
            text=markdown,
            text_for_embedding="",
            text_for_llm=markdown,
            text_for_display=markdown,
            parser="TableSemanticRenderer",
            confidence=1.0,
        )


# ------------------------------------------------------------------
# module-level helpers
# ------------------------------------------------------------------

def _extract_systems(region: dict[str, Any]) -> list[str]:
    """マージセルのグループラベルからシステム名候補を抽出する。"""
    systems: list[str] = []
    for mc in region.get("merged_cells", []):
        val = str(mc.get("value", "")).strip()
        if val:
            systems.append(val)
    return list(dict.fromkeys(systems))


def _build_groups(
    merged_cells: list[dict[str, Any]],
    columns: list[str],
) -> dict[str, list[str]]:
    """マージセル情報からグループラベル → カラムリストのマップを構築する。"""
    groups: dict[str, list[str]] = {}
    for mc in merged_cells:
        label = str(mc.get("value", "")).strip()
        if not label:
            continue
        min_col = mc.get("min_col", 1) - 1
        max_col = mc.get("max_col", min_col + 1) - 1
        grp_cols = [
            columns[i]
            for i in range(min_col, max_col + 1)
            if 0 <= i < len(columns)
        ]
        if grp_cols:
            groups.setdefault(label, []).extend(grp_cols)
    return groups
