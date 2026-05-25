"""
行セマンティックレンダラー — テーブル行ごとの意味的 EvidenceRecord を生成するモジュール。

テーブル種別に応じたテンプレートで text_for_embedding / text_for_llm を生成する。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)

_SYSTEM_PATTERN = re.compile(
    r"(SAP|中間F|Oracle|DB2|Salesforce|MySQL|PostgreSQL|[A-Z]{2,}システム)", re.IGNORECASE
)
_FIELD_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,30}$")


class RowSemanticRenderer:
    """テーブル行ごとの EvidenceRecord を生成するクラス。

    render_row() で1行分のレコードを生成し、
    render_all() で正規化済み行リスト全体を一括処理する。
    """

    def __init__(self, dataset: str, run_id: str) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def render_row(
        self,
        row_data: dict[str, Any],
        table_type: str,
        column_roles: dict[str, str],
        table_region: dict[str, Any],
    ) -> EvidenceRecord:
        """1行分の table_row EvidenceRecord を生成する。"""
        # row_data has nested "values" dict with actual cell values
        cell_values = row_data.get("values", {})
        values = _extract_role_values(cell_values, column_roles)
        sheet_name = row_data.get("sheet_name", "") or table_region.get("sheet_name", "")
        workbook_name = row_data.get("workbook_name", "") or table_region.get("workbook_name", "")
        row_number: Optional[int] = row_data.get("row_number")
        cell_refs: dict[str, str] = row_data.get("cell_refs", {})

        raw_vals = {k: v for k, v in cell_values.items() if v is not None and str(v).strip()}
        norm_vals = {k: str(v).strip() for k, v in cell_values.items() if v is not None and str(v).strip()}

        text_for_llm, text_for_embedding = _render_texts(
            table_type, values, raw_vals, sheet_name, row_number
        )

        keywords = _extract_keywords(raw_vals)
        entity_mentions = _extract_entity_mentions(raw_vals, values)

        return EvidenceRecord(
            record_type="table_row",
            dataset=self.dataset,
            run_id=self.run_id,
            source_file=row_data.get("source_file", "") or table_region.get("source_file", ""),
            workbook_name=workbook_name,
            sheet_name=sheet_name,
            sheet_index=table_region.get("sheet_index", 0),
            cell_range=row_data.get("cell_range", "") or table_region.get("cell_range", ""),
            row_number=row_number,
            column_names=row_data.get("column_names", list(cell_values.keys())),
            table_type=table_type,
            table_region_id=row_data.get("table_region_id", "") or table_region.get("table_region_id", ""),
            column_roles=column_roles,
            text=text_for_llm,
            text_for_embedding=text_for_embedding,
            text_for_llm=text_for_llm,
            raw_values=raw_vals,
            normalized_values=norm_vals,
            source_cell_refs=cell_refs,
            keywords=keywords,
            entity_mentions=entity_mentions,
            parser="RowSemanticRenderer",
            confidence=1.0,
        )

    def render_all(
        self,
        normalized_rows: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
        column_roles_map: dict[str, dict[str, str]],
    ) -> list[EvidenceRecord]:
        """全行の EvidenceRecord リストを生成する。"""
        region_by_id = {r.get("table_region_id", ""): r for r in table_regions}
        type_by_id = {
            c.get("table_region_id", ""): c.get("table_type", "unknown_table")
            for c in classifications
        }

        records: list[EvidenceRecord] = []
        for row in normalized_rows:
            region_id = row.get("_table_region_id", "")
            region = region_by_id.get(region_id, {})
            table_type = type_by_id.get(region_id, "unknown_table")
            column_roles = column_roles_map.get(region_id, {})
            try:
                rec = self.render_row(row, table_type, column_roles, region)
                records.append(rec)
            except Exception:
                logger.exception(
                    "Failed to render row %s in region %s",
                    row.get("_row_number"),
                    region_id,
                )

        logger.info(
            "RowSemanticRenderer: generated %d row records from %d input rows",
            len(records),
            len(normalized_rows),
        )
        return records


# ------------------------------------------------------------------
# template dispatch
# ------------------------------------------------------------------

def _render_texts(
    table_type: str,
    values: dict[str, str],
    raw_vals: dict[str, Any],
    sheet_name: str,
    row_number: Optional[int],
) -> tuple[str, str]:
    if table_type == "field_mapping_table":
        return _tmpl_field_mapping(values)
    if table_type == "api_definition_table":
        return _tmpl_api_definition(values)
    if table_type == "data_condition_table":
        return _tmpl_data_condition(values)
    if table_type == "data_dictionary_table":
        return _tmpl_data_dictionary(values)
    return _tmpl_unknown(raw_vals, sheet_name, row_number)


def _tmpl_field_mapping(v: dict[str, str]) -> tuple[str, str]:
    src_sys = v.get("source_system", "")
    src_fld = v.get("source_field", "")
    tgt_sys = v.get("target_system", "")
    tgt_fld = v.get("target_field", "")
    rule = v.get("mapping_rule", "")
    remarks = v.get("remarks", v.get("description", ""))
    aliases = " ".join([src_fld, tgt_fld]).strip()

    llm = (
        f"{src_sys}の項目{src_fld}は{tgt_sys}の項目{tgt_fld}にマッピングされる。"
        f"変換ルールは「{rule}」。備考: {remarks}"
    )
    emb = (
        f"{src_fld} {tgt_fld} {src_sys} {tgt_sys} "
        f"maps_to mapping {rule} {aliases}"
    ).strip()
    return llm, emb


def _tmpl_api_definition(v: dict[str, str]) -> tuple[str, str]:
    name = v.get("api_name", "")
    method = v.get("method", "")
    path = v.get("path", "")
    req = v.get("request_message", "")
    res = v.get("response_message", "")

    llm = f"API {name}: {method} {path}. リクエスト: {req}. レスポンス: {res}."
    emb = f"API {name} {method} {path} {req} {res} endpoint interface".strip()
    return llm, emb


def _tmpl_data_condition(v: dict[str, str]) -> tuple[str, str]:
    condition = v.get("condition", "")
    target = v.get("target_field", v.get("item_name", ""))
    fields = v.get("source_field", v.get("item_no", ""))

    llm = f"データ取得条件: {condition}を満たす場合に{target}を取得する。対象フィールド: {fields}"
    emb = f"condition {condition} {target} {fields} data retrieval filter".strip()
    return llm, emb


def _tmpl_data_dictionary(v: dict[str, str]) -> tuple[str, str]:
    fname = v.get("source_field", v.get("item_name", ""))
    dtype = v.get("source_data_type", v.get("target_data_type", ""))
    length = v.get("source_length", v.get("target_length", ""))
    desc = v.get("description", v.get("remarks", ""))

    llm = f"項目{fname}はタイプ{dtype}、桁数{length}。説明: {desc}"
    emb = f"{fname} {dtype} {length} {desc} field definition column".strip()
    return llm, emb


def _tmpl_unknown(
    raw_vals: dict[str, Any],
    sheet_name: str,
    row_number: Optional[int],
) -> tuple[str, str]:
    pairs = ", ".join(f"{k}={v}" for k, v in raw_vals.items() if v)
    llm = f"{sheet_name}の行{row_number}: {pairs}"
    emb = " ".join(str(v) for v in raw_vals.values() if v)
    return llm, emb


# ------------------------------------------------------------------
# extraction helpers
# ------------------------------------------------------------------

def _extract_role_values(
    row_data: dict[str, Any],
    column_roles: dict[str, str],
) -> dict[str, str]:
    """column_roles を使ってロール名 → 値のマップを構築する。"""
    role_values: dict[str, str] = {}
    for col, role in column_roles.items():
        val = row_data.get(col)
        if val is not None:
            role_values.setdefault(role, str(val).strip())
    return role_values


def _extract_keywords(raw_vals: dict[str, Any]) -> list[str]:
    words: list[str] = []
    for v in raw_vals.values():
        if isinstance(v, str):
            words.extend(re.split(r"[\s,、。・/\\|]+", v))
    return list(dict.fromkeys(w for w in words if len(w) > 1))


def _extract_entity_mentions(
    raw_vals: dict[str, Any],
    role_values: dict[str, str],
) -> list[str]:
    mentions: list[str] = []
    for v in raw_vals.values():
        if isinstance(v, str):
            for m in _SYSTEM_PATTERN.findall(v):
                mentions.append(m)
    for role in ("source_field", "target_field", "source_system", "target_system", "api_name"):
        val = role_values.get(role, "")
        if val:
            mentions.append(val)
    return list(dict.fromkeys(mentions))
