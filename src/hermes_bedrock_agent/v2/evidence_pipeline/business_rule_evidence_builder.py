"""
業務ルール証拠ビルダー — business_rule_table / data_condition_table 行から
business_rule EvidenceRecord と sheet_summary レコードを生成するモジュール。

出力 record_type:
  - business_rule   … 条件・アクション・対象が識別できた行
  - sheet_summary   … シートごとの目的・テーブル種別・システム名・ビジュアル概要
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Optional

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)

_APPLICABLE_TYPES = frozenset({"business_rule_table", "data_condition_table"})

# 条件テキストが存在するかを示すロール
_CONDITION_ROLES = frozenset({"condition", "mapping_rule", "description", "remarks"})
# アクション/対象が入るロール
_ACTION_ROLES = frozenset({"mapping_rule", "target_field", "item_name"})
_TARGET_ROLES = frozenset({"target_system", "target_field", "item_name"})
_BUSINESS_OBJ_ROLES = frozenset({"source_system", "target_system", "api_name"})

_SYSTEM_PATTERN = re.compile(
    r"(SAP|ANDPAD|DataSpider|中間F|Oracle|Salesforce|MySQL|PostgreSQL|[A-Z]{2,}システム)",
    re.IGNORECASE,
)


class BusinessRuleEvidenceBuilder:
    """業務ルール EvidenceRecord と sheet_summary を生成するクラス。

    build_from_row()    — 1行から Optional[EvidenceRecord] (business_rule)
    build_all()         — 全行を一括処理
    build_sheet_summaries() — シートごとの sheet_summary レコードを生成
    """

    def __init__(self, dataset: str, run_id: str) -> None:
        self.dataset = dataset
        self.run_id = run_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_from_row(
        self,
        row_data: dict[str, Any],
        table_type: str,
        column_roles: dict[str, str],
    ) -> Optional[EvidenceRecord]:
        """1行から business_rule レコードを生成する。対象外行は None を返す。"""
        if table_type not in _APPLICABLE_TYPES:
            return None

        rv = _extract_role_values(row_data.get("values", {}), column_roles)

        condition = _pick_first(rv, _CONDITION_ROLES)
        if not condition:
            return None

        action = _pick_first(rv, _ACTION_ROLES)
        target = _pick_first(rv, _TARGET_ROLES)
        business_object = _pick_first(rv, _BUSINESS_OBJ_ROLES)
        keywords = _extract_keywords(row_data)
        systems = _extract_systems(row_data)

        text_for_llm = (
            f"業務ルール: {condition}の場合、"
            f"{action or '(アクション不明)'}を実行する。"
            f"対象: {target or '(対象不明)'}. "
            f"適用: {business_object or '(対象システム不明)'}"
        )
        text_for_embedding = (
            f"business rule 業務ルール {condition} "
            f"{action} {target} "
            f"{' '.join(keywords)}"
        ).strip()

        return EvidenceRecord(
            record_type="business_rule",
            dataset=self.dataset,
            run_id=self.run_id,
            source_file=row_data.get("source_file", ""),
            workbook_name=row_data.get("workbook_name", ""),
            sheet_name=row_data.get("sheet_name", ""),
            sheet_index=row_data.get("sheet_index", 0),
            cell_range=row_data.get("cell_range", ""),
            row_number=row_data.get("row_number"),
            table_type=table_type,
            table_region_id=row_data.get("table_region_id", ""),
            column_roles=column_roles,
            text=text_for_llm,
            text_for_llm=text_for_llm,
            text_for_embedding=text_for_embedding,
            raw_values={k: v for k, v in row_data.get("values", {}).items() if v is not None},
            normalized_values={k: str(v).strip() for k, v in row_data.get("values", {}).items()
                if v is not None and str(v).strip()
            },
            source_cell_refs=row_data.get("cell_refs", {}),
            keywords=keywords,
            entity_mentions=systems,
            record_role="business_rule",
            parser="BusinessRuleEvidenceBuilder",
            confidence=1.0,
            metadata={
                "condition": condition,
                "action": action,
                "target": target,
                "business_object": business_object,
            },
        )

    def build_all(
        self,
        normalized_rows: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
        column_roles_map: dict[str, dict[str, str]],
    ) -> list[EvidenceRecord]:
        """全行を処理して business_rule レコードリストを返す。"""
        type_by_id = {
            c.get("table_region_id", ""): c.get("table_type", "unknown_table")
            for c in classifications
        }

        records: list[EvidenceRecord] = []
        skipped = 0
        for row in normalized_rows:
            region_id = row.get("table_region_id", "")
            table_type = type_by_id.get(region_id, "unknown_table")
            column_roles = column_roles_map.get(region_id, {})
            try:
                rec = self.build_from_row(row, table_type, column_roles)
                if rec is not None:
                    records.append(rec)
                else:
                    skipped += 1
            except Exception:
                logger.exception(
                    "BusinessRuleEvidenceBuilder: error on row %s region %s",
                    row.get("row_number"),
                    region_id,
                )

        logger.info(
            "BusinessRuleEvidenceBuilder: %d business_rule records built, %d skipped",
            len(records),
            skipped,
        )
        return records

    def build_sheet_summaries(
        self,
        sheet_records: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
    ) -> list[EvidenceRecord]:
        """シートごとの sheet_summary レコードを生成する。

        各シートについて:
        - 含まれるテーブル種別の集計
        - 登場するシステム名
        - ビジュアルオブジェクト数 (prescan 情報があれば)
        """
        # sheet → table_types, systems のマップを構築
        type_by_region: dict[str, str] = {
            c.get("table_region_id", ""): c.get("table_type", "unknown_table")
            for c in classifications
        }

        # (source_file, sheet_name) → { table_types, systems, region_count, workbook_name, ... }
        sheet_data: dict[tuple[str, str], dict[str, Any]] = {}

        for sr in sheet_records:
            key = (sr.get("source_file", ""), sr.get("sheet_name", ""))
            if key not in sheet_data:
                sheet_data[key] = {
                    "source_file": sr.get("source_file", ""),
                    "workbook_name": sr.get("workbook_name", ""),
                    "sheet_name": sr.get("sheet_name", ""),
                    "sheet_index": sr.get("sheet_index", 0),
                    "source_s3_uri": sr.get("source_s3_uri", ""),
                    "table_types": [],
                    "systems": [],
                    "region_ids": [],
                }

        for region in table_regions:
            key = (region.get("source_file", ""), region.get("sheet_name", ""))
            if key not in sheet_data:
                sheet_data[key] = {
                    "source_file": region.get("source_file", ""),
                    "workbook_name": region.get("workbook_name", ""),
                    "sheet_name": region.get("sheet_name", ""),
                    "sheet_index": region.get("sheet_index", 0),
                    "source_s3_uri": region.get("source_s3_uri", ""),
                    "table_types": [],
                    "systems": [],
                    "region_ids": [],
                }
            region_id = region.get("table_region_id", "")
            t_type = type_by_region.get(region_id, "unknown_table")
            sheet_data[key]["table_types"].append(t_type)
            sheet_data[key]["region_ids"].append(region_id)
            # extract systems from merged cell labels
            for mc in region.get("merged_cells", []):
                val = str(mc.get("value", "")).strip()
                if val:
                    sheet_data[key]["systems"].append(val)
            # extract system names from columns / data sample
            for hit in _SYSTEM_PATTERN.findall(" ".join(region.get("columns", []))):
                sheet_data[key]["systems"].append(hit)

        records: list[EvidenceRecord] = []
        for (source_file, sheet_name), sd in sheet_data.items():
            if not sheet_name:
                continue

            table_types_unique = list(dict.fromkeys(sd["table_types"]))
            systems_unique = list(dict.fromkeys(sd["systems"]))
            region_count = len(sd["region_ids"])

            table_type_str = ", ".join(table_types_unique) or "なし"
            systems_str = ", ".join(systems_unique) or "不明"

            text_for_llm = (
                f"シート「{sheet_name}」の概要: "
                f"テーブル{region_count}件 (種別: {table_type_str})。"
                f"登場システム: {systems_str}。"
            )
            text_for_embedding = (
                f"sheet summary シート概要 {sheet_name} "
                f"{table_type_str} {systems_str}"
            ).strip()

            records.append(EvidenceRecord(
                record_type="sheet_summary",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=source_file,
                workbook_name=sd.get("workbook_name", ""),
                sheet_name=sheet_name,
                sheet_index=sd.get("sheet_index", 0),
                source_s3_uri=sd.get("source_s3_uri", ""),
                text=text_for_llm,
                text_for_llm=text_for_llm,
                text_for_embedding=text_for_embedding,
                keywords=table_types_unique + systems_unique,
                entity_mentions=systems_unique,
                parser="BusinessRuleEvidenceBuilder",
                confidence=1.0,
                metadata={
                    "table_types": table_types_unique,
                    "systems": systems_unique,
                    "region_count": region_count,
                    "region_ids": sd["region_ids"],
                },
            ))

        logger.info(
            "BusinessRuleEvidenceBuilder: %d sheet_summary records built",
            len(records),
        )
        return records


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _extract_role_values(
    row_data: dict[str, Any],
    column_roles: dict[str, str],
) -> dict[str, str]:
    rv: dict[str, str] = {}
    for col, role in column_roles.items():
        val = row_data.get(col)
        if val is not None:
            rv.setdefault(role, str(val).strip())
    return rv


def _pick_first(rv: dict[str, str], roles: frozenset[str]) -> str:
    for role in roles:
        val = rv.get(role, "")
        if val:
            return val
    return ""


def _extract_keywords(row_data: dict[str, Any]) -> list[str]:
    words: list[str] = []
    for k, v in row_data.get("values", {}).items():
        if isinstance(v, str) and v.strip():
            words.extend(re.split(r"[\s,、。・/\\|]+", v))
    return list(dict.fromkeys(w for w in words if len(w) > 1))


def _extract_systems(row_data: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(v) for k, v in row_data.get("values", {}).items()
        if isinstance(v, str)
    )
    return list(dict.fromkeys(_SYSTEM_PATTERN.findall(text)))
