"""
Excel reporter — generate profiling and evidence design reports.

Outputs:
- excel_profile_report.md: Full workbook/sheet/region analysis
- excel_evidence_design.md: Evidence extraction strategy and chunk mappings
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_schema import (
    ExcelWorkbookRecord,
    ExcelSheetRecord,
    ExcelTableRegion,
    ExcelRowRecord,
)
from hermes_bedrock_agent.v2.schemas.evidence_schema import EvidenceChunk

logger = logging.getLogger(__name__)


class ExcelReporter:
    """Generate reports for Excel profiling results."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_profile_report(
        self,
        workbooks: list[ExcelWorkbookRecord],
        sheets: list[ExcelSheetRecord],
        regions: list[ExcelTableRegion],
        rows: list[ExcelRowRecord],
        chunks: list[EvidenceChunk],
        discovery: dict[str, Any] | None = None,
    ) -> str:
        """Write the excel_profile_report.md."""
        lines = [
            "# Excel Profile Report",
            "",
            f"**Dataset:** sample_20260519",
            f"**Run ID:** sample_20260519_excel_v1",
            "",
        ]

        if discovery:
            lines.extend([
                "## S3 Discovery",
                "",
                f"- S3 URI: s3://s3-hulftchina-rd/サンプル20260519/",
                f"- Total files: {discovery.get('total_count', 0)}",
                f"- Excel files: {discovery.get('excel_count', 0)}",
                f"- Non-Excel files: {len(discovery.get('non_excel_files', []))}",
                "",
            ])
            if discovery.get("error"):
                lines.extend([f"- **Error:** {discovery['error']}", ""])

        # Workbook summary
        lines.extend([
            "## Workbooks",
            "",
            f"- Total workbooks profiled: {len(workbooks)}",
            "",
        ])

        for wb in workbooks:
            lines.extend([
                f"### {wb.file_name}",
                "",
                f"- Source: {wb.source_path}",
                f"- Extension: {wb.file_extension}",
                f"- Sheets: {wb.sheet_count} (visible={wb.visible_sheet_count}, hidden={wb.hidden_sheet_count})",
                "",
            ])

        # Sheet summary
        lines.extend([
            "## Sheets",
            "",
            "| # | Workbook | Sheet Name | Visible | Rows | Cols | Non-Empty | Merged | Formula | Comments | Type | Confidence |",
            "|---|----------|-----------|---------|------|------|-----------|--------|---------|----------|------|------------|",
        ])
        for i, sh in enumerate(sheets, 1):
            wb_name = next((w.file_name for w in workbooks if w.workbook_id == sh.workbook_id), "?")
            lines.append(
                f"| {i} | {wb_name} | {sh.sheet_name} | {'✓' if sh.visible else '✗'} | "
                f"{sh.max_row} | {sh.max_column} | {sh.non_empty_cell_count} | "
                f"{len(sh.merged_cell_ranges)} | {'✓' if sh.has_formula else '✗'} | "
                f"{'✓' if sh.has_comments else '✗'} | {sh.guessed_sheet_type} | {sh.confidence} |"
            )
        lines.append("")

        # Table regions
        lines.extend([
            "## Table Regions",
            "",
            f"- Total regions detected: {len(regions)}",
            "",
            "| # | Sheet | Cell Range | Header Rows | Data Rows | Columns | Type | Confidence |",
            "|---|-------|-----------|-------------|-----------|---------|------|------------|",
        ])
        for i, r in enumerate(regions, 1):
            data_rows = (r.data_end_row - r.data_start_row + 1) if r.data_start_row and r.data_end_row else 0
            lines.append(
                f"| {i} | {r.sheet_name} | {r.cell_range} | {r.header_rows} | "
                f"{data_rows} | {len(r.columns)} | {r.region_type} | {r.confidence} |"
            )
        lines.append("")

        # Row records
        lines.extend([
            "## Normalized Rows",
            "",
            f"- Total normalized rows: {len(rows)}",
            "",
        ])

        # Evidence chunks
        lines.extend([
            "## Evidence Chunks",
            "",
            f"- Total evidence chunks generated: {len(chunks)}",
            "",
        ])
        if chunks:
            type_counts: dict[str, int] = {}
            for c in chunks:
                type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1
            lines.append("| Chunk Type | Count |")
            lines.append("|-----------|-------|")
            for ct, count in sorted(type_counts.items()):
                lines.append(f"| {ct} | {count} |")
            lines.append("")

        # Parser limitations
        lines.extend([
            "## Parser Limitations",
            "",
            "- `.xls` (legacy format): Not supported by openpyxl. Requires xlrd or conversion.",
            "- Formula evaluation: Formulas are preserved as strings, not evaluated.",
            "- Chart/image data: Not extracted (openpyxl does not expose chart data directly).",
            "- Pivot tables: Not specially handled (appear as regular cell values).",
            "- VBA macros: Not extracted from .xlsm files.",
            "- Large workbooks (>10K rows): Scanned up to 1000 rows per sheet.",
            "",
        ])

        # Next steps
        lines.extend([
            "## Recommended Next Stage",
            "",
            "1. Review evidence chunks for quality and completeness",
            "2. Tune sheet type inference keywords for this dataset",
            "3. Consider multi-row header edge cases",
            "4. Build vector evidence store from generated chunks",
            "5. Extract business semantic graph from field mapping / interface sheets",
            "6. Extract implementation graph from API/DB/config sheets",
            "",
        ])

        report_path = str(self.output_dir / "excel_profile_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("Wrote profile report to %s", report_path)
        return report_path

    def write_evidence_design_report(
        self,
        workbooks: list[ExcelWorkbookRecord],
        sheets: list[ExcelSheetRecord],
        regions: list[ExcelTableRegion],
        chunks: list[EvidenceChunk],
    ) -> str:
        """Write the excel_evidence_design.md."""
        lines = [
            "# Excel Evidence Design Report",
            "",
            "## Overview",
            "",
            "This document describes the evidence extraction strategy for Excel workbooks.",
            "",
            "## Architecture",
            "",
            "```",
            "Excel Workbook",
            "  └── Sheet (ExcelSheetRecord)",
            "        └── Table Region (ExcelTableRegion)",
            "              ├── Header Rows → column names",
            "              └── Data Rows → ExcelRowRecord → EvidenceChunk",
            "```",
            "",
            "## Chunk Mapping Strategy",
            "",
            "| Source | Chunk Type | Granularity |",
            "|--------|-----------|-------------|",
            "| Workbook metadata | summary | 1 per workbook |",
            "| Sheet metadata | section | 1 per sheet |",
            "| Table region rows | table / api / config / testcase | N rows per chunk (batch) |",
            "",
            "## Sheet Type → Chunk Type Mapping",
            "",
            "| Sheet Type | Default Chunk Type |",
            "|-----------|-------------------|",
            "| field_mapping_sheet | table |",
            "| api_interface_sheet | api |",
            "| data_dictionary_sheet | table |",
            "| business_process_sheet | table |",
            "| code_master_sheet | table |",
            "| business_rule_sheet | table |",
            "| test_case_sheet | testcase |",
            "| screen_definition_sheet | table |",
            "| system_config_sheet | config |",
            "| operation_sheet | operation |",
            "| unknown_sheet | table |",
            "",
            "## Evidence Text Format",
            "",
            "Each evidence chunk contains human-readable text:",
            "",
            "```",
            "Workbook: xxx.xlsx",
            "Sheet: IFマッピング",
            "Region: B3:H42",
            "Rows: 12-21",
            "",
            "Row 12: 項目名: ... | 型: ... | 桁数: ... | 説明: ...",
            "Row 13: 項目名: ... | 型: ... | 桁数: ... | 説明: ...",
            "...",
            "```",
            "",
            "## Evidence Metadata",
            "",
            "Each chunk metadata includes:",
            "- workbook_id, workbook_name",
            "- sheet_id, sheet_name, sheet_index",
            "- guessed_sheet_type",
            "- table_region_id, cell_range",
            "- row_numbers, columns",
            "- has_formula, has_comment",
            "- parser = excel_v2",
            "- s3_uri",
            "",
            "## Traceability",
            "",
            "- Every chunk links back to source workbook + sheet + cell range",
            "- Cell references (e.g. B12, C12) preserved in row records",
            "- Merged cell parent references preserved",
            "- Evidence can be cited with exact workbook/sheet/cell location",
            "",
            "## Quality Considerations",
            "",
            "- Empty rows are skipped (no empty chunks generated)",
            "- Chunk text capped at 3000 chars to prevent oversized chunks",
            "- Sheet type inference is heuristic — may require tuning per dataset",
            "- Multi-row headers joined with '/' separator",
            "- Duplicate column names get _2, _3 suffixes",
            "",
        ]

        # Dataset-specific notes
        lines.extend([
            "## Dataset-Specific Notes",
            "",
            f"- Workbooks profiled: {len(workbooks)}",
            f"- Sheets profiled: {len(sheets)}",
            f"- Table regions detected: {len(regions)}",
            f"- Evidence chunks generated: {len(chunks)}",
            "",
        ])

        if sheets:
            lines.extend([
                "### Sheet Types Found",
                "",
            ])
            type_counts: dict[str, int] = {}
            for sh in sheets:
                type_counts[sh.guessed_sheet_type] = type_counts.get(sh.guessed_sheet_type, 0) + 1
            for st, count in sorted(type_counts.items()):
                lines.append(f"- {st}: {count} sheets")
            lines.append("")

        report_path = str(self.output_dir / "excel_evidence_design.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("Wrote evidence design report to %s", report_path)
        return report_path
