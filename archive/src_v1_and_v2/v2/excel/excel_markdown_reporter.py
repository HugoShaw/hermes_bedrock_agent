"""
Excel Markdown Reporter — generates export summary report.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelMarkdownReporter:
    """Generate the markdown_export_report.md summarizing the export."""

    def __init__(
        self,
        stats: dict[str, Any],
        generated_files: list[str],
        output_dir: str | Path,
        run_id: str = "",
        dataset: str = "",
        warnings: list[str] | None = None,
    ):
        self.stats = stats
        self.generated_files = generated_files
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.dataset = dataset
        self.warnings = warnings or []

    def generate_report(self) -> str:
        """Generate and write the report."""
        sheet_files = [f for f in self.generated_files if "/sheets/" in f]
        wb_files = [f for f in self.generated_files if "/workbooks/" in f]

        report = f"""# Markdown Export Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Run ID:** {self.run_id}
**Dataset:** {self.dataset}
**Status:** Done

---

## Statistics

| Metric | Value |
|--------|-------|
| Workbooks exported | {self.stats.get('workbooks', 0)} |
| Sheets exported | {self.stats.get('sheets', 0)} |
| Table regions exported | {self.stats.get('table_regions', 0)} |
| Normalized rows exported | {self.stats.get('normalized_rows', 0)} |
| Evidence chunks exported | {self.stats.get('evidence_chunks', 0)} |
| Cell samples included | {self.stats.get('cell_samples', 0)} |
| Sheet Markdown files | {len(sheet_files)} |
| Workbook Markdown files | {len(wb_files)} |
| Total generated files | {len(self.generated_files)} |

---

## Generated Files

### Main Files

"""
        main_files = [f for f in self.generated_files
                      if "/sheets/" not in f and "/workbooks/" not in f]
        for f in sorted(main_files):
            report += f"- `{f}`\n"

        if wb_files:
            report += "\n### Workbook Files\n\n"
            for f in sorted(wb_files):
                report += f"- `{f}`\n"

        if sheet_files:
            report += f"\n### Sheet Files ({len(sheet_files)} files)\n\n"
            for f in sorted(sheet_files):
                report += f"- `{f}`\n"

        if self.warnings:
            report += "\n---\n\n## Warnings\n\n"
            for w in self.warnings:
                report += f"- {w}\n"

        report += """
---

## Verification Instructions

1. Download original Excel files from S3
2. Open `excel_parsed_full.md` or individual sheet files
3. Compare sheet by sheet:
   - Sheet names and order
   - Table boundaries
   - Header reconstruction
   - Row values (sample a few rows per sheet)
   - Merged cell handling
4. Check `excel_parsed_quality_check.md` for known issues
5. Mark verified sheets in the checklist

---

## Next Recommended Action

After human verification completes:
- If all content verified → proceed to X8 (QA or refinement)
- If parser issues found → create targeted fixes before proceeding
"""
        path = self.output_dir / "markdown_export_report.md"
        path.write_text(report, encoding="utf-8")
        logger.info("Generated: %s", path)
        return report
