"""
Run reporter — パイプライン実行レポートを生成する。

出力 (reports/ ディレクトリ):
  - evidence_pipeline_report.md … メインレポート (全統計)
  - excel_parse_report.md       … Excel 解析レポート
  - visual_parse_report.md      … ビジュアル解析レポート
  - mermaid_parse_report.md     … Mermaid 解析レポート
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)


class RunReporter:
    """パイプライン実行レポートを生成するクラス。

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

    def generate_all(
        self,
        output_dir: str,
        evidence_records: list[EvidenceRecord] | None = None,
        workbook_records: list[dict[str, Any]] | None = None,
        sheet_records: list[dict[str, Any]] | None = None,
        table_regions: list[dict[str, Any]] | None = None,
        normalized_rows: list[dict[str, Any]] | None = None,
        prescan_records: list[dict[str, Any]] | None = None,
        drawing_objects: list[dict[str, Any]] | None = None,
        connectors: list[dict[str, Any]] | None = None,
        chart_objects: list[dict[str, Any]] | None = None,
        image_records: list[dict[str, Any]] | None = None,
        graph_records: list[dict[str, Any]] | None = None,
        node_records: list[dict[str, Any]] | None = None,
        edge_records: list[dict[str, Any]] | None = None,
        visual_analysis_records: list[dict[str, Any]] | None = None,
        elapsed_seconds: float | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, str]:
        """全レポートを生成して出力パスの dict を返す。"""
        reports_dir = Path(output_dir) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 引数の正規化
        evidence_records = evidence_records or []
        workbook_records = workbook_records or []
        sheet_records = sheet_records or []
        table_regions = table_regions or []
        normalized_rows = normalized_rows or []
        prescan_records = prescan_records or []
        drawing_objects = drawing_objects or []
        connectors = connectors or []
        chart_objects = chart_objects or []
        image_records = image_records or []
        graph_records = graph_records or []
        node_records = node_records or []
        edge_records = edge_records or []
        visual_analysis_records = visual_analysis_records or []
        errors = errors or []

        paths: dict[str, str] = {}

        paths["pipeline"] = self._write_pipeline_report(
            reports_dir=reports_dir,
            evidence_records=evidence_records,
            workbook_records=workbook_records,
            sheet_records=sheet_records,
            table_regions=table_regions,
            normalized_rows=normalized_rows,
            image_records=image_records,
            graph_records=graph_records,
            node_records=node_records,
            edge_records=edge_records,
            visual_analysis_records=visual_analysis_records,
            drawing_objects=drawing_objects,
            connectors=connectors,
            chart_objects=chart_objects,
            elapsed_seconds=elapsed_seconds,
            errors=errors,
        )

        paths["excel_parse"] = self._write_excel_report(
            reports_dir=reports_dir,
            workbook_records=workbook_records,
            sheet_records=sheet_records,
            table_regions=table_regions,
            normalized_rows=normalized_rows,
        )

        paths["visual_parse"] = self._write_visual_report(
            reports_dir=reports_dir,
            prescan_records=prescan_records,
            drawing_objects=drawing_objects,
            connectors=connectors,
            chart_objects=chart_objects,
            image_records=image_records,
            visual_analysis_records=visual_analysis_records,
        )

        paths["mermaid_parse"] = self._write_mermaid_report(
            reports_dir=reports_dir,
            graph_records=graph_records,
            node_records=node_records,
            edge_records=edge_records,
        )

        logger.info("Generated %d run reports in %s", len(paths), reports_dir)
        return paths

    # ------------------------------------------------------------------
    # evidence_pipeline_report.md
    # ------------------------------------------------------------------

    def _write_pipeline_report(
        self,
        reports_dir: Path,
        evidence_records: list[EvidenceRecord],
        workbook_records: list[dict[str, Any]],
        sheet_records: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        normalized_rows: list[dict[str, Any]],
        image_records: list[dict[str, Any]],
        graph_records: list[dict[str, Any]],
        node_records: list[dict[str, Any]],
        edge_records: list[dict[str, Any]],
        visual_analysis_records: list[dict[str, Any]],
        drawing_objects: list[dict[str, Any]],
        connectors: list[dict[str, Any]],
        chart_objects: list[dict[str, Any]],
        elapsed_seconds: float | None,
        errors: list[str],
    ) -> str:
        path = str(reports_dir / "evidence_pipeline_report.md")
        now = datetime.now(timezone.utc).isoformat()

        type_counts: dict[str, int] = defaultdict(int)
        for r in evidence_records:
            type_counts[r.record_type] += 1

        elapsed_str = f"{elapsed_seconds:.1f}s" if elapsed_seconds is not None else "N/A"
        error_count = len(errors)
        status = "✓ SUCCESS" if error_count == 0 else f"⚠ COMPLETED WITH {error_count} ERROR(S)"

        lines: list[str] = [
            "# Evidence Pipeline Run Report",
            "",
            f"**Status:** {status}  ",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}  ",
            f"**Elapsed:** {elapsed_str}",
            "",
            "---",
            "",
            "## Stage Summary",
            "",
            "| Stage | Input | Output |",
            "|-------|-------|--------|",
            f"| S3 Discovery | — | {len(workbook_records)} workbooks |",
            f"| Excel Parse | {len(workbook_records)} workbooks | {len(sheet_records)} sheets |",
            f"| Table Detection | {len(sheet_records)} sheets | {len(table_regions)} regions, {len(normalized_rows)} rows |",
            f"| OOXML Visual Parse | {len(sheet_records)} sheets | {len(drawing_objects)} shapes, {len(connectors)} connectors, {len(chart_objects)} charts |",
            f"| Image Extraction | {len(workbook_records)} workbooks | {len(image_records)} images |",
            f"| Mermaid Parse | — | {len(graph_records)} graphs, {len(node_records)} nodes, {len(edge_records)} edges |",
            f"| VLM Analysis | {len(image_records)} images | {len(visual_analysis_records)} analyses |",
            f"| Record Build | all above | {len(evidence_records)} evidence records |",
            "",
            "## Evidence Records by Type",
            "",
            "| Record Type | Count | % |",
            "|-------------|-------|---|",
        ]
        total = len(evidence_records) or 1
        for rtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            lines.append(f"| {rtype} | {count} | {pct:.1f}% |")
        lines.append("")

        # Workbook ごとのレコード数
        if workbook_records:
            lines += [
                "## Records per Workbook",
                "",
                "| Workbook | Evidence Records |",
                "|----------|-----------------|",
            ]
            wb_counts: dict[str, int] = defaultdict(int)
            for r in evidence_records:
                if r.workbook_name:
                    wb_counts[r.workbook_name] += 1
            for wb in workbook_records:
                name = wb.get("workbook_name", wb.get("file_name", ""))
                lines.append(f"| {wb.get('file_name', '')} | {wb_counts.get(name, 0)} |")
            lines.append("")

        # エラー
        if errors:
            lines += ["## Errors", ""]
            for i, err in enumerate(errors, 1):
                lines.append(f"{i}. {err}")
            lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # excel_parse_report.md
    # ------------------------------------------------------------------

    def _write_excel_report(
        self,
        reports_dir: Path,
        workbook_records: list[dict[str, Any]],
        sheet_records: list[dict[str, Any]],
        table_regions: list[dict[str, Any]],
        normalized_rows: list[dict[str, Any]],
    ) -> str:
        path = str(reports_dir / "excel_parse_report.md")
        now = datetime.now(timezone.utc).isoformat()

        lines: list[str] = [
            "# Excel Parse Report",
            "",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}",
            "",
            "## Workbooks",
            "",
            f"Total: {len(workbook_records)}",
            "",
        ]

        if workbook_records:
            lines += [
                "| File | Sheets | Visible | Hidden | File Size |",
                "|------|--------|---------|--------|-----------|",
            ]
            for wb in workbook_records:
                kb = wb.get("file_size_bytes", 0) / 1024
                lines.append(
                    f"| {wb.get('file_name', '')} "
                    f"| {wb.get('sheet_count', 0)} "
                    f"| {wb.get('visible_sheet_count', 0)} "
                    f"| {wb.get('hidden_sheet_count', 0)} "
                    f"| {kb:.1f} KB |"
                )
            lines.append("")

        lines += [
            "## Sheets",
            "",
            f"Total: {len(sheet_records)}",
            "",
        ]

        if sheet_records:
            lines += [
                "| Workbook | Sheet | Rows | Cols | Non-empty | Formulas | Comments |",
                "|----------|-------|------|------|-----------|----------|----------|",
            ]
            for sh in sheet_records:
                lines.append(
                    f"| {sh.get('workbook_name', '')} "
                    f"| {sh.get('sheet_name', '')} "
                    f"| {sh.get('max_row', 0)} "
                    f"| {sh.get('max_column', 0)} "
                    f"| {sh.get('non_empty_cell_count', 0)} "
                    f"| {'✓' if sh.get('has_formula') else ''} "
                    f"| {'✓' if sh.get('has_comments') else ''} |"
                )
            lines.append("")

        lines += [
            "## Table Detection",
            "",
            f"Table regions: {len(table_regions)}  ",
            f"Normalized rows: {len(normalized_rows)}",
            "",
        ]

        if table_regions:
            lines += [
                "| Workbook | Sheet | Range | Type | Rows | Columns | Confidence |",
                "|----------|-------|-------|------|------|---------|------------|",
            ]
            for tr in table_regions:
                cols_preview = ", ".join(tr.get("columns", [])[:4])
                if len(tr.get("columns", [])) > 4:
                    cols_preview += "…"
                lines.append(
                    f"| {tr.get('workbook_name', '')} "
                    f"| {tr.get('sheet_name', '')} "
                    f"| {tr.get('cell_range', '')} "
                    f"| {tr.get('region_type', '')} "
                    f"| {tr.get('data_row_count', 0)} "
                    f"| {cols_preview} "
                    f"| {tr.get('confidence', 0):.2f} |"
                )
            lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # visual_parse_report.md
    # ------------------------------------------------------------------

    def _write_visual_report(
        self,
        reports_dir: Path,
        prescan_records: list[dict[str, Any]],
        drawing_objects: list[dict[str, Any]],
        connectors: list[dict[str, Any]],
        chart_objects: list[dict[str, Any]],
        image_records: list[dict[str, Any]],
        visual_analysis_records: list[dict[str, Any]],
    ) -> str:
        path = str(reports_dir / "visual_parse_report.md")
        now = datetime.now(timezone.utc).isoformat()

        visual_sheets = [p for p in prescan_records if p.get("has_visual_objects")]

        lines: list[str] = [
            "# Visual Parse Report",
            "",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}",
            "",
            "## Summary",
            "",
            f"| Item | Count |",
            f"|------|-------|",
            f"| Sheets scanned | {len(prescan_records)} |",
            f"| Sheets with visuals | {len(visual_sheets)} |",
            f"| Drawing objects (shapes) | {len(drawing_objects)} |",
            f"| Connectors | {len(connectors)} |",
            f"| Charts | {len(chart_objects)} |",
            f"| Embedded images | {len(image_records)} |",
            f"| VLM analyses | {len(visual_analysis_records)} |",
            "",
        ]

        if prescan_records:
            lines += [
                "## Prescan Results",
                "",
                "| Sheet | Images | Charts | Connectors | Shapes | Strategy |",
                "|-------|--------|--------|------------|--------|----------|",
            ]
            for p in prescan_records:
                lines.append(
                    f"| {p.get('workbook_name', '')}/{p.get('sheet_name', '')} "
                    f"| {p.get('image_count', 0)} "
                    f"| {p.get('chart_count', 0)} "
                    f"| {p.get('connector_count', 0)} "
                    f"| {p.get('shape_count', 0)} "
                    f"| {p.get('suggested_strategy', '')} |"
                )
            lines.append("")

        if drawing_objects:
            lines += [
                "## Drawing Objects (sample)",
                "",
                "| Sheet | Type | Text |",
                "|-------|------|------|",
            ]
            for obj in drawing_objects[:20]:
                text_preview = (obj.get("text") or "")[:60].replace("\n", " ")
                lines.append(f"| {obj.get('sheet_name', '')} | {obj.get('shape_type', '')} | {text_preview} |")
            if len(drawing_objects) > 20:
                lines.append(f"*... {len(drawing_objects) - 20} more*")
            lines.append("")

        if connectors:
            lines += [
                "## Connectors (sample)",
                "",
                "| Sheet | Name | From | To |",
                "|-------|------|------|----|",
            ]
            for c in connectors[:20]:
                from_a = c.get("from_anchor", {})
                to_a = c.get("to_anchor", {})
                lines.append(
                    f"| {c.get('sheet_name', '')} "
                    f"| {c.get('connector_name', '')} "
                    f"| row={from_a.get('row')} col={from_a.get('col')} "
                    f"| row={to_a.get('row')} col={to_a.get('col')} |"
                )
            if len(connectors) > 20:
                lines.append(f"*... {len(connectors) - 20} more*")
            lines.append("")

        if image_records:
            lines += [
                "## Embedded Images",
                "",
                "| # | Format | Size | Sheet |",
                "|---|--------|------|-------|",
            ]
            for i, img in enumerate(image_records, 1):
                kb = img.get("size_bytes", 0) / 1024
                lines.append(
                    f"| {i} | {img.get('format', '')} | {kb:.1f} KB | {img.get('anchor_sheet', '')} |"
                )
            lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # mermaid_parse_report.md
    # ------------------------------------------------------------------

    def _write_mermaid_report(
        self,
        reports_dir: Path,
        graph_records: list[dict[str, Any]],
        node_records: list[dict[str, Any]],
        edge_records: list[dict[str, Any]],
    ) -> str:
        path = str(reports_dir / "mermaid_parse_report.md")
        now = datetime.now(timezone.utc).isoformat()

        lines: list[str] = [
            "# Mermaid Parse Report",
            "",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}",
            "",
            "## Summary",
            "",
            f"| Item | Count |",
            f"|------|-------|",
            f"| Graphs | {len(graph_records)} |",
            f"| Nodes | {len(node_records)} |",
            f"| Edges | {len(edge_records)} |",
            "",
        ]

        if not graph_records:
            lines.append("*No Mermaid files were found or parsed.*")
            _write(path, lines)
            return path

        # グラフ種別集計
        type_counts: dict[str, int] = defaultdict(int)
        for g in graph_records:
            type_counts[g.get("graph_type", "unknown")] += 1

        lines += [
            "## Graphs by Type",
            "",
            "| Graph Type | Count |",
            "|------------|-------|",
        ]
        for gtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {gtype} | {count} |")
        lines.append("")

        lines += [
            "## Graph Details",
            "",
            "| File | Type | Nodes | Edges | Associated Workbook |",
            "|------|------|-------|-------|---------------------|",
        ]
        for g in graph_records:
            lines.append(
                f"| {g.get('file_name', '')} "
                f"| {g.get('graph_type', '')} "
                f"| {g.get('node_count', 0)} "
                f"| {g.get('edge_count', 0)} "
                f"| {g.get('associated_workbook', '')} |"
            )
        lines.append("")

        _write(path, lines)
        return path


# ---- helpers ----------------------------------------------------------

def _write(path: str, lines: list[str]) -> None:
    content = "\n".join(lines)
    Path(path).write_text(content, encoding="utf-8")
    logger.info("Wrote %s", path)
