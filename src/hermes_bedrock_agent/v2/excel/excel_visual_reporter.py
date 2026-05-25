"""
Excel Visual Reporter — generates the final report for X7C stage.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelVisualReporter:
    """Generate excel_visual_parse_report.md for X7C stage."""

    def __init__(
        self,
        workbook_records: list[dict[str, Any]],
        sheet_records: list[dict[str, Any]],
        object_records: list[dict[str, Any]],
        analysis_records: list[dict[str, Any]],
        sheet_image_results: list[dict[str, Any]],
        generated_files: list[str],
        output_dir: str,
        run_id: str = "",
        dataset: str = "",
        s3_uri: str = "",
        warnings: list[str] | None = None,
        bedrock_used: bool = False,
        model_id: str = "",
    ):
        self.workbook_records = workbook_records
        self.sheet_records = sheet_records
        self.object_records = object_records
        self.analysis_records = analysis_records
        self.sheet_image_results = sheet_image_results
        self.generated_files = generated_files
        self.output_dir = Path(output_dir)
        self.reports_dir = self.output_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.dataset = dataset
        self.s3_uri = s3_uri
        self.warnings = warnings or []
        self.bedrock_used = bedrock_used
        self.model_id = model_id

    def generate_report(self) -> str:
        """Generate and write the final report."""
        path = self.reports_dir / "excel_visual_parse_report.md"

        visual_objects = len(self.object_records)
        sheet_images_exported = sum(1 for r in self.sheet_image_results if r.get('image_path'))
        embedded_images = sum(1 for o in self.object_records if o.get('object_type') == 'embedded_image')
        charts = sum(1 for o in self.object_records if o.get('object_type') == 'chart')
        shapes = sum(1 for o in self.object_records if o.get('object_type') in ('shape', 'textbox', 'group'))
        connectors = sum(1 for o in self.object_records if o.get('object_type') in ('connector', 'arrow'))
        with_text = sum(1 for o in self.object_records if o.get('text'))
        successful_analyses = sum(1 for a in self.analysis_records if a.get('confidence', 0) > 0.1)
        failed_analyses = len(self.analysis_records) - successful_analyses

        # Determine decision
        has_flowchart = any('フローチャート' in a.get('sheet_name', '') for a in self.analysis_records if a.get('confidence', 0) > 0.3)
        has_overview = any('概要' in a.get('sheet_name', '') for a in self.analysis_records if a.get('confidence', 0) > 0.3)

        if successful_analyses > 0 and visual_objects > 0:
            decision = "GO"
        elif visual_objects > 0:
            decision = "CONDITIONAL GO"
        else:
            decision = "NO-GO"

        lines = [f"# Excel Visual Parse Report\n"]
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Run ID:** {self.run_id}")
        lines.append(f"**Dataset:** {self.dataset}")
        lines.append("")

        # 1. Executive Summary
        lines.append(f"## 1. Executive Summary\n")
        lines.append(f"**Decision:** {decision}\n")
        lines.append(f"- Visual objects found: **{'YES' if visual_objects > 0 else 'NO'}** ({visual_objects} objects)")
        lines.append(f"- Sheet images exported: **{'YES' if sheet_images_exported > 0 else 'NO (LibreOffice unavailable)'}**")
        lines.append(f"- Bedrock analysis performed: **{'YES' if self.bedrock_used else 'NO'}**")
        lines.append(f"- フローチャート recovered: **{'YES' if has_flowchart else 'PARTIAL/NO'}**")
        lines.append(f"- 概要 recovered: **{'YES' if has_overview else 'PARTIAL/NO'}**")
        lines.append("")

        # 2. Input Summary
        lines.append("## 2. Input Summary\n")
        lines.append(f"- S3 Path: `{self.s3_uri}`")
        lines.append(f"- Workbook Count: {len(self.workbook_records)}")
        total_sheets = sum(r.get('sheet_count', 0) for r in self.workbook_records)
        lines.append(f"- Sheet Count: {total_sheets}")
        lines.append("")

        # 3. Extraction Summary
        lines.append("## 3. Extraction Summary\n")
        lines.append(f"- Visual objects total: {visual_objects}")
        lines.append(f"- Sheet images exported: {sheet_images_exported}")
        lines.append(f"- Embedded images: {embedded_images}")
        lines.append(f"- Charts: {charts}")
        lines.append(f"- Shapes/textboxes: {shapes}")
        lines.append(f"- Connectors/arrows: {connectors}")
        lines.append(f"- Objects with text: {with_text}")
        lines.append(f"- Objects without text: {visual_objects - with_text}")
        lines.append("")

        type_counts = Counter(o.get('object_type', 'unknown') for o in self.object_records)
        if type_counts:
            lines.append("### Object Type Breakdown\n")
            lines.append("| Type | Count |")
            lines.append("|------|------:|")
            for t, c in type_counts.most_common():
                lines.append(f"| {t} | {c} |")
            lines.append("")

        # 4. Bedrock Analysis Summary
        lines.append("## 4. Bedrock Analysis Summary\n")
        lines.append(f"- Model used: `{self.model_id}`")
        lines.append(f"- Images analyzed: {len(self.analysis_records)}")
        lines.append(f"- Successful analyses: {successful_analyses}")
        lines.append(f"- Failed/low-confidence: {failed_analyses}")
        lines.append("")

        # 5. Sheet-Level Results
        lines.append("## 5. Sheet-Level Results\n")
        lines.append("| Workbook | Sheet | Visual Objs | Images | Bedrock | Confidence | Summary |")
        lines.append("|----------|-------|----------:|-------:|---------|----------:|---------|")
        for s in sorted(self.sheet_records, key=lambda x: (x.get('workbook_name', ''), x.get('sheet_index', 0))):
            sheet_analyses = [a for a in self.analysis_records
                           if a.get('sheet_name') == s.get('sheet_name') and a.get('workbook_name') == s.get('workbook_name')]
            conf = max((a.get('confidence', 0) for a in sheet_analyses), default=0)
            summary = ""
            if sheet_analyses:
                summary = sheet_analyses[0].get('summary', '')[:40]
            bedrock_status = "✓" if sheet_analyses else "—"
            lines.append(
                f"| {s.get('workbook_name', '')[:30]} "
                f"| {s.get('sheet_name', '')} "
                f"| {s.get('object_count', 0)} "
                f"| {s.get('image_count', 0)} "
                f"| {bedrock_status} "
                f"| {conf:.2f} "
                f"| {summary} |"
            )
        lines.append("")

        # 6. フローチャート
        lines.append("## 6. フローチャート Result\n")
        fc_analyses = [a for a in self.analysis_records if 'フローチャート' in a.get('sheet_name', '')]
        if fc_analyses:
            a = fc_analyses[0]
            lines.append(f"- Recovered: **YES**")
            lines.append(f"- Confidence: {a.get('confidence', 0):.2f}")
            lines.append(f"- Flow steps: {len(a.get('flowchart_steps', []))}")
            lines.append(f"- Diagram nodes: {len(a.get('diagram_nodes', []))}")
            lines.append(f"- Diagram edges: {len(a.get('diagram_edges', []))}")
        else:
            fc_objects = [o for o in self.object_records if 'フローチャート' in o.get('sheet_name', '')]
            if fc_objects:
                lines.append(f"- Visual objects extracted: {len(fc_objects)}")
                lines.append("- Bedrock analysis: not performed or failed")
            else:
                lines.append("- Not recovered (no visual objects found for this sheet)")
        lines.append("")

        # 7. 概要
        lines.append("## 7. 概要 Result\n")
        ov_analyses = [a for a in self.analysis_records if '概要' in a.get('sheet_name', '')]
        if ov_analyses:
            a = ov_analyses[0]
            lines.append(f"- Recovered: **YES**")
            lines.append(f"- Confidence: {a.get('confidence', 0):.2f}")
            lines.append(f"- Summary: {a.get('summary', '')[:100]}")
        else:
            lines.append("- Not recovered via Bedrock (may have cell-only content)")
        lines.append("")

        # 8. Generated Files
        lines.append("## 8. Generated Files\n")
        for f in sorted(self.generated_files):
            lines.append(f"- `{f}`")
        lines.append("")

        # 9. Known Limitations
        lines.append("## 9. Known Limitations\n")
        lines.append("- Sheet-level screenshot unavailable (LibreOffice not installed)")
        lines.append("- PyMuPDF not available for PDF→PNG conversion")
        lines.append("- SVG images cannot be analyzed by Bedrock")
        lines.append("- Drawing XML shapes may be partially parsed (complex groups)")
        lines.append("- Connector semantics (source→target linkage) are positional, not semantic")
        lines.append("- VML drawings may contain comment indicators rather than content")
        lines.append("- Chart data is not extracted as raw values")
        lines.append("- SmartArt is represented as grouped shapes")
        lines.append("- OCR is not separately performed")
        lines.append("- Formula evaluation is not performed")
        lines.append("")

        # 10. Recommended Next Stage
        lines.append("## 10. Recommended Next Stage\n")
        if decision == "GO":
            lines.append("1. **Manual verification** of visual parse Markdown against original Excel")
            lines.append("2. **X7D:** Convert verified visual analysis into EvidenceChunks")
            lines.append("3. **X8:** Update Business Graph with Flowchart BusinessStep candidates")
        elif decision == "CONDITIONAL GO":
            lines.append("1. **Install LibreOffice** for full sheet-level image export")
            lines.append("2. **Re-run with --use-bedrock** after fixing any model access issues")
            lines.append("3. **Manual verification** of extracted objects")
        else:
            lines.append("1. Check workbook contents manually")
            lines.append("2. Verify S3 access and file integrity")
        lines.append("")

        if self.warnings:
            lines.append("## Warnings\n")
            for w in self.warnings:
                lines.append(f"- ⚠️ {w}")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        logger.info("Generated report: %s", path)
        return str(path)
