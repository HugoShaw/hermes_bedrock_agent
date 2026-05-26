"""
Excel Markdown Exporter — generates human-readable Markdown files from parsed Excel data.

Reconstructs all parsed Excel contents for human verification against original files.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelMarkdownExporter:
    """Export parsed Excel data as structured Markdown for human verification."""

    def __init__(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        run_id: str,
        dataset: str,
        config: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.dataset = dataset
        self.config = config or {}
        self.options = options or {}

        # Data containers
        self.workbooks: list[dict] = []
        self.sheets: list[dict] = []
        self.table_regions: list[dict] = []
        self.rows: list[dict] = []
        self.cells: list[dict] = []
        self.evidence_chunks: list[dict] = []

        # Options
        self.split_by_workbook = self.options.get("split_by_workbook", True)
        self.split_by_sheet = self.options.get("split_by_sheet", True)
        self.include_cell_samples = self.options.get("include_cell_samples", True)
        self.include_evidence_chunks = self.options.get("include_evidence_chunks", True)
        self.include_normalized_rows = self.options.get("include_normalized_rows", True)
        self.include_table_regions = self.options.get("include_table_regions", True)
        self.max_cell_text_length = self.options.get("max_cell_text_length", 1000)
        self.max_rows_per_table = self.options.get("max_rows_per_table", 0)  # 0 = all

        # Generated files tracking
        self.generated_files: list[str] = []
        self.stats: dict[str, Any] = {}

    def load_data(self):
        """Load all JSONL data files."""
        self.workbooks = self._load_jsonl("excel_workbooks.jsonl")
        self.sheets = self._load_jsonl("excel_sheets.jsonl")
        self.table_regions = self._load_jsonl("excel_table_regions.jsonl")
        self.rows = self._load_jsonl("excel_rows_normalized.jsonl")
        self.cells = self._load_jsonl("excel_cells_sample.jsonl")

        # Prefer reviewed chunks
        reviewed_path = self.input_dir / "evidence_chunks_reviewed.jsonl"
        if reviewed_path.exists():
            self.evidence_chunks = self._load_jsonl("evidence_chunks_reviewed.jsonl")
        else:
            self.evidence_chunks = self._load_jsonl("evidence_chunks.jsonl")

        self.stats = {
            "workbooks": len(self.workbooks),
            "sheets": len(self.sheets),
            "table_regions": len(self.table_regions),
            "normalized_rows": len(self.rows),
            "cell_samples": len(self.cells),
            "evidence_chunks": len(self.evidence_chunks),
        }
        logger.info(
            "Loaded: %d workbooks, %d sheets, %d regions, %d rows, %d cells, %d chunks",
            *self.stats.values()
        )

    def export_all(self) -> dict[str, Any]:
        """Run full Markdown export."""
        self.load_data()

        # Build indexes
        self._build_indexes()

        # Generate main files
        self._generate_full_markdown()
        self._generate_summary_markdown()
        self._generate_by_sheet_index()
        self._generate_quality_check()

        # Split files
        if self.split_by_workbook:
            self._generate_workbook_files()
        if self.split_by_sheet:
            self._generate_sheet_files()

        # Manifest
        self._generate_manifest()

        return {
            "generated_files": self.generated_files,
            "stats": self.stats,
        }

    def _build_indexes(self):
        """Build lookup indexes for fast access."""
        self.sheets_by_workbook: dict[str, list[dict]] = defaultdict(list)
        for s in self.sheets:
            self.sheets_by_workbook[s["workbook_id"]].append(s)
        # Sort by sheet_index
        for wid in self.sheets_by_workbook:
            self.sheets_by_workbook[wid].sort(key=lambda x: x["sheet_index"])

        self.regions_by_sheet: dict[str, list[dict]] = defaultdict(list)
        for r in self.table_regions:
            self.regions_by_sheet[r["sheet_id"]].append(r)

        self.rows_by_region: dict[str, list[dict]] = defaultdict(list)
        self.rows_by_sheet: dict[str, list[dict]] = defaultdict(list)
        for row in self.rows:
            rid = row.get("table_region_id")
            if rid:
                self.rows_by_region[rid].append(row)
            self.rows_by_sheet[row["sheet_id"]].append(row)

        self.cells_by_sheet: dict[str, list[dict]] = defaultdict(list)
        for c in self.cells:
            self.cells_by_sheet[c.get("sheet_id", "")].append(c)

        self.chunks_by_sheet: dict[str, list[dict]] = defaultdict(list)
        for ch in self.evidence_chunks:
            sid = ch.get("metadata", {}).get("sheet_id", "")
            if sid:
                self.chunks_by_sheet[sid].append(ch)

        self.workbook_map = {w["workbook_id"]: w for w in self.workbooks}

    def _generate_full_markdown(self):
        """Generate the complete full export."""
        lines: list[str] = []
        lines.append("# Excel Parsed Full Export\n")
        lines.append(self._export_metadata_section())
        lines.append("")

        for wb in self.workbooks:
            lines.append(self._workbook_section(wb, include_rows=True))

        path = self.output_dir / "excel_parsed_full.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s", path.name)

    def _generate_summary_markdown(self):
        """Generate summary-only markdown."""
        lines: list[str] = []
        lines.append("# Excel Parsed Summary\n")
        lines.append(self._export_metadata_section())
        lines.append("")

        for wb in self.workbooks:
            lines.append(self._workbook_section(wb, include_rows=False))

        path = self.output_dir / "excel_parsed_summary.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s", path.name)

    def _generate_by_sheet_index(self):
        """Generate flat index of all sheets."""
        lines: list[str] = []
        lines.append("# Excel Parsed — All Sheets by Index\n")
        lines.append(self._export_metadata_section())
        lines.append("")

        # Global sheet table
        lines.append("## Sheet Index\n")
        lines.append("| # | Workbook | Sheet Name | Rows | Cols | Cells | Type | Regions | Parsed Rows |")
        lines.append("|--:|----------|------------|-----:|-----:|------:|------|--------:|------------:|")

        global_idx = 0
        for wb in self.workbooks:
            wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
            wb_name = self._workbook_display_name(wb)
            for s in wb_sheets:
                regions = self.regions_by_sheet.get(s["sheet_id"], [])
                parsed_rows = len(self.rows_by_sheet.get(s["sheet_id"], []))
                global_idx += 1
                lines.append(
                    f"| {global_idx} | {wb_name} | {s['sheet_name']} | "
                    f"{s['max_row']} | {s['max_column']} | {s['non_empty_cell_count']} | "
                    f"{s['guessed_sheet_type']} | {len(regions)} | {parsed_rows} |"
                )

        lines.append("")
        lines.append("---\n")

        # Each sheet content
        global_idx = 0
        for wb in self.workbooks:
            wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
            for s in wb_sheets:
                global_idx += 1
                lines.append(f"## Sheet #{global_idx}: {s['sheet_name']}\n")
                lines.append(self._sheet_content(s, wb, include_rows=True))
                lines.append("\n---\n")

        path = self.output_dir / "excel_parsed_by_sheet_index.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s", path.name)

    def _generate_quality_check(self):
        """Generate quality check markdown."""
        lines: list[str] = []
        lines.append("# Excel Parsed Quality Check\n")
        lines.append(f"**Dataset:** {self.dataset}  \n")
        lines.append(f"**Run ID:** {self.run_id}  \n")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  \n")
        lines.append("")

        # 1. Completeness checklist
        lines.append("## 1. Completeness Checklist\n")
        lines.append("- [ ] All workbooks are present")
        lines.append("- [ ] All sheets are present")
        lines.append("- [ ] Sheet order matches original Excel")
        lines.append("- [ ] Sheet names match original Excel")
        lines.append("- [ ] Table regions look correct")
        lines.append("- [ ] Multi-row headers are reconstructed correctly")
        lines.append("- [ ] Merged cells are understandable")
        lines.append("- [ ] Formulas are visible where present")
        lines.append("- [ ] Comments are visible where present")
        lines.append("- [ ] Row values are not missing")
        lines.append("- [ ] Cell coordinates are preserved")
        lines.append("- [ ] Evidence chunks point to correct sheet/cell range")
        lines.append("")

        # 2. Sheet verification table
        lines.append("## 2. Sheet Verification Table\n")
        lines.append("| Workbook | Sheet Idx | Sheet Name | Rows | Cols | Parsed Rows | Regions | Warnings | Human Check |")
        lines.append("|----------|----------:|------------|-----:|-----:|------------:|--------:|----------|-------------|")

        for wb in self.workbooks:
            wb_name = self._workbook_display_name(wb)
            wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
            for s in wb_sheets:
                regions = self.regions_by_sheet.get(s["sheet_id"], [])
                parsed_rows = len(self.rows_by_sheet.get(s["sheet_id"], []))
                warnings = self._detect_sheet_warnings(s, regions, parsed_rows)
                lines.append(
                    f"| {wb_name} | {s['sheet_index']} | {s['sheet_name']} | "
                    f"{s['max_row']} | {s['max_column']} | {parsed_rows} | "
                    f"{len(regions)} | {warnings} | ☐ |"
                )
        lines.append("")

        # 3. Potential parser issues
        lines.append("## 3. Potential Parser Issues\n")
        issues = self._detect_parser_issues()
        if issues:
            for issue in issues:
                lines.append(f"- **{issue['sheet_name']}** ({issue['workbook']}): {issue['issue']}")
        else:
            lines.append("No major issues detected.")
        lines.append("")

        # 4. Sheets needing manual review
        lines.append("## 4. Sheets Needing Manual Review\n")
        review_sheets = self._identify_review_needed()
        if review_sheets:
            for rs in review_sheets:
                lines.append(f"- **{rs['sheet_name']}** — {rs['reason']}")
        else:
            lines.append("All sheets appear adequately parsed.")
        lines.append("")

        # 5. Recommended procedure
        lines.append("## 5. Recommended Human Review Procedure\n")
        lines.append("1. Open the original Excel file(s) alongside the Markdown export")
        lines.append("2. For each sheet, compare:")
        lines.append("   - Sheet name matches")
        lines.append("   - Row count is reasonable (some empty rows may be skipped)")
        lines.append("   - Column headers match")
        lines.append("   - Data values in a few sample rows match")
        lines.append("   - Merged cell context is readable")
        lines.append("3. Check table region boundaries (start row, end row, columns)")
        lines.append("4. Verify that important content is not missing")
        lines.append("5. Note any discrepancies in the Human Check column above")
        lines.append("6. For complex mapping sheets, verify SAP→中間F→Andpad field alignment")
        lines.append("")

        # 6. Evidence chunk index
        if self.include_evidence_chunks:
            lines.append("## 6. Evidence Chunk Index\n")
            lines.append("| chunk_id | workbook | sheet | chunk_type | cell_range | title |")
            lines.append("|----------|----------|-------|------------|------------|-------|")
            for ch in self.evidence_chunks:
                meta = ch.get("metadata", {})
                wb_name = meta.get("workbook_name", "")
                sheet = meta.get("sheet_name", "")
                ctype = ch.get("chunk_type", "")
                crange = meta.get("cell_range", "")
                title = ch.get("title", "")[:50]
                lines.append(f"| {ch['chunk_id'][:12]}… | {wb_name[:20]} | {sheet[:20]} | {ctype} | {crange} | {title} |")
            lines.append("")

        path = self.output_dir / "excel_parsed_quality_check.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s", path.name)

    def _generate_workbook_files(self):
        """Generate per-workbook Markdown files."""
        wb_dir = self.output_dir / "workbooks"
        wb_dir.mkdir(parents=True, exist_ok=True)
        for wb in self.workbooks:
            wb_name = self._workbook_display_name(wb)
            safe_name = self._safe_filename(wb_name)
            lines: list[str] = []
            lines.append(f"# Workbook: {wb_name}\n")
            lines.append(self._workbook_section(wb, include_rows=True))
            path = wb_dir / f"{safe_name}.md"
            path.write_text("\n".join(lines), encoding="utf-8")
            self.generated_files.append(str(path))
        logger.info("Generated %d workbook files", len(self.workbooks))

    def _generate_sheet_files(self):
        """Generate per-sheet Markdown files."""
        sheet_dir = self.output_dir / "sheets"
        sheet_dir.mkdir(parents=True, exist_ok=True)
        for wb in self.workbooks:
            wb_name = self._workbook_display_name(wb)
            safe_wb = self._safe_filename(wb_name)
            wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
            for s in wb_sheets:
                safe_sheet = self._safe_filename(s["sheet_name"])
                fname = f"{safe_wb}__{s['sheet_index']:02d}__{safe_sheet}.md"
                lines: list[str] = []
                lines.append(f"# Sheet: {s['sheet_name']}\n")
                lines.append(f"**Workbook:** {wb_name}  \n")
                lines.append(f"**Sheet Index:** {s['sheet_index']}  \n")
                lines.append("")
                lines.append(self._sheet_content(s, wb, include_rows=True))
                path = sheet_dir / fname
                path.write_text("\n".join(lines), encoding="utf-8")
                self.generated_files.append(str(path))
        logger.info("Generated %d sheet files", len(self.sheets))

    def _generate_manifest(self):
        """Generate machine-readable export manifest."""
        manifest = {
            "generated_at": datetime.now().isoformat(),
            "run_id": self.run_id,
            "dataset": self.dataset,
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "stats": self.stats,
            "generated_files": self.generated_files,
            "options": self.options,
        }
        path = self.output_dir / "markdown_export_manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        self.generated_files.append(str(path))

    # --- Section builders ---

    def _export_metadata_section(self) -> str:
        """Build export metadata header."""
        s3_uri = self.config.get("source", {}).get("s3_uri", "N/A")
        return (
            "## Export Metadata\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| Dataset | {self.dataset} |\n"
            f"| Run ID | {self.run_id} |\n"
            f"| Generated | {datetime.now().strftime('%Y-%m-%d %H:%M')} |\n"
            f"| S3 Path | {s3_uri} |\n"
            f"| Workbooks | {self.stats['workbooks']} |\n"
            f"| Sheets | {self.stats['sheets']} |\n"
            f"| Table Regions | {self.stats['table_regions']} |\n"
            f"| Normalized Rows | {self.stats['normalized_rows']} |\n"
            f"| Evidence Chunks | {self.stats['evidence_chunks']} |\n"
        )

    def _workbook_section(self, wb: dict, include_rows: bool = True) -> str:
        """Build workbook section."""
        wb_name = self._workbook_display_name(wb)
        lines: list[str] = []
        lines.append(f"## Workbook: {wb_name}\n")

        # Metadata table
        lines.append("### Workbook Metadata\n")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Workbook ID | {wb['workbook_id']} |")
        lines.append(f"| Source Path | {wb.get('source_path', '')} |")
        lines.append(f"| Extension | {wb.get('file_extension', '')} |")
        lines.append(f"| Sheet Count | {wb['sheet_count']} |")
        lines.append(f"| Visible | {wb['visible_sheet_count']} |")
        lines.append(f"| Hidden | {wb['hidden_sheet_count']} |")
        meta = wb.get("metadata", {})
        if meta.get("sheet_names"):
            lines.append(f"| Sheet Names | {', '.join(meta['sheet_names'])} |")
        lines.append("")

        # Sheet list table
        wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
        lines.append("### Sheet List\n")
        lines.append("| Idx | Sheet Name | Visible | Rows | Cols | Cells | Type | Confidence | Regions |")
        lines.append("|----:|------------|---------|-----:|-----:|------:|------|:----------:|--------:|")
        for s in wb_sheets:
            regions = self.regions_by_sheet.get(s["sheet_id"], [])
            vis = "✓" if s["visible"] else "✗"
            lines.append(
                f"| {s['sheet_index']} | {s['sheet_name']} | {vis} | "
                f"{s['max_row']} | {s['max_column']} | {s['non_empty_cell_count']} | "
                f"{s['guessed_sheet_type']} | {s['confidence']:.1f} | {len(regions)} |"
            )
        lines.append("")

        # Sheet contents
        for s in wb_sheets:
            lines.append("---\n")
            lines.append(f"### Sheet {s['sheet_index']}: {s['sheet_name']}\n")
            lines.append(self._sheet_content(s, wb, include_rows=include_rows))

        return "\n".join(lines)

    def _sheet_content(self, sheet: dict, wb: dict, include_rows: bool = True) -> str:
        """Build sheet content section."""
        lines: list[str] = []
        sid = sheet["sheet_id"]

        # Sheet metadata
        lines.append("#### Sheet Metadata\n")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Sheet ID | {sid} |")
        lines.append(f"| Max Row | {sheet['max_row']} |")
        lines.append(f"| Max Column | {sheet['max_column']} |")
        lines.append(f"| Non-empty Cells | {sheet['non_empty_cell_count']} |")
        lines.append(f"| Has Formula | {sheet['has_formula']} |")
        lines.append(f"| Has Comments | {sheet['has_comments']} |")
        lines.append(f"| Guessed Type | {sheet['guessed_sheet_type']} |")
        lines.append(f"| Confidence | {sheet['confidence']:.2f} |")
        lines.append("")

        # Merged cells
        if sheet.get("merged_cell_ranges"):
            lines.append("#### Merged Cells\n")
            lines.append("| Range |")
            lines.append("|-------|")
            for mc in sheet["merged_cell_ranges"]:
                lines.append(f"| {mc} |")
            lines.append("")

        # Table regions
        regions = self.regions_by_sheet.get(sid, [])
        if regions and self.include_table_regions:
            lines.append("#### Table Regions\n")
            for region in regions:
                lines.append(self._table_region_content(region, include_rows))
                lines.append("")

        # Cell samples (if no table regions or extra context needed)
        if self.include_cell_samples and not regions:
            cells = self.cells_by_sheet.get(sid, [])
            if cells:
                lines.append("#### Cell Samples\n")
                lines.append("| Cell | Value |")
                lines.append("|------|-------|")
                for c in cells[:50]:
                    val = str(c.get("value", ""))[:100]
                    val = val.replace("|", "\\|").replace("\n", " ")
                    lines.append(f"| {c.get('cell_ref', '')} | {val} |")
                lines.append("")

        # Evidence chunks
        if self.include_evidence_chunks:
            chunks = self.chunks_by_sheet.get(sid, [])
            if chunks:
                lines.append("#### Evidence Chunks\n")
                lines.append("| chunk_id | type | cell_range | title |")
                lines.append("|----------|------|------------|-------|")
                for ch in chunks:
                    meta = ch.get("metadata", {})
                    lines.append(
                        f"| {ch['chunk_id'][:12]}… | {ch.get('chunk_type', '')} | "
                        f"{meta.get('cell_range', '')} | {ch.get('title', '')[:40]} |"
                    )
                lines.append("")

        return "\n".join(lines)

    def _table_region_content(self, region: dict, include_rows: bool) -> str:
        """Build table region content."""
        lines: list[str] = []
        rid = region["table_region_id"]
        lines.append(f"##### Table Region: {region['cell_range']}\n")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Region ID | {rid} |")
        lines.append(f"| Cell Range | {region['cell_range']} |")
        lines.append(f"| Header Rows | {region.get('header_rows', [])} |")
        lines.append(f"| Data Start Row | {region.get('data_start_row', 'N/A')} |")
        lines.append(f"| Data End Row | {region.get('data_end_row', 'N/A')} |")
        lines.append(f"| Confidence | {region.get('confidence', 0):.2f} |")
        lines.append(f"| Region Type | {region.get('region_type', 'unknown')} |")
        lines.append(f"| Columns | {len(region.get('columns', []))} |")
        lines.append("")

        # Header reconstruction
        columns = region.get("columns", [])
        if columns:
            lines.append("**Headers:**\n")
            lines.append("| # | Column Header |")
            lines.append("|--:|---------------|")
            for i, col in enumerate(columns):
                lines.append(f"| {i+1} | {col} |")
            lines.append("")

        # Normalized rows
        if include_rows and self.include_normalized_rows:
            region_rows = self.rows_by_region.get(rid, [])
            if region_rows:
                # Sort by row_number
                region_rows_sorted = sorted(region_rows, key=lambda r: r["row_number"])

                # Limit if configured
                if self.max_rows_per_table > 0:
                    region_rows_sorted = region_rows_sorted[:self.max_rows_per_table]

                lines.append(f"**Normalized Rows ({len(region_rows)} total):**\n")

                # Decide format based on column count
                if len(columns) <= 8:
                    lines.append(self._rows_as_table(columns, region_rows_sorted))
                else:
                    lines.append(self._rows_as_details(columns, region_rows_sorted))
        lines.append("")
        return "\n".join(lines)

    def _rows_as_table(self, columns: list[str], rows: list[dict]) -> str:
        """Render rows as Markdown table (for narrow tables)."""
        lines: list[str] = []
        # Header
        col_headers = " | ".join(c[:20] for c in columns)
        lines.append(f"| Row | {col_headers} |")
        lines.append("|----:|" + "|".join(["---"] * len(columns)) + "|")

        for row in rows:
            vals = []
            for col in columns:
                v = str(row.get("normalized_values", {}).get(col, ""))
                v = v.replace("|", "\\|").replace("\n", " ")
                if len(v) > 50:
                    v = v[:47] + "…"
                vals.append(v)
            row_vals = " | ".join(vals)
            lines.append(f"| {row['row_number']} | {row_vals} |")

        return "\n".join(lines)

    def _rows_as_details(self, columns: list[str], rows: list[dict]) -> str:
        """Render rows as detail blocks (for wide tables)."""
        lines: list[str] = []
        for row in rows:
            lines.append(f"<a id=\"row-{row['row_id'][:8]}\"></a>")
            lines.append(f"**Row {row['row_number']}** (cells: {row.get('metadata', {}).get('cell_range', 'N/A')})\n")
            lines.append("| Field | Value | Cell |")
            lines.append("|-------|-------|------|")

            nv = row.get("normalized_values", {})
            refs = row.get("source_cell_refs", {})
            for col in columns:
                v = str(nv.get(col, ""))
                v = v.replace("|", "\\|").replace("\n", " ")
                if len(v) > self.max_cell_text_length:
                    v = v[:self.max_cell_text_length - 3] + "…"
                cell_ref = refs.get(col, "")
                lines.append(f"| {col[:30]} | {v[:100]} | {cell_ref} |")
            lines.append("")
        return "\n".join(lines)

    # --- Helpers ---

    def _workbook_display_name(self, wb: dict) -> str:
        """Get human-readable workbook name from source_path."""
        sp = wb.get("source_path", "")
        if sp:
            return Path(sp).name
        return wb.get("file_name", wb["workbook_id"][:12])

    def _safe_filename(self, name: str) -> str:
        """Make a filesystem-safe filename."""
        # Replace problematic chars
        safe = re.sub(r'[\\/:*?"<>|]', '_', name)
        safe = re.sub(r'\s+', '_', safe)
        # Limit length
        if len(safe) > 80:
            safe = safe[:80]
        return safe

    def _detect_sheet_warnings(self, sheet: dict, regions: list, parsed_rows: int) -> str:
        """Detect potential issues for a sheet."""
        warnings = []
        if sheet["non_empty_cell_count"] == 0:
            warnings.append("empty")
        if sheet["non_empty_cell_count"] > 0 and parsed_rows == 0 and not regions:
            warnings.append("no_table_detected")
        if sheet["confidence"] < 0.3:
            warnings.append("low_confidence")
        if sheet["max_column"] > 100:
            warnings.append("very_wide")
        if sheet.get("merged_cell_ranges"):
            warnings.append("merged_cells")
        return ", ".join(warnings) if warnings else "—"

    def _detect_parser_issues(self) -> list[dict]:
        """Detect overall parser issues."""
        issues = []
        for wb in self.workbooks:
            wb_name = self._workbook_display_name(wb)
            wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
            for s in wb_sheets:
                if s["non_empty_cell_count"] == 0:
                    issues.append({
                        "workbook": wb_name,
                        "sheet_name": s["sheet_name"],
                        "issue": "Sheet has 0 non-empty cells (may contain only charts/images)"
                    })
                elif s["non_empty_cell_count"] > 0:
                    rows = self.rows_by_sheet.get(s["sheet_id"], [])
                    regions = self.regions_by_sheet.get(s["sheet_id"], [])
                    if not rows and not regions and s["non_empty_cell_count"] > 5:
                        issues.append({
                            "workbook": wb_name,
                            "sheet_name": s["sheet_name"],
                            "issue": f"Has {s['non_empty_cell_count']} cells but no table regions/rows detected"
                        })
                if s["max_column"] > 150:
                    issues.append({
                        "workbook": wb_name,
                        "sheet_name": s["sheet_name"],
                        "issue": f"Very wide sheet ({s['max_column']} columns) — may have parsing challenges"
                    })
        return issues

    def _identify_review_needed(self) -> list[dict]:
        """Identify sheets needing manual review."""
        review = []
        for wb in self.workbooks:
            wb_sheets = self.sheets_by_workbook.get(wb["workbook_id"], [])
            for s in wb_sheets:
                reasons = []
                if s["guessed_sheet_type"] == "unknown_sheet":
                    reasons.append("unknown sheet type")
                if s["confidence"] < 0.3:
                    reasons.append("low type confidence")
                if s["non_empty_cell_count"] <= 3 and s["max_row"] > 50:
                    reasons.append("sparse content in large sheet (possible chart/image)")
                if s.get("merged_cell_ranges") and len(s.get("merged_cell_ranges", [])) > 10:
                    reasons.append("heavy merged cells")
                if reasons:
                    review.append({
                        "sheet_name": s["sheet_name"],
                        "reason": "; ".join(reasons),
                    })
        return review

    def _load_jsonl(self, filename: str) -> list[dict]:
        """Load a JSONL file."""
        path = self.input_dir / filename
        if not path.exists():
            logger.warning("File not found: %s", path)
            return []
        records = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON line in %s", filename)
        return records
