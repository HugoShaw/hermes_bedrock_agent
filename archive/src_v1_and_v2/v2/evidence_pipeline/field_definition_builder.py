"""
フィールド定義ビルダー — field_mapping_table / data_dictionary_table 行から
field_definition EvidenceRecord を生成するモジュール。

フィールド名・型・桁数・説明などの属性が揃った行を対象に、
構造化されたフィールド定義レコードを出力する。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)

_APPLICABLE_TYPES = frozenset({"field_mapping_table", "data_dictionary_table"})


class FieldDefinitionBuilder:
    """フィールド定義 EvidenceRecord を生成するクラス。

    build_from_row() で1行から Optional[EvidenceRecord] を返し、
    build_all() で全行を一括処理する。
    """

    def __init__(self, dataset: str, run_id: str) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def build_from_row(
        self,
        row_data: dict[str, Any],
        table_type: str,
        column_roles: dict[str, str],
    ) -> Optional[EvidenceRecord]:
        """1行から field_definition レコードを生成する。対象外行は None を返す。"""
        if table_type not in _APPLICABLE_TYPES:
            return None

        rv = _extract_role_values(row_data.get("values", {}), column_roles)
        field_name = rv.get("source_field") or rv.get("target_field") or rv.get("item_name", "")
        if not field_name:
            return None

        # 少なくとも1つの属性が必要
        has_attr = any(rv.get(k) for k in ("source_data_type", "target_data_type",
                                            "source_length", "target_length",
                                            "description", "remarks", "required"))
        if not has_attr:
            return None

        system = rv.get("source_system") or rv.get("target_system", "")
        table_or_msg = rv.get("request_message") or rv.get("response_message", "")
        dtype = rv.get("source_data_type") or rv.get("target_data_type", "")
        length = rv.get("source_length") or rv.get("target_length", "")
        required = rv.get("required", "")
        description = rv.get("description") or rv.get("remarks", "")
        aliases = _build_aliases(field_name, rv)

        text_for_llm = (
            f"フィールド定義: {field_name} ({system}.{table_or_msg}) — "
            f"タイプ: {dtype}, 桁数: {length}, 必須: {required}. "
            f"説明: {description}"
        )
        text_for_embedding = (
            f"{field_name} {system} {table_or_msg} {dtype} {length} "
            f"field definition 項目定義 {' '.join(aliases)}"
        ).strip()

        entity_mentions = [e for e in [field_name, system, table_or_msg] if e]
        graph_hints: dict[str, Any] = {
            "candidate_nodes": _build_candidate_nodes(field_name, system, table_or_msg),
        }

        return EvidenceRecord(
            record_type="field_definition",
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
            text_for_embedding=text_for_embedding,
            text_for_llm=text_for_llm,
            raw_values={k: v for k, v in row_data.get("values", {}).items() if v is not None},
            normalized_values={k: str(v).strip() for k, v in row_data.get("values", {}).items()
                               if v is not None and str(v).strip()},
            source_cell_refs=row_data.get("cell_refs", {}),
            keywords=[field_name, system, dtype] + aliases,
            aliases=aliases,
            entity_mentions=entity_mentions,
            graph_hints=graph_hints,
            parser="FieldDefinitionBuilder",
            confidence=1.0,
            metadata={
                "field_name": field_name,
                "system": system,
                "table_or_message": table_or_msg,
                "data_type": dtype,
                "length": length,
                "required": required,
                "description": description,
            },
        )

    def build_all(
        self,
        normalized_rows: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
        column_roles_map: dict[str, dict[str, str]],
    ) -> list[EvidenceRecord]:
        """全行を処理して field_definition レコードリストを返す。"""
        type_by_id = {
            c.get("table_region_id", ""): c.get("table_type", "unknown_table")
            for c in classifications
        }
        roles_by_id = column_roles_map

        records: list[EvidenceRecord] = []
        skipped = 0
        for row in normalized_rows:
            region_id = row.get("table_region_id", "")
            table_type = type_by_id.get(region_id, "unknown_table")
            column_roles = roles_by_id.get(region_id, {})
            try:
                rec = self.build_from_row(row, table_type, column_roles)
                if rec is not None:
                    records.append(rec)
                else:
                    skipped += 1
            except Exception:
                logger.exception(
                    "FieldDefinitionBuilder: error on row %s region %s",
                    row.get("row_number"),
                    region_id,
                )

        logger.info(
            "FieldDefinitionBuilder: %d field_definition records built, %d skipped",
            len(records),
            skipped,
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


def _build_aliases(field_name: str, rv: dict[str, str]) -> list[str]:
    candidates = [
        rv.get("source_field", ""),
        rv.get("target_field", ""),
        rv.get("item_name", ""),
    ]
    return list(dict.fromkeys(c for c in candidates if c and c != field_name))


def _build_candidate_nodes(
    field_name: str,
    system: str,
    table_or_msg: str,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if system:
        nodes.append({"label": "System", "name": system})
    if table_or_msg:
        nodes.append({"label": "Table", "name": table_or_msg, "parent": system})
    if field_name:
        nodes.append({"label": "Column", "name": field_name,
                      "parent": f"{system}.{table_or_msg}" if table_or_msg else system})
    return nodes
