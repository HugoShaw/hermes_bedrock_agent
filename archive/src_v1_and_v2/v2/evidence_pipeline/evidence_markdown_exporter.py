"""
Evidence Markdown exporter — 人間レビュー用 Markdown ファイルを生成する。

出力:
  - evidence_full_review.md      … ワークブック/シート別の全コンテンツ
  - evidence_summary.md          … 高レベル統計
  - visual_reference_review.md   … ビジュアルアイテムと画像パス
  - mermaid_review.md            … Mermaid コンテンツ
  - human_review_checklist.md    … 検証チェックリスト
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)


class EvidenceMarkdownExporter:
    """EvidenceRecord リストから Markdown ファイルを生成するエクスポーター。

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

    def export_all(
        self,
        records: list[EvidenceRecord],
        output_dir: str,
        workbook_records: list[dict[str, Any]] | None = None,
        sheet_records: list[dict[str, Any]] | None = None,
        prescan_records: list[dict[str, Any]] | None = None,
        image_records: list[dict[str, Any]] | None = None,
        graph_records: list[dict[str, Any]] | None = None,
        node_records: list[dict[str, Any]] | None = None,
        edge_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """全 Markdown ファイルを生成して出力パスの dict を返す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        paths: dict[str, str] = {}

        paths["evidence_full_review"] = self._write_full_review(records, out)
        paths["evidence_summary"] = self._write_summary(records, out, workbook_records or [], sheet_records or [])
        paths["visual_reference_review"] = self._write_visual_review(records, out, image_records or [], prescan_records or [])
        paths["mermaid_review"] = self._write_mermaid_review(records, out, graph_records or [], node_records or [], edge_records or [])
        paths["human_review_checklist"] = self._write_checklist(records, out, workbook_records or [], prescan_records or [])

        logger.info("Exported %d Markdown files to %s", len(paths), out)
        return paths

    # ------------------------------------------------------------------
    # evidence_full_review.md
    # ------------------------------------------------------------------

    def _write_full_review(self, records: list[EvidenceRecord], out: Path) -> str:
        path = str(out / "evidence_full_review.md")
        now = datetime.now(timezone.utc).isoformat()

        lines: list[str] = [
            "# Evidence Full Review",
            "",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}  ",
            f"**Total records:** {len(records)}",
            "",
            "---",
            "",
        ]

        # ワークブック → シート → レコード種別 の階層でグループ化
        by_wb: dict[str, dict[str, list[EvidenceRecord]]] = defaultdict(lambda: defaultdict(list))
        no_wb: list[EvidenceRecord] = []

        for rec in records:
            if rec.workbook_name:
                by_wb[rec.workbook_name][rec.sheet_name or "(no sheet)"].append(rec)
            else:
                no_wb.append(rec)

        for wb_name, sheets in sorted(by_wb.items()):
            lines.append(f"## Workbook: {wb_name}")
            lines.append("")
            for sheet_name, recs in sorted(sheets.items()):
                lines.append(f"### Sheet: {sheet_name}")
                lines.append("")
                by_type: dict[str, list[EvidenceRecord]] = defaultdict(list)
                for r in recs:
                    by_type[r.record_type].append(r)
                for rtype, type_recs in sorted(by_type.items()):
                    lines.append(f"#### {rtype} ({len(type_recs)} records)")
                    lines.append("")
                    for r in type_recs[:20]:  # 先頭20件のみ表示
                        lines.extend(_format_record(r))
                    if len(type_recs) > 20:
                        lines.append(f"*... {len(type_recs) - 20} more records omitted*")
                        lines.append("")
            lines.append("---")
            lines.append("")

        if no_wb:
            lines.append("## Non-workbook records")
            lines.append("")
            by_type2: dict[str, list[EvidenceRecord]] = defaultdict(list)
            for r in no_wb:
                by_type2[r.record_type].append(r)
            for rtype, type_recs in sorted(by_type2.items()):
                lines.append(f"### {rtype} ({len(type_recs)} records)")
                lines.append("")
                for r in type_recs[:10]:
                    lines.extend(_format_record(r))
                if len(type_recs) > 10:
                    lines.append(f"*... {len(type_recs) - 10} more omitted*")
                    lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # evidence_summary.md
    # ------------------------------------------------------------------

    def _write_summary(
        self,
        records: list[EvidenceRecord],
        out: Path,
        workbook_records: list[dict[str, Any]],
        sheet_records: list[dict[str, Any]],
    ) -> str:
        path = str(out / "evidence_summary.md")
        now = datetime.now(timezone.utc).isoformat()

        type_counts: dict[str, int] = defaultdict(int)
        for r in records:
            type_counts[r.record_type] += 1

        wb_count = len(workbook_records)
        sheet_count = len(sheet_records)

        lines: list[str] = [
            "# Evidence Summary",
            "",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}  ",
            f"**Generated:** {now}",
            "",
            "## Source Statistics",
            "",
            f"| Item | Count |",
            f"|------|-------|",
            f"| Workbooks | {wb_count} |",
            f"| Sheets | {sheet_count} |",
            f"| Total evidence records | {len(records)} |",
            "",
            "## Records by Type",
            "",
            "| Record Type | Count |",
            "|-------------|-------|",
        ]
        for rtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {rtype} | {count} |")
        lines.append("")

        # ワークブック別サマリー
        if workbook_records:
            lines += [
                "## Workbook Summary",
                "",
                "| Workbook | Sheets | Visible |",
                "|----------|--------|---------|",
            ]
            for wb in workbook_records:
                lines.append(
                    f"| {wb.get('file_name', '')} | {wb.get('sheet_count', 0)} | {wb.get('visible_sheet_count', 0)} |"
                )
            lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # visual_reference_review.md
    # ------------------------------------------------------------------

    def _write_visual_review(
        self,
        records: list[EvidenceRecord],
        out: Path,
        image_records: list[dict[str, Any]],
        prescan_records: list[dict[str, Any]],
    ) -> str:
        path = str(out / "visual_reference_review.md")

        visual_types = {"drawing_object", "connector", "chart", "image_reference", "visual_analysis", "sheet_screenshot"}
        visual_recs = [r for r in records if r.record_type in visual_types]

        lines: list[str] = [
            "# Visual Reference Review",
            "",
            f"**Total visual records:** {len(visual_recs)}",
            f"**Embedded images:** {len(image_records)}",
            "",
        ]

        # Prescan サマリー
        if prescan_records:
            lines += [
                "## Sheet Visual Prescan",
                "",
                "| Sheet | Has Images | Has Charts | Has Connectors | Has Shapes | Strategy |",
                "|-------|-----------|------------|----------------|------------|----------|",
            ]
            for p in prescan_records:
                lines.append(
                    f"| {p.get('sheet_name', '')} "
                    f"| {'✓' if p.get('has_images') else ''} "
                    f"| {'✓' if p.get('has_charts') else ''} "
                    f"| {'✓' if p.get('has_connectors') else ''} "
                    f"| {'✓' if p.get('has_shapes') else ''} "
                    f"| {p.get('suggested_strategy', '')} |"
                )
            lines.append("")

        # 埋め込み画像一覧
        if image_records:
            lines += [
                "## Embedded Images",
                "",
                "| # | File | Format | Size | Sheet | Local Path |",
                "|---|------|--------|------|-------|------------|",
            ]
            for i, img in enumerate(image_records, 1):
                kb = img.get("size_bytes", 0) / 1024
                lines.append(
                    f"| {i} | {Path(img.get('media_zip_path', '')).name} "
                    f"| {img.get('format', '')} "
                    f"| {kb:.1f} KB "
                    f"| {img.get('anchor_sheet', '')} "
                    f"| `{img.get('local_path', '')}` |"
                )
            lines.append("")

        # visual_analysis レコード
        va_recs = [r for r in records if r.record_type == "visual_analysis"]
        if va_recs:
            lines += ["## VLM Analysis Results", ""]
            for r in va_recs:
                lines.append(f"### Image: `{r.image_path}`")
                lines.append(f"**Sheet:** {r.sheet_name}  ")
                lines.append(f"**Model:** {r.metadata.get('model_id', '')}  ")
                lines.append("")
                lines.append(r.text)
                lines.append("")
                lines.append("---")
                lines.append("")

        # connector レコード
        conn_recs = [r for r in records if r.record_type == "connector"]
        if conn_recs:
            lines += [
                "## Connectors",
                "",
                f"Total connectors: {len(conn_recs)}",
                "",
            ]
            by_sheet: dict[str, list[EvidenceRecord]] = defaultdict(list)
            for r in conn_recs:
                by_sheet[r.sheet_name].append(r)
            for sheet, recs in sorted(by_sheet.items()):
                lines.append(f"### {sheet} ({len(recs)} connectors)")
                lines.append("")
                for r in recs[:10]:
                    lines.append(f"- {r.text}")
                if len(recs) > 10:
                    lines.append(f"  *... {len(recs) - 10} more*")
                lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # mermaid_review.md
    # ------------------------------------------------------------------

    def _write_mermaid_review(
        self,
        records: list[EvidenceRecord],
        out: Path,
        graph_records: list[dict[str, Any]],
        node_records: list[dict[str, Any]],
        edge_records: list[dict[str, Any]],
    ) -> str:
        path = str(out / "mermaid_review.md")

        lines: list[str] = [
            "# Mermaid Review",
            "",
            f"**Graphs:** {len(graph_records)}  ",
            f"**Nodes:** {len(node_records)}  ",
            f"**Edges:** {len(edge_records)}",
            "",
        ]

        if not graph_records:
            lines.append("*No Mermaid files found.*")
            _write(path, lines)
            return path

        # ノード・エッジを graph_id でインデックス化
        nodes_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        edges_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for n in node_records:
            nodes_by_file[n.get("file_id", "")].append(n)
        for e in edge_records:
            edges_by_file[e.get("file_id", "")].append(e)

        for graph in graph_records:
            file_id = graph.get("file_id", "")
            lines.append(f"## {graph.get('file_name', '')} ({graph.get('graph_type', '')})")
            lines.append("")
            lines.append(f"**Associated workbook:** {graph.get('associated_workbook', 'N/A')}  ")
            lines.append(f"**Nodes:** {graph.get('node_count', 0)}  ")
            lines.append(f"**Edges:** {graph.get('edge_count', 0)}")
            lines.append("")

            # Mermaid ソース
            src = graph.get("mermaid_source", "")
            if src:
                lines.append("### Source")
                lines.append("")
                lines.append("```mermaid")
                lines.append(src)
                lines.append("```")
                lines.append("")

            # ノード一覧
            g_nodes = nodes_by_file.get(file_id, [])
            if g_nodes:
                lines.append("### Nodes")
                lines.append("")
                lines.append("| ID | Label | Shape | Subgraph |")
                lines.append("|----|-------|-------|----------|")
                for n in g_nodes:
                    lines.append(f"| {n.get('node_id','')} | {n.get('label','')} | {n.get('shape','')} | {n.get('subgraph','')} |")
                lines.append("")

            # エッジ一覧
            g_edges = edges_by_file.get(file_id, [])
            if g_edges:
                lines.append("### Edges")
                lines.append("")
                lines.append("| From | To | Label |")
                lines.append("|------|----|-------|")
                for e in g_edges:
                    lines.append(f"| {e.get('from_id','')} | {e.get('to_id','')} | {e.get('edge_label','')} |")
                lines.append("")

            lines.append("---")
            lines.append("")

        _write(path, lines)
        return path

    # ------------------------------------------------------------------
    # human_review_checklist.md
    # ------------------------------------------------------------------

    def _write_checklist(
        self,
        records: list[EvidenceRecord],
        out: Path,
        workbook_records: list[dict[str, Any]],
        prescan_records: list[dict[str, Any]],
    ) -> str:
        path = str(out / "human_review_checklist.md")

        type_counts: dict[str, int] = defaultdict(int)
        for r in records:
            type_counts[r.record_type] += 1

        has_visual_issues = any(
            p.get("has_connectors") or p.get("has_charts")
            for p in prescan_records
        )
        has_mermaid = type_counts.get("mermaid_graph", 0) > 0
        has_vlm = type_counts.get("visual_analysis", 0) > 0

        lines: list[str] = [
            "# Human Review Checklist",
            "",
            f"**Dataset:** {self.dataset}  ",
            f"**Run ID:** {self.run_id}",
            "",
            "## Data Completeness",
            "",
            f"- [ ] Verify all {len(workbook_records)} workbooks were processed",
            f"- [ ] Confirm {type_counts.get('sheet_text', 0)} sheet records are present",
            f"- [ ] Confirm {type_counts.get('table_region', 0)} table regions detected",
            f"- [ ] Confirm {type_counts.get('table_row', 0)} table rows normalized",
            "",
            "## Visual Content",
            "",
            f"- [ ] Review {type_counts.get('drawing_object', 0)} drawing objects for text accuracy",
            f"- [ ] Review {type_counts.get('connector', 0)} connectors for from/to mapping",
            f"- [ ] Review {type_counts.get('chart', 0)} chart references",
            f"- [ ] Review {type_counts.get('image_reference', 0)} embedded image references",
        ]

        if has_visual_issues:
            lines.append("- [ ] **[ACTION REQUIRED]** Sheets with connectors/charts need manual verification")

        lines += [
            "",
            "## Mermaid Content",
            "",
        ]
        if has_mermaid:
            lines += [
                f"- [ ] Verify {type_counts.get('mermaid_graph', 0)} Mermaid graphs parsed correctly",
                f"- [ ] Verify {type_counts.get('mermaid_node', 0)} nodes extracted",
                f"- [ ] Verify {type_counts.get('mermaid_edge', 0)} edges extracted",
                "- [ ] Check workbook associations for each Mermaid file",
            ]
        else:
            lines.append("- [x] No Mermaid files found (skip)")

        lines += [
            "",
            "## VLM Analysis",
            "",
        ]
        if has_vlm:
            lines += [
                f"- [ ] Review {type_counts.get('visual_analysis', 0)} VLM analysis results",
                "- [ ] Verify analysis accuracy against source images",
                "- [ ] Flag any hallucinated content",
            ]
        else:
            lines.append("- [x] VLM analysis not run or no results (skip)")

        lines += [
            "",
            "## Final Validation",
            "",
            "- [ ] Open `evidence_full_review.md` and spot-check 5+ random records",
            "- [ ] Confirm `parsed_text_records.jsonl` was generated",
            "- [ ] Confirm record count matches expectations",
            "- [ ] Check for any empty `text` fields in critical record types",
            "- [ ] Verify S3 upload completed (if applicable)",
            "",
            "## Sign-off",
            "",
            "| Reviewer | Date | Notes |",
            "|----------|------|-------|",
            "|          |      |       |",
            "",
        ]

        _write(path, lines)
        return path


# ---- helpers ----------------------------------------------------------

def _format_record(rec: EvidenceRecord) -> list[str]:
    """レコードを Markdown ブロックとしてフォーマットする。"""
    lines = [
        f"**[{rec.record_id}]** `{rec.record_type}`",
        "",
    ]
    if rec.cell_range:
        lines.append(f"- **Range:** `{rec.cell_range}`")
    if rec.row_number is not None:
        lines.append(f"- **Row:** {rec.row_number}")
    if rec.column_names:
        lines.append(f"- **Columns:** {', '.join(rec.column_names[:10])}")
    if rec.text:
        preview = rec.text[:300].replace("\n", " ↵ ")
        lines.append(f"- **Text:** {preview}")
    if rec.image_path:
        lines.append(f"- **Image:** `{rec.image_path}`")
    if rec.mermaid_source:
        src_preview = rec.mermaid_source[:100].replace("\n", " ↵ ")
        lines.append(f"- **Mermaid:** {src_preview}")
    lines.append(f"- **Parser:** {rec.parser}  **Confidence:** {rec.confidence:.2f}")
    lines.append("")
    return lines


def _write(path: str, lines: list[str]) -> None:
    content = "\n".join(lines)
    Path(path).write_text(content, encoding="utf-8")
    logger.info("Wrote %s", path)
