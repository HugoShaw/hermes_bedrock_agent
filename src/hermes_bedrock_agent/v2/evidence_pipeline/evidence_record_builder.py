"""
Evidence record builder — 全パーサーの出力を統一 EvidenceRecord に変換する。

最終成果物: parsed_text_records.jsonl

record_id = SHA256 hash of (source_file + sheet_name + record_type + content_key)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .evidence_schema import EvidenceRecord, write_jsonl

logger = logging.getLogger(__name__)


class EvidenceRecordBuilder:
    """全パーサー出力を EvidenceRecord に変換するビルダー。

    Parameters
    ----------
    dataset, run_id:
        パイプライン識別子。
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_evidence_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def build_all(
        self,
        sheet_records: list[dict[str, Any]] | None = None,
        table_regions: list[dict[str, Any]] | None = None,
        normalized_rows: list[dict[str, Any]] | None = None,
        drawing_objects: list[dict[str, Any]] | None = None,
        connectors: list[dict[str, Any]] | None = None,
        chart_objects: list[dict[str, Any]] | None = None,
        image_records: list[dict[str, Any]] | None = None,
        graph_records: list[dict[str, Any]] | None = None,
        node_records: list[dict[str, Any]] | None = None,
        edge_records: list[dict[str, Any]] | None = None,
        visual_analysis_records: list[dict[str, Any]] | None = None,
        formula_records: list[dict[str, Any]] | None = None,
        comment_records: list[dict[str, Any]] | None = None,
    ) -> list[EvidenceRecord]:
        """全パーサー出力から EvidenceRecord リストを構築する。

        Returns
        -------
        全 EvidenceRecord のリスト。
        """
        all_records: list[EvidenceRecord] = []

        all_records.extend(self._from_sheet_records(sheet_records or []))
        all_records.extend(self._from_table_regions(table_regions or []))
        all_records.extend(self._from_normalized_rows(normalized_rows or []))
        all_records.extend(self._from_drawing_objects(drawing_objects or []))
        all_records.extend(self._from_connectors(connectors or []))
        all_records.extend(self._from_chart_objects(chart_objects or []))
        all_records.extend(self._from_image_records(image_records or []))
        all_records.extend(self._from_graph_records(graph_records or []))
        all_records.extend(self._from_node_records(node_records or []))
        all_records.extend(self._from_edge_records(edge_records or []))
        all_records.extend(self._from_visual_analysis(visual_analysis_records or []))
        all_records.extend(self._from_formula_records(formula_records or []))
        all_records.extend(self._from_comment_records(comment_records or []))

        logger.info("EvidenceRecordBuilder: built %d total records", len(all_records))
        return all_records

    def write_jsonl(self, records: list[EvidenceRecord], output_dir: str) -> str:
        """EvidenceRecord リストを parsed_text_records.jsonl に書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = str(out / "parsed_text_records.jsonl")
        count = write_jsonl(records, path)
        logger.info("Wrote %d evidence records → %s", count, path)
        return path

    # ------------------------------------------------------------------
    # Per-type converters
    # ------------------------------------------------------------------

    def _from_sheet_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """シートレコード → sheet_text EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            # シート概要テキストを生成
            formula_samples = rec.get("formula_samples", [])
            comment_samples = rec.get("comment_samples", [])
            text_parts = [
                f"Sheet: {rec.get('sheet_name', '')}",
                f"Rows: {rec.get('max_row', 0)}, Cols: {rec.get('max_column', 0)}",
                f"Non-empty cells: {rec.get('non_empty_cell_count', 0)}",
            ]
            if rec.get("has_formula") and formula_samples:
                text_parts.append("Formulas: " + "; ".join(f"{f['cell']}={f['formula']}" for f in formula_samples[:5]))
            if rec.get("has_comments") and comment_samples:
                text_parts.append("Comments: " + "; ".join(f"{c['cell']}: {c['comment'][:50]}" for c in comment_samples[:3]))
            text = "\n".join(text_parts)

            er = _make_record(
                record_type="sheet_text",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                text=text,
                parser="excel_parser",
                confidence=1.0,
                metadata={
                    "sheet_id": rec.get("sheet_id", ""),
                    "max_row": rec.get("max_row", 0),
                    "max_column": rec.get("max_column", 0),
                    "non_empty_cell_count": rec.get("non_empty_cell_count", 0),
                    "has_formula": rec.get("has_formula", False),
                    "has_comments": rec.get("has_comments", False),
                    "merged_cell_count": rec.get("merged_cell_count", 0),
                },
            )
            result.append(er)
        logger.debug("sheet_text: %d records", len(result))
        return result

    def _from_table_regions(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """テーブル領域 → table_region EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            columns = rec.get("columns", [])
            text = f"Table ({rec.get('region_type', 'unknown')}): columns=[{', '.join(columns)}], rows={rec.get('data_row_count', 0)}"
            er = _make_record(
                record_type="table_region",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                cell_range=rec.get("cell_range", ""),
                column_names=columns,
                text=text,
                parser="excel_table_parser",
                confidence=rec.get("confidence", 0.8),
                metadata={
                    "table_region_id": rec.get("table_region_id", ""),
                    "region_type": rec.get("region_type", ""),
                    "data_row_count": rec.get("data_row_count", 0),
                    "column_count": rec.get("column_count", 0),
                    "header_rows": rec.get("header_rows", []),
                },
            )
            result.append(er)
        logger.debug("table_region: %d records", len(result))
        return result

    def _from_normalized_rows(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """正規化行データ → table_row EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            values = rec.get("values", {})
            text = json.dumps(values, ensure_ascii=False)
            er = _make_record(
                record_type="table_row",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                cell_range=rec.get("cell_range", ""),
                row_number=rec.get("row_number"),
                column_names=rec.get("column_names", []),
                text=text,
                parser="excel_table_parser",
                confidence=0.9,
                metadata={
                    "row_id": rec.get("row_id", ""),
                    "table_region_id": rec.get("table_region_id", ""),
                    "cell_refs": rec.get("cell_refs", {}),
                },
            )
            result.append(er)
        logger.debug("table_row: %d records", len(result))
        return result

    def _from_drawing_objects(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """ドローイングオブジェクト → drawing_object EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            text = rec.get("text", "").strip()
            shape_type = rec.get("shape_type", rec.get("object_type", "shape"))
            er = _make_record(
                record_type="drawing_object",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                text=text,
                parser="excel_ooxml_visual_parser",
                confidence=0.85,
                metadata={
                    "object_id": rec.get("object_id", ""),
                    "object_type": rec.get("object_type", "shape"),
                    "shape_type": shape_type,
                    "anchor": rec.get("anchor", {}),
                    "drawing_xml_path": rec.get("drawing_xml_path", ""),
                },
            )
            result.append(er)
        logger.debug("drawing_object: %d records", len(result))
        return result

    def _from_connectors(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """コネクター → connector EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            from_a = rec.get("from_anchor", {})
            to_a = rec.get("to_anchor", {})
            text = f"Connector: from={from_a} to={to_a} name={rec.get('connector_name', '')}"
            er = _make_record(
                record_type="connector",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                text=text,
                parser="excel_ooxml_visual_parser",
                confidence=0.9,
                metadata={
                    "connector_id": rec.get("connector_id", ""),
                    "connector_name": rec.get("connector_name", ""),
                    "from_anchor": from_a,
                    "to_anchor": to_a,
                    "drawing_xml_path": rec.get("drawing_xml_path", ""),
                },
            )
            result.append(er)
        logger.debug("connector: %d records", len(result))
        return result

    def _from_chart_objects(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """チャートオブジェクト → chart EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            text = f"Chart: rel_id={rec.get('chart_rel_id', '')} path={rec.get('chart_xml_path', '')}"
            er = _make_record(
                record_type="chart",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                text=text,
                parser="excel_ooxml_visual_parser",
                confidence=0.8,
                metadata={
                    "chart_id": rec.get("chart_id", ""),
                    "chart_rel_id": rec.get("chart_rel_id", ""),
                    "chart_xml_path": rec.get("chart_xml_path", ""),
                    "anchor": rec.get("anchor", {}),
                },
            )
            result.append(er)
        logger.debug("chart: %d records", len(result))
        return result

    def _from_image_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """埋め込み画像 → image_reference EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            text = f"Embedded image: {rec.get('format', '')} {rec.get('size_bytes', 0)} bytes"
            er = _make_record(
                record_type="image_reference",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("anchor_sheet", ""),
                sheet_index=rec.get("anchor_sheet_index") or 0,
                text=text,
                image_path=rec.get("local_path", ""),
                parser="excel_image_extractor",
                confidence=1.0,
                metadata={
                    "image_id": rec.get("image_id", ""),
                    "image_index": rec.get("image_index", 0),
                    "format": rec.get("format", ""),
                    "size_bytes": rec.get("size_bytes", 0),
                    "media_zip_path": rec.get("media_zip_path", ""),
                    "anchor_cell_from": rec.get("anchor_cell_from", ""),
                    "anchor_cell_to": rec.get("anchor_cell_to", ""),
                },
            )
            result.append(er)
        logger.debug("image_reference: %d records", len(result))
        return result

    def _from_graph_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """Mermaid グラフ → mermaid_graph EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            mermaid_src = rec.get("mermaid_source", "")
            text = f"Mermaid {rec.get('graph_type', '')} graph: {rec.get('node_count', 0)} nodes, {rec.get('edge_count', 0)} edges"
            er = _make_record(
                record_type="mermaid_graph",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("associated_workbook", ""),
                sheet_name="",
                text=text,
                mermaid_source=mermaid_src,
                parser="mermaid_parser",
                confidence=0.95,
                metadata={
                    "graph_id": rec.get("graph_id", ""),
                    "file_id": rec.get("file_id", ""),
                    "graph_type": rec.get("graph_type", ""),
                    "node_count": rec.get("node_count", 0),
                    "edge_count": rec.get("edge_count", 0),
                    "file_name": rec.get("file_name", ""),
                    "associated_workbook": rec.get("associated_workbook", ""),
                },
            )
            result.append(er)
        logger.debug("mermaid_graph: %d records", len(result))
        return result

    def _from_node_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """Mermaid ノード → mermaid_node EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            text = f"Node {rec.get('node_id', '')}: {rec.get('label', '')} ({rec.get('shape', '')})"
            er = _make_record(
                record_type="mermaid_node",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name="",
                sheet_name="",
                text=text,
                parser="mermaid_parser",
                confidence=0.9,
                metadata={
                    "node_record_id": rec.get("node_record_id", ""),
                    "file_id": rec.get("file_id", ""),
                    "node_id": rec.get("node_id", ""),
                    "label": rec.get("label", ""),
                    "shape": rec.get("shape", ""),
                    "subgraph": rec.get("subgraph", ""),
                },
            )
            result.append(er)
        logger.debug("mermaid_node: %d records", len(result))
        return result

    def _from_edge_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """Mermaid エッジ → mermaid_edge EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            label = rec.get("edge_label", "")
            text = f"Edge: {rec.get('from_id', '')} -> {rec.get('to_id', '')}"
            if label:
                text += f" [{label}]"
            er = _make_record(
                record_type="mermaid_edge",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name="",
                sheet_name="",
                text=text,
                parser="mermaid_parser",
                confidence=0.9,
                metadata={
                    "edge_record_id": rec.get("edge_record_id", ""),
                    "file_id": rec.get("file_id", ""),
                    "from_id": rec.get("from_id", ""),
                    "to_id": rec.get("to_id", ""),
                    "edge_label": label,
                    "line_number": rec.get("line_number"),
                },
            )
            result.append(er)
        logger.debug("mermaid_edge: %d records", len(result))
        return result

    def _from_visual_analysis(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """VLM 解析結果 → visual_analysis EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            text = rec.get("analysis_text", "")
            er = _make_record(
                record_type="visual_analysis",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("anchor_sheet", ""),
                sheet_index=rec.get("anchor_sheet_index") or 0,
                text=text,
                image_path=rec.get("local_path", ""),
                parser="optional_vision_analyzer",
                confidence=0.85,
                metadata={
                    "image_id": rec.get("image_id", ""),
                    "model_id": rec.get("model_id", ""),
                    "media_zip_path": rec.get("media_zip_path", ""),
                },
            )
            # Populate text_for_* fields from VLM analysis text
            if text:
                # Strip markdown for embedding (compact)
                import re as _re
                stripped = _re.sub(r"#{1,6}\s*", "", text)
                stripped = _re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
                stripped = _re.sub(r"---+", "", stripped)
                stripped = _re.sub(r"\n{3,}", "\n\n", stripped).strip()
                er.text_for_embedding = stripped[:2000]
                er.text_for_llm = text
                er.text_for_display = text
            result.append(er)
        logger.debug("visual_analysis: %d records", len(result))
        return result

    def _from_formula_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """数式サンプル (sheet_record 内) → formula EvidenceRecord。

        sheet_records の formula_samples を直接受け取る場合用。
        """
        result: list[EvidenceRecord] = []
        for rec in records:
            formula = rec.get("formula", "")
            cell = rec.get("cell", "")
            text = f"{cell}: {formula}"
            er = _make_record(
                record_type="formula",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                cell_range=cell,
                text=text,
                parser="excel_parser",
                confidence=1.0,
                metadata={"formula": formula, "cell": cell},
            )
            result.append(er)
        logger.debug("formula: %d records", len(result))
        return result

    def _from_comment_records(self, records: list[dict[str, Any]]) -> list[EvidenceRecord]:
        """コメントサンプル → comment EvidenceRecord。"""
        result: list[EvidenceRecord] = []
        for rec in records:
            comment_text = rec.get("comment", "")
            cell = rec.get("cell", "")
            text = f"{cell}: {comment_text}"
            er = _make_record(
                record_type="comment",
                dataset=self.dataset,
                run_id=self.run_id,
                source_file=rec.get("source_file", ""),
                source_s3_uri=rec.get("source_s3_uri", ""),
                workbook_name=rec.get("workbook_name", ""),
                sheet_name=rec.get("sheet_name", ""),
                sheet_index=rec.get("sheet_index", 0),
                cell_range=cell,
                text=text,
                parser="excel_parser",
                confidence=1.0,
                metadata={"comment": comment_text, "cell": cell},
            )
            result.append(er)
        logger.debug("comment: %d records", len(result))
        return result


# ---- helper -----------------------------------------------------------

def _make_record(
    record_type: str,
    dataset: str,
    run_id: str,
    source_file: str,
    source_s3_uri: str,
    workbook_name: str,
    sheet_name: str,
    text: str,
    parser: str,
    confidence: float,
    metadata: dict[str, Any],
    sheet_index: int = 0,
    cell_range: str = "",
    row_number: int | None = None,
    column_names: list[str] | None = None,
    image_path: str = "",
    mermaid_source: str = "",
) -> EvidenceRecord:
    return EvidenceRecord(
        record_type=record_type,
        dataset=dataset,
        run_id=run_id,
        source_file=source_file,
        source_s3_uri=source_s3_uri,
        workbook_name=workbook_name,
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        cell_range=cell_range,
        row_number=row_number,
        column_names=column_names or [],
        text=text,
        image_path=image_path,
        mermaid_source=mermaid_source,
        metadata=metadata,
        parser=parser,
        confidence=confidence,
    )
