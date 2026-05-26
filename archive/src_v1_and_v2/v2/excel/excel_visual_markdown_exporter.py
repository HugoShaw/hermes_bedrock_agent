"""
Excel Visual Markdown Exporter — generates comprehensive Markdown from visual parse results.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_visual_schema import (
    BedrockVisualAnalysisRecord,
    ExcelVisualObjectRecord,
    ExcelVisualSheetRecord,
    ExcelVisualWorkbookRecord,
)

logger = logging.getLogger(__name__)


class ExcelVisualMarkdownExporter:
    """Generate comprehensive Markdown files from visual parse results."""

    def __init__(
        self,
        workbook_records: list[dict[str, Any]],
        sheet_records: list[dict[str, Any]],
        object_records: list[dict[str, Any]],
        analysis_records: list[dict[str, Any]],
        sheet_image_results: list[dict[str, Any]],
        output_dir: str,
        run_id: str = "",
        dataset: str = "",
        s3_uri: str = "",
        warnings: list[str] | None = None,
    ):
        self.workbook_records = workbook_records
        self.sheet_records = sheet_records
        self.object_records = object_records
        self.analysis_records = analysis_records
        self.sheet_image_results = sheet_image_results
        self.output_dir = Path(output_dir)
        self.md_dir = self.output_dir / "markdown"
        self.md_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.dataset = dataset
        self.s3_uri = s3_uri
        self.warnings = warnings or []

    def export_all(self) -> list[str]:
        """Generate all markdown files. Returns list of paths."""
        files = []
        files.append(self._generate_full_report())
        files.append(self._generate_summary())
        files.append(self._generate_quality_check())
        files.append(self._generate_visual_evidence_design())

        # Generate focused reports for priority sheets
        fc = self._generate_flowchart_report()
        if fc:
            files.append(fc)
        ov = self._generate_overview_report()
        if ov:
            files.append(ov)

        return files

    def _generate_full_report(self) -> str:
        """Generate the main comprehensive markdown file."""
        path = self.md_dir / "excel_visual_parse_full.md"

        lines = ["# Excel Visual Parse Full Report\n"]
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

        # Section 1: Metadata
        lines.append("## 1. Export Metadata\n")
        lines.append(f"- **Dataset:** {self.dataset}")
        lines.append(f"- **Run ID:** {self.run_id}")
        lines.append(f"- **Source S3 Path:** {self.s3_uri}")
        lines.append(f"- **Workbook Count:** {len(self.workbook_records)}")
        total_sheets = sum(r.get('sheet_count', 0) for r in self.workbook_records)
        visual_sheets = sum(1 for s in self.sheet_records if s.get('has_visual_objects'))
        lines.append(f"- **Sheet Count:** {total_sheets}")
        lines.append(f"- **Visual Sheet Count:** {visual_sheets}")
        lines.append(f"- **Visual Object Count:** {len(self.object_records)}")
        lines.append(f"- **Embedded Image Count:** {sum(1 for o in self.object_records if o.get('object_type') == 'embedded_image')}")
        lines.append(f"- **Chart Count:** {sum(1 for o in self.object_records if o.get('object_type') == 'chart')}")
        lines.append(f"- **Shape/Textbox Count:** {sum(1 for o in self.object_records if o.get('object_type') in ('shape', 'textbox', 'group'))}")
        lines.append(f"- **Connector/Arrow Count:** {sum(1 for o in self.object_records if o.get('object_type') in ('connector', 'arrow'))}")
        lines.append(f"- **Bedrock Analysis Count:** {len(self.analysis_records)}")
        lines.append("")

        # Section 2: Executive Summary
        lines.append("## 2. Executive Summary\n")
        has_visuals = len(self.object_records) > 0
        has_bedrock = len(self.analysis_records) > 0
        successful_analyses = sum(1 for a in self.analysis_records if a.get('confidence', 0) > 0.1)
        lines.append(f"- Visual content found: **{'YES' if has_visuals else 'NO'}**")
        lines.append(f"- Bedrock analysis performed: **{'YES' if has_bedrock else 'NO'}**")
        if has_bedrock:
            lines.append(f"- Successful analyses: **{successful_analyses}/{len(self.analysis_records)}**")
        if self.warnings:
            lines.append(f"- Warnings: **{len(self.warnings)}**")
        lines.append("")

        # Section 3: Workbook Overview
        lines.append("## 3. Workbook Overview\n")
        lines.append("| Workbook | Sheets | Visual Sheets | Images | Charts | Drawing Objects | Bedrock Analyses |")
        lines.append("|----------|-------:|-------------:|-------:|-------:|----------------:|-----------------:|")
        for wb in self.workbook_records:
            wb_name = wb.get('workbook_name', '')
            wb_analyses = sum(1 for a in self.analysis_records if a.get('workbook_name') == wb_name)
            lines.append(
                f"| {wb_name} | {wb.get('sheet_count', 0)} | {wb.get('visual_sheet_count', 0)} "
                f"| {wb.get('image_count', 0)} | {wb.get('chart_count', 0)} "
                f"| {wb.get('drawing_object_count', 0)} | {wb_analyses} |"
            )
        lines.append("")

        # Section 4: Sheet-by-Sheet Visual Analysis
        lines.append("## 4. Sheet-by-Sheet Visual Analysis\n")

        for wb in self.workbook_records:
            wb_name = wb.get('workbook_name', '')
            lines.append(f"### Workbook: {wb_name}\n")

            wb_sheets = [s for s in self.sheet_records if s.get('workbook_name') == wb_name]
            for sheet in sorted(wb_sheets, key=lambda x: x.get('sheet_index', 0)):
                sheet_name = sheet.get('sheet_name', '')
                lines.append(f"#### Sheet {sheet.get('sheet_index', 0)}: {sheet_name}\n")

                # Sheet metadata
                lines.append("##### Sheet Visual Metadata\n")
                lines.append("| Field | Value |")
                lines.append("|-------|-------|")
                lines.append(f"| Has Visual Objects | {sheet.get('has_visual_objects', False)} |")
                lines.append(f"| Has Images | {sheet.get('has_images', False)} |")
                lines.append(f"| Has Charts | {sheet.get('has_charts', False)} |")
                lines.append(f"| Has Shapes | {sheet.get('has_shapes', False)} |")
                lines.append(f"| Has Drawings | {sheet.get('has_drawings', False)} |")
                lines.append(f"| Object Count | {sheet.get('object_count', 0)} |")
                lines.append(f"| Image Count | {sheet.get('image_count', 0)} |")
                lines.append(f"| Shape Count | {sheet.get('shape_count', 0)} |")
                lines.append(f"| Connector Count | {sheet.get('connector_count', 0)} |")
                lines.append("")

                # Objects for this sheet
                sheet_objects = [
                    o for o in self.object_records
                    if o.get('sheet_name') == sheet_name and o.get('workbook_name') == wb_name
                ]

                if sheet_objects:
                    # Images
                    images = [o for o in sheet_objects if o.get('object_type') == 'embedded_image']
                    if images:
                        lines.append("##### Embedded Images\n")
                        lines.append("| # | Name | Anchor | Alt Text | Image Path |")
                        lines.append("|--:|------|--------|----------|------------|")
                        for i, img in enumerate(images, 1):
                            lines.append(
                                f"| {i} | {img.get('object_name', '')} "
                                f"| {img.get('anchor_range', '')} "
                                f"| {img.get('alt_text', '')[:50]} "
                                f"| {os.path.basename(img.get('image_path', ''))} |"
                            )
                        lines.append("")

                    # Shapes/Textboxes
                    shapes = [o for o in sheet_objects if o.get('object_type') in ('shape', 'textbox', 'group')]
                    if shapes:
                        lines.append("##### Shapes and Textboxes\n")
                        lines.append("| # | Type | Name | Shape | Anchor | Text |")
                        lines.append("|--:|------|------|-------|--------|------|")
                        for i, shp in enumerate(shapes, 1):
                            text_preview = shp.get('text', '')[:80].replace('\n', ' ↩ ')
                            lines.append(
                                f"| {i} | {shp.get('object_type', '')} "
                                f"| {shp.get('object_name', '')[:30]} "
                                f"| {shp.get('shape_type', '')} "
                                f"| {shp.get('anchor_from_cell', '')} "
                                f"| {text_preview} |"
                            )
                        lines.append("")

                        # Full text for textboxes
                        textboxes_with_text = [s for s in shapes if s.get('text')]
                        if textboxes_with_text:
                            lines.append("##### Textbox Full Content\n")
                            for tb in textboxes_with_text:
                                lines.append(f"**{tb.get('object_name', 'unnamed')}** (anchor: {tb.get('anchor_from_cell', 'unknown')}):")
                                lines.append(f"```\n{tb.get('text', '')}\n```\n")

                    # Connectors
                    connectors = [o for o in sheet_objects if o.get('object_type') in ('connector', 'arrow')]
                    if connectors:
                        lines.append("##### Connectors and Arrows\n")
                        lines.append("| # | Type | Name | Shape | From | To |")
                        lines.append("|--:|------|------|-------|------|-----|")
                        for i, conn in enumerate(connectors, 1):
                            lines.append(
                                f"| {i} | {conn.get('object_type', '')} "
                                f"| {conn.get('object_name', '')[:30]} "
                                f"| {conn.get('shape_type', '')} "
                                f"| {conn.get('anchor_from_cell', '')} "
                                f"| {conn.get('anchor_to_cell', '')} |"
                            )
                        lines.append("")

                    # Charts
                    charts = [o for o in sheet_objects if o.get('object_type') == 'chart']
                    if charts:
                        lines.append("##### Charts\n")
                        for i, ch in enumerate(charts, 1):
                            lines.append(f"- Chart {i}: {ch.get('object_name', 'unnamed')} (type: {ch.get('chart_type', 'unknown')})")
                        lines.append("")

                # Bedrock analysis
                sheet_analyses = [
                    a for a in self.analysis_records
                    if a.get('sheet_name') == sheet_name and a.get('workbook_name') == wb_name
                ]
                if sheet_analyses:
                    lines.append("##### Bedrock Claude Sonnet Analysis\n")
                    for analysis in sheet_analyses:
                        lines.append(f"**Target:** {analysis.get('analysis_target_type', '')} "
                                     f"| **Image:** {os.path.basename(analysis.get('image_path', ''))} "
                                     f"| **Confidence:** {analysis.get('confidence', 0):.2f}\n")

                        if analysis.get('summary'):
                            lines.append(f"###### Summary\n\n{analysis['summary']}\n")

                        detected_text = analysis.get('detected_text', [])
                        if detected_text:
                            lines.append("###### Detected Text\n")
                            for t in detected_text:
                                lines.append(f"- {t}")
                            lines.append("")

                        objects_detected = analysis.get('detected_objects', [])
                        if objects_detected:
                            lines.append("###### Detected Objects\n")
                            lines.append("| Type | Label | Description | Position | Confidence |")
                            lines.append("|------|-------|-------------|----------|----------:|")
                            for obj in objects_detected:
                                lines.append(
                                    f"| {obj.get('object_type', '')} "
                                    f"| {obj.get('label', '')} "
                                    f"| {obj.get('description', '')[:60]} "
                                    f"| {obj.get('position_hint', '')} "
                                    f"| {obj.get('confidence', 0):.2f} |"
                                )
                            lines.append("")

                        steps = analysis.get('flowchart_steps', [])
                        if steps:
                            lines.append("###### Flowchart Steps\n")
                            lines.append("| Step | Label | Description | Next Steps | Condition | Confidence |")
                            lines.append("|-----:|-------|-------------|------------|-----------|----------:|")
                            for step in steps:
                                next_s = ", ".join(step.get('next_steps', []))
                                lines.append(
                                    f"| {step.get('step_no', '')} "
                                    f"| {step.get('label', '')} "
                                    f"| {step.get('description', '')[:50]} "
                                    f"| {next_s} "
                                    f"| {step.get('condition', '')} "
                                    f"| {step.get('confidence', 0):.2f} |"
                                )
                            lines.append("")

                        nodes = analysis.get('diagram_nodes', [])
                        if nodes:
                            lines.append("###### Diagram Nodes\n")
                            lines.append("| Node | Type | Description | Confidence |")
                            lines.append("|------|------|-------------|----------:|")
                            for node in nodes:
                                lines.append(
                                    f"| {node.get('label', '')} "
                                    f"| {node.get('type', '')} "
                                    f"| {node.get('description', '')[:60]} "
                                    f"| {node.get('confidence', 0):.2f} |"
                                )
                            lines.append("")

                        edges = analysis.get('diagram_edges', [])
                        if edges:
                            lines.append("###### Diagram Edges\n")
                            lines.append("| Source | Relation | Target | Label | Confidence |")
                            lines.append("|--------|----------|--------|-------|----------:|")
                            for edge in edges:
                                lines.append(
                                    f"| {edge.get('source', '')} "
                                    f"| {edge.get('relation', '')} "
                                    f"| {edge.get('target', '')} "
                                    f"| {edge.get('label', '')} "
                                    f"| {edge.get('confidence', 0):.2f} |"
                                )
                            lines.append("")

                        # Business terms, systems, etc.
                        for field_name, label in [
                            ('business_terms', 'Business Terms'),
                            ('systems', 'Systems'),
                            ('tables', 'Tables'),
                            ('fields', 'Fields'),
                            ('api_names', 'APIs'),
                            ('rules', 'Rules'),
                        ]:
                            items = analysis.get(field_name, [])
                            if items:
                                lines.append(f"###### {label}\n")
                                for item in items:
                                    lines.append(f"- {item}")
                                lines.append("")

                        warn = analysis.get('warnings', [])
                        if warn:
                            lines.append("###### Warnings\n")
                            for w in warn:
                                lines.append(f"- ⚠️ {w}")
                            lines.append("")

                lines.append("---\n")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        logger.info("Generated: %s (%d bytes)", path, len(content))
        return str(path)

    def _generate_summary(self) -> str:
        """Generate visual_parse_summary.md."""
        path = self.md_dir / "visual_parse_summary.md"

        lines = ["# Visual Parse Summary\n"]
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        lines.append("## Overview\n")
        lines.append(f"- Workbooks: {len(self.workbook_records)}")
        lines.append(f"- Total sheets: {sum(r.get('sheet_count', 0) for r in self.workbook_records)}")
        lines.append(f"- Visual sheets: {sum(1 for s in self.sheet_records if s.get('has_visual_objects'))}")
        lines.append(f"- Visual objects: {len(self.object_records)}")
        lines.append(f"- Bedrock analyses: {len(self.analysis_records)}")
        lines.append("")

        # Object type breakdown
        lines.append("## Object Type Breakdown\n")
        lines.append("| Type | Count |")
        lines.append("|------|------:|")
        from collections import Counter
        type_counts = Counter(o.get('object_type', 'unknown') for o in self.object_records)
        for otype, count in type_counts.most_common():
            lines.append(f"| {otype} | {count} |")
        lines.append("")

        # Key findings from Bedrock
        if self.analysis_records:
            lines.append("## Key Findings from Bedrock Analysis\n")
            for a in self.analysis_records:
                if a.get('confidence', 0) > 0.3:
                    lines.append(f"### {a.get('sheet_name', 'unknown')} — {os.path.basename(a.get('image_path', ''))}\n")
                    lines.append(f"**Summary:** {a.get('summary', 'N/A')}\n")
                    if a.get('flowchart_steps'):
                        lines.append(f"**Flowchart Steps:** {len(a['flowchart_steps'])}")
                    if a.get('diagram_nodes'):
                        lines.append(f"**Diagram Nodes:** {len(a['diagram_nodes'])}")
                    if a.get('systems'):
                        lines.append(f"**Systems:** {', '.join(a['systems'])}")
                    lines.append("")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _generate_quality_check(self) -> str:
        """Generate visual_parse_quality_check.md."""
        path = self.md_dir / "visual_parse_quality_check.md"

        lines = ["# Visual Parse Quality Check\n"]
        lines.append("## Manual Verification Checklist\n")
        lines.append("- [ ] All workbooks with visual content are listed")
        lines.append("- [ ] All sheets with visual content are listed")
        lines.append("- [ ] フローチャート sheet visual objects extracted")
        lines.append("- [ ] 概要 sheet visual objects extracted")
        lines.append("- [ ] Embedded images are extracted to raw_media/")
        lines.append("- [ ] Charts are detected")
        lines.append("- [ ] Shape/textbox text is extracted where possible")
        lines.append("- [ ] Bedrock analysis exists for visual-heavy sheets")
        lines.append("- [ ] Flowchart steps are reasonable")
        lines.append("- [ ] Diagram arrows/connectors are reasonably described")
        lines.append("- [ ] Japanese text is preserved")
        lines.append("- [ ] No hallucinated objects are obvious")
        lines.append("- [ ] Limitations are clearly stated")
        lines.append("")

        lines.append("## Sheets Requiring Human Review\n")
        lines.append("| Workbook | Sheet | Reason |")
        lines.append("|----------|-------|--------|")
        for s in self.sheet_records:
            reasons = []
            if not s.get('has_visual_objects') and s.get('sheet_name') in ('概要', 'フローチャート'):
                reasons.append("priority sheet, no visual objects detected")
            analyses = [a for a in self.analysis_records if a.get('sheet_name') == s.get('sheet_name')]
            failed = [a for a in analyses if a.get('confidence', 0) <= 0.1]
            if failed:
                reasons.append("Bedrock analysis low confidence")
            if s.get('has_visual_objects') and not analyses:
                reasons.append("has visual objects but no Bedrock analysis")
            if reasons:
                lines.append(f"| {s.get('workbook_name', '')} | {s.get('sheet_name', '')} | {'; '.join(reasons)} |")
        lines.append("")

        if self.warnings:
            lines.append("## Pipeline Warnings\n")
            for w in self.warnings:
                lines.append(f"- ⚠️ {w}")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _generate_visual_evidence_design(self) -> str:
        """Generate visual_evidence_design.md."""
        path = self.md_dir / "visual_evidence_design.md"

        content = """# Visual Evidence Design Note

## How Visual Parse Outputs Could Be Integrated into GraphRAG

### 1. As EvidenceChunk Records

Visual analysis results (detected text, diagram descriptions, flowchart steps) can be
converted to EvidenceChunk records with:

- `chunk_type = "visual"` or `"diagram"` or `"flowchart"`
- `source_path` = original workbook S3 URI
- `metadata.visual_object_id` = reference to extracted object
- `metadata.bedrock_analysis_id` = reference to Bedrock analysis
- `metadata.image_path` = path to extracted image
- `text` = structured text representation of visual content

### 2. As BusinessStep Candidates

Flowchart steps detected by Bedrock can become BusinessStep node candidates:

- Each `flowchart_steps[].label` → potential BusinessStep name
- Each `flowchart_steps[].next_steps` → NEXT_STEP edge
- Each `flowchart_steps[].condition` → BusinessRule candidate
- Confidence threshold recommended: >= 0.7

### 3. As BusinessRule Candidates

Decision points and conditions from flowcharts:

- Diamond shapes with condition text → BusinessRule candidates
- Need human verification before promotion to graph

### 4. As Implementation Graph Nodes

If systems, APIs, files, or tables are visible in diagrams:

- `diagram_nodes[].type == "system"` → System node candidate
- `diagram_nodes[].type == "api"` → API node candidate
- `diagram_nodes[].type == "file"` → File node candidate
- `diagram_nodes[].type == "table"` → Table node candidate
- `diagram_edges` → relationship candidates (CALLS, READS, WRITES, etc.)

### 5. As Manual-Review-Only Evidence

For low-confidence analysis (< 0.5):

- Store as candidate evidence only
- Flag for human review
- Do not auto-promote to graph

### Integration Recommendation

1. After human verification of this visual parse report
2. Create `visual_evidence_chunks.jsonl` from verified results
3. Add to evidence store with `parser = "bedrock_vision_v1"`
4. Link to relevant graph nodes via HAS_EVIDENCE edges
5. Re-run entity resolution to merge visual-detected entities with existing graph

### Do NOT in This Stage

- Do not auto-create graph nodes from visual analysis
- Do not modify existing graph files
- Do not reload Neptune
- Visual evidence integration requires a separate X7D or X8 stage
"""
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _generate_flowchart_report(self) -> str | None:
        """Generate focused flowchart analysis report."""
        path = self.md_dir / "flowchart_visual_analysis.md"

        # Find flowchart sheet data
        fc_sheets = [s for s in self.sheet_records if 'フローチャート' in s.get('sheet_name', '')]
        fc_objects = [o for o in self.object_records if 'フローチャート' in o.get('sheet_name', '')]
        fc_analyses = [a for a in self.analysis_records if 'フローチャート' in a.get('sheet_name', '')]

        lines = ["# Flowchart Visual Analysis (フローチャート)\n"]
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

        if not fc_sheets and not fc_objects:
            lines.append("**Status:** No フローチャート sheet visual data found.\n")
            lines.append("This may indicate:")
            lines.append("- The sheet was not linked to a drawing XML")
            lines.append("- Visual objects are in a format not detected by the extractor")
            lines.append("")

        if fc_sheets:
            for s in fc_sheets:
                lines.append(f"## Sheet: {s.get('sheet_name', '')}\n")
                lines.append(f"- Workbook: {s.get('workbook_name', '')}")
                lines.append(f"- Sheet Index: {s.get('sheet_index', 0)}")
                lines.append(f"- Has Visual Objects: {s.get('has_visual_objects', False)}")
                lines.append(f"- Object Count: {s.get('object_count', 0)}")
                lines.append(f"- Has Drawings: {s.get('has_drawings', False)}")
                lines.append("")

        if fc_objects:
            lines.append("## Extracted Visual Objects\n")
            # Textboxes
            textboxes = [o for o in fc_objects if o.get('text')]
            if textboxes:
                lines.append("### Textbox Content\n")
                for tb in textboxes:
                    lines.append(f"**{tb.get('object_name', 'unnamed')}** ({tb.get('object_type', '')}, anchor: {tb.get('anchor_from_cell', '')})")
                    lines.append(f"```\n{tb.get('text', '')}\n```\n")

            # Connectors
            connectors = [o for o in fc_objects if o.get('object_type') in ('connector', 'arrow')]
            if connectors:
                lines.append(f"### Connectors/Arrows: {len(connectors)} found\n")
                for c in connectors[:20]:
                    lines.append(f"- {c.get('object_name', '')} ({c.get('shape_type', '')}) {c.get('anchor_from_cell', '')} → {c.get('anchor_to_cell', '')}")
                lines.append("")

            # Images
            images = [o for o in fc_objects if o.get('object_type') == 'embedded_image']
            if images:
                lines.append(f"### Embedded Images: {len(images)}\n")
                for img in images:
                    lines.append(f"- {img.get('object_name', '')} → {os.path.basename(img.get('image_path', ''))}")
                lines.append("")

        if fc_analyses:
            lines.append("## Bedrock Analysis Results\n")
            for a in fc_analyses:
                lines.append(f"### Analysis of: {os.path.basename(a.get('image_path', ''))}\n")
                lines.append(f"**Confidence:** {a.get('confidence', 0):.2f}\n")
                lines.append(f"**Summary:** {a.get('summary', 'N/A')}\n")

                steps = a.get('flowchart_steps', [])
                if steps:
                    lines.append("### Possible Business Process Steps from Flowchart\n")
                    lines.append("| Step | Label | Description | Next Step | Condition | Confidence |")
                    lines.append("|-----:|-------|-------------|-----------|-----------|----------:|")
                    for step in steps:
                        next_s = ", ".join(step.get('next_steps', []))
                        lines.append(
                            f"| {step.get('step_no', '')} "
                            f"| {step.get('label', '')} "
                            f"| {step.get('description', '')[:50]} "
                            f"| {next_s} "
                            f"| {step.get('condition', '')} "
                            f"| {step.get('confidence', 0):.2f} |"
                        )
                    lines.append("")

                nodes = a.get('diagram_nodes', [])
                if nodes:
                    lines.append("### Diagram Nodes\n")
                    for n in nodes:
                        lines.append(f"- **{n.get('label', '')}** ({n.get('type', '')}) — {n.get('description', '')}")
                    lines.append("")

                edges = a.get('diagram_edges', [])
                if edges:
                    lines.append("### Diagram Edges\n")
                    for e in edges:
                        lines.append(f"- {e.get('source', '')} —[{e.get('relation', '')}]→ {e.get('target', '')}")
                    lines.append("")
        else:
            lines.append("## Bedrock Analysis\n")
            lines.append("No Bedrock analysis available for フローチャート sheet.\n")

        lines.append("## Limitations\n")
        lines.append("- Sheet-level screenshot not available (LibreOffice not installed)")
        lines.append("- Drawing XML shapes may not fully represent visual layout")
        lines.append("- Connector semantics (which textbox connects to which) require positional inference")
        lines.append("- Process step ordering is inferred from Bedrock analysis, not guaranteed correct")
        lines.append("")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _generate_overview_report(self) -> str | None:
        """Generate focused overview sheet analysis report."""
        path = self.md_dir / "overview_visual_analysis.md"

        ov_sheets = [s for s in self.sheet_records if '概要' in s.get('sheet_name', '')]
        ov_objects = [o for o in self.object_records if '概要' in o.get('sheet_name', '')]
        ov_analyses = [a for a in self.analysis_records if '概要' in a.get('sheet_name', '')]

        lines = ["# Overview Visual Analysis (概要)\n"]
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

        if ov_sheets:
            for s in ov_sheets:
                lines.append(f"## Sheet: {s.get('sheet_name', '')}\n")
                lines.append(f"- Workbook: {s.get('workbook_name', '')}")
                lines.append(f"- Has Visual Objects: {s.get('has_visual_objects', False)}")
                lines.append(f"- Object Count: {s.get('object_count', 0)}")
                lines.append("")

        if ov_objects:
            lines.append("## Extracted Objects\n")
            for obj in ov_objects:
                lines.append(f"- **{obj.get('object_name', '')}** ({obj.get('object_type', '')}) text: {obj.get('text', '')[:100]}")
            lines.append("")

        if ov_analyses:
            lines.append("## Bedrock Analysis\n")
            for a in ov_analyses:
                lines.append(f"**Summary:** {a.get('summary', 'N/A')}")
                lines.append(f"**Confidence:** {a.get('confidence', 0):.2f}\n")
                if a.get('systems'):
                    lines.append(f"**Systems:** {', '.join(a['systems'])}")
                if a.get('business_terms'):
                    lines.append(f"**Business Terms:** {', '.join(a['business_terms'])}")
                lines.append("")
        else:
            lines.append("## Bedrock Analysis\n")
            lines.append("No Bedrock analysis available for 概要 sheet.\n")

        lines.append("## Limitations\n")
        lines.append("- Sheet-level screenshot not available")
        lines.append("- Overview may contain sparse layout-only text that appears as cell data, not drawings")
        lines.append("")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return str(path)
