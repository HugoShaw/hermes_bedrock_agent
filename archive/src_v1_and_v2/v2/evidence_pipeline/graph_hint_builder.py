"""
グラフヒントビルダー — 行データからグラフ関係候補を生成するモジュール。

テーブル種別ごとのパターンでノード・エッジ候補を検出し、
graph_candidate EvidenceRecord として出力する。
出力: reports/graph_hints_report.md
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)


class GraphHintBuilder:
    """グラフ関係候補の EvidenceRecord を生成するクラス。

    build_from_row() で1行から Optional[EvidenceRecord] を返し、
    build_all() で全行を一括処理する。
    write_report() で Markdown レポートを出力する。
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
        """1行から graph_candidate レコードを生成する。候補なしは None。"""
        rv = _extract_role_values(row_data.get("values", {}), column_roles)

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        if table_type == "field_mapping_table":
            _build_mapping_hints(rv, nodes, edges)
        elif table_type == "api_definition_table":
            _build_api_hints(rv, nodes, edges)
        elif table_type == "data_condition_table":
            _build_condition_hints(rv, nodes, edges)
        else:
            _build_generic_hints(rv, nodes, edges)

        if not edges and not nodes:
            return None

        graph_hints: dict[str, Any] = {
            "candidate_nodes": nodes,
            "candidate_edges": edges,
        }

        text_for_llm = _describe_hints(table_type, rv, edges)
        text_for_embedding = _embedding_text(edges, rv)

        return EvidenceRecord(
            record_type="graph_candidate",
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
            graph_hints=graph_hints,
            entity_mentions=list({
                n["name"] for n in nodes if n.get("name")
            }),
            parser="GraphHintBuilder",
            confidence=_calc_confidence(edges),
        )

    def build_all(
        self,
        normalized_rows: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        classifications: list[dict[str, Any]],
        column_roles_map: dict[str, dict[str, str]],
    ) -> list[EvidenceRecord]:
        """全行を処理して graph_candidate レコードリストを返す。"""
        type_by_id = {
            c.get("table_region_id", ""): c.get("table_type", "unknown_table")
            for c in classifications
        }

        records: list[EvidenceRecord] = []
        for row in normalized_rows:
            region_id = row.get("table_region_id", "")
            table_type = type_by_id.get(region_id, "unknown_table")
            column_roles = column_roles_map.get(region_id, {})
            try:
                rec = self.build_from_row(row, table_type, column_roles)
                if rec is not None:
                    records.append(rec)
            except Exception:
                logger.exception(
                    "GraphHintBuilder: error on row %s region %s",
                    row.get("row_number"),
                    region_id,
                )

        logger.info(
            "GraphHintBuilder: %d graph_candidate records built from %d rows",
            len(records),
            len(normalized_rows),
        )
        return records

    def write_report(
        self,
        hints: list[EvidenceRecord],
        output_path: str,
    ) -> None:
        """グラフ候補を Markdown レポートとして書き出す。"""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        edge_count = sum(
            len(r.graph_hints.get("candidate_edges", [])) for r in hints
        )
        node_count = sum(
            len(r.graph_hints.get("candidate_nodes", [])) for r in hints
        )

        lines: list[str] = [
            "# Graph Hint Builder Report",
            "",
            f"Total graph_candidate records: {len(hints)}",
            f"Total candidate edges: {edge_count}",
            f"Total candidate nodes: {node_count}",
            "",
            "## Edges",
            "",
            "| # | Source | Relation | Target | Confidence |",
            "|---|--------|----------|--------|------------|",
        ]

        idx = 1
        for rec in hints:
            for edge in rec.graph_hints.get("candidate_edges", []):
                lines.append(
                    f"| {idx} "
                    f"| {edge.get('source', '')} "
                    f"| {edge.get('relation', '')} "
                    f"| {edge.get('target', '')} "
                    f"| {edge.get('confidence', 0.0):.2f} |"
                )
                idx += 1

        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("GraphHintBuilder: wrote report → %s", output_path)


# ------------------------------------------------------------------
# pattern builders
# ------------------------------------------------------------------

def _build_mapping_hints(
    rv: dict[str, str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    src_sys = rv.get("source_system", "")
    src_fld = rv.get("source_field", "")
    tgt_sys = rv.get("target_system", "")
    tgt_fld = rv.get("target_field", "")

    if src_sys:
        nodes.append({"label": "System", "name": src_sys})
    if src_fld:
        nodes.append({"label": "Column", "name": src_fld, "parent": src_sys})
    if tgt_sys:
        nodes.append({"label": "System", "name": tgt_sys})
    if tgt_fld:
        nodes.append({"label": "Column", "name": tgt_fld, "parent": tgt_sys})

    if src_fld and tgt_fld:
        src_id = f"{src_sys}.{src_fld}" if src_sys else src_fld
        tgt_id = f"{tgt_sys}.{tgt_fld}" if tgt_sys else tgt_fld
        edges.append({
            "source": src_id,
            "relation": "MAPS_TO",
            "target": tgt_id,
            "confidence": 0.9,
        })

    if src_sys and tgt_sys and src_sys != tgt_sys:
        edges.append({
            "source": src_sys,
            "relation": "RELATED_TO",
            "target": tgt_sys,
            "confidence": 0.7,
        })


def _build_api_hints(
    rv: dict[str, str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    api_name = rv.get("api_name", "")
    req = rv.get("request_message", "")
    res = rv.get("response_message", "")

    if api_name:
        nodes.append({"label": "API", "name": api_name})
    if req:
        nodes.append({"label": "Message", "name": req})
        if api_name:
            edges.append({
                "source": api_name,
                "relation": "USES",
                "target": req,
                "confidence": 0.85,
            })
    if res:
        nodes.append({"label": "Message", "name": res})
        if api_name:
            edges.append({
                "source": api_name,
                "relation": "RETURNS",
                "target": res,
                "confidence": 0.85,
            })


def _build_condition_hints(
    rv: dict[str, str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    condition = rv.get("condition", "")
    target = rv.get("target_field") or rv.get("item_name", "")
    field = rv.get("source_field") or rv.get("item_no", "")

    if condition:
        nodes.append({"label": "BusinessRule", "name": condition})
    if field:
        nodes.append({"label": "Column", "name": field})
        if condition:
            edges.append({
                "source": condition,
                "relation": "HAS_TERM",
                "target": field,
                "confidence": 0.75,
            })
    if target and condition:
        edges.append({
            "source": condition,
            "relation": "FILTERS",
            "target": target,
            "confidence": 0.75,
        })


def _build_generic_hints(
    rv: dict[str, str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    src_sys = rv.get("source_system", "")
    tgt_sys = rv.get("target_system", "")
    if src_sys and tgt_sys and src_sys != tgt_sys:
        nodes.append({"label": "System", "name": src_sys})
        nodes.append({"label": "System", "name": tgt_sys})
        edges.append({
            "source": src_sys,
            "relation": "RELATED_TO",
            "target": tgt_sys,
            "confidence": 0.6,
        })


# ------------------------------------------------------------------
# text generators
# ------------------------------------------------------------------

def _describe_hints(
    table_type: str,
    rv: dict[str, str],
    edges: list[dict[str, Any]],
) -> str:
    if not edges:
        return "グラフ関係候補なし"
    parts = []
    for edge in edges:
        parts.append(f"{edge['source']} —[{edge['relation']}]→ {edge['target']}")
    return "グラフ関係候補: " + "; ".join(parts)


def _embedding_text(
    edges: list[dict[str, Any]],
    rv: dict[str, str],
) -> str:
    tokens: list[str] = []
    for edge in edges:
        tokens += [edge.get("source", ""), edge.get("relation", ""), edge.get("target", "")]
    for key in ("source_field", "target_field", "source_system", "target_system",
                "api_name", "condition"):
        if rv.get(key):
            tokens.append(rv[key])
    tokens.append("field mapping relationship graph")
    return " ".join(t for t in tokens if t)


def _calc_confidence(edges: list[dict[str, Any]]) -> float:
    if not edges:
        return 0.5
    return round(sum(e.get("confidence", 0.5) for e in edges) / len(edges), 3)


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
