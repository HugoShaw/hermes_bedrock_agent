"""
Excel sample exporter — export human-readable samples for manual review.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelSampleExporter:
    """Export human-readable evidence samples for review.

    Parameters
    ----------
    chunks_path : Path
        Path to evidence_chunks.jsonl.
    sheets_path : Path
        Path to excel_sheets.jsonl.
    regions_path : Path
        Path to excel_table_regions.jsonl.
    rows_path : Path
        Path to excel_rows_normalized.jsonl.
    quality_records : list[dict]
        Quality records from ExcelEvidenceQualityReviewer.
    sample_size : int
        Number of samples per category.
    """

    def __init__(
        self,
        chunks_path: Path,
        sheets_path: Path,
        regions_path: Path,
        rows_path: Path,
        quality_records: list[dict] | None = None,
        sample_size: int = 30,
    ) -> None:
        self.chunks_path = Path(chunks_path)
        self.sheets_path = Path(sheets_path)
        self.regions_path = Path(regions_path)
        self.rows_path = Path(rows_path)
        self.quality_records = quality_records or []
        self.sample_size = sample_size
        self._chunks: list[dict] = []
        self._sheets: list[dict] = []
        self._regions: list[dict] = []
        self._rows: list[dict] = []

    def load_data(self) -> None:
        """Load input data."""
        self._chunks = [
            json.loads(line) for line in self.chunks_path.read_text().strip().split("\n") if line.strip()
        ]
        self._sheets = [
            json.loads(line) for line in self.sheets_path.read_text().strip().split("\n") if line.strip()
        ]
        self._regions = [
            json.loads(line) for line in self.regions_path.read_text().strip().split("\n") if line.strip()
        ]
        # Load limited rows for sampling
        rows = []
        with open(self.rows_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 200:  # Only load first 200 for sampling
                    break
                if line.strip():
                    rows.append(json.loads(line))
        self._rows = rows
        logger.info(f"Loaded data for sample export")

    def export_all(self, output_dir: Path) -> list[str]:
        """Export all sample files. Returns list of created paths."""
        if not self._chunks:
            self.load_data()

        output_dir = Path(output_dir) / "review_samples"
        output_dir.mkdir(parents=True, exist_ok=True)

        files_created = []

        # 1. Evidence chunk samples
        path = output_dir / "evidence_chunk_samples.md"
        self._export_evidence_chunk_samples(path)
        files_created.append(str(path))

        # 2. Table region samples
        path = output_dir / "table_region_samples.md"
        self._export_table_region_samples(path)
        files_created.append(str(path))

        # 3. Row normalization samples
        path = output_dir / "row_normalization_samples.md"
        self._export_row_normalization_samples(path)
        files_created.append(str(path))

        # 4. Sheet type samples
        path = output_dir / "sheet_type_samples.md"
        self._export_sheet_type_samples(path)
        files_created.append(str(path))

        logger.info(f"Exported {len(files_created)} sample files to {output_dir}")
        return files_created

    def _export_evidence_chunk_samples(self, path: Path) -> None:
        """Export evidence chunk samples."""
        # Build quality lookup
        quality_lookup = {r["chunk_id"]: r for r in self.quality_records} if self.quality_records else {}

        # Collect samples: at least 3 from each chunk_type, high and low quality
        by_type: dict[str, list[dict]] = {}
        for c in self._chunks:
            by_type.setdefault(c["chunk_type"], []).append(c)

        lines = [
            "# Evidence Chunk Samples\n",
            f"**Total chunks:** {len(self._chunks)}",
            f"**Sample size:** {self.sample_size}\n",
            "---\n",
        ]

        sample_count = 0
        for chunk_type, chunks in sorted(by_type.items()):
            lines.append(f"## Chunk Type: `{chunk_type}` ({len(chunks)} total)\n")

            # Get a mix: first 3 + any low-quality ones
            samples = chunks[:min(5, len(chunks))]

            for chunk in samples:
                if sample_count >= self.sample_size:
                    break
                sample_count += 1
                q = quality_lookup.get(chunk["chunk_id"], {})
                meta = chunk.get("metadata", {})

                lines.append(f"### Sample {sample_count}: {chunk['title'][:80]}\n")
                lines.append(f"- **chunk_id:** `{chunk['chunk_id']}`")
                lines.append(f"- **workbook:** {meta.get('workbook_name', 'N/A')}")
                lines.append(f"- **sheet:** {meta.get('sheet_name', 'N/A')}")
                lines.append(f"- **sheet_type:** {meta.get('guessed_sheet_type', 'N/A')}")
                lines.append(f"- **cell_range:** {meta.get('cell_range', 'N/A')}")
                lines.append(f"- **chunk_type:** {chunk['chunk_type']}")
                lines.append(f"- **text_length:** {len(chunk['text'])} chars")
                if q:
                    lines.append(f"- **quality_score:** {q.get('quality_score', 'N/A')}")
                    lines.append(f"- **flags:** {q.get('flags', [])}")
                lines.append(f"\n**Text Preview:**\n")
                lines.append("```")
                lines.append(chunk["text"][:600])
                if len(chunk["text"]) > 600:
                    lines.append(f"\n... ({len(chunk['text']) - 600} more chars)")
                lines.append("```\n")
                lines.append("---\n")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _export_table_region_samples(self, path: Path) -> None:
        """Export table region samples."""
        lines = [
            "# Table Region Samples\n",
            f"**Total regions:** {len(self._regions)}\n",
            "---\n",
        ]

        # Show up to 10 diverse regions
        by_type: dict[str, list[dict]] = {}
        for r in self._regions:
            by_type.setdefault(r.get("region_type", "unknown"), []).append(r)

        sample_count = 0
        for region_type, regions in sorted(by_type.items()):
            lines.append(f"## Region Type: `{region_type}` ({len(regions)} total)\n")

            for region in regions[:3]:
                sample_count += 1
                lines.append(f"### Sample {sample_count}: {region.get('sheet_name', 'N/A')} [{region.get('cell_range', '')}]\n")
                lines.append(f"- **table_region_id:** `{region.get('table_region_id', 'N/A')}`")
                lines.append(f"- **workbook_id:** `{region.get('workbook_id', 'N/A')}`")
                lines.append(f"- **sheet_name:** {region.get('sheet_name', 'N/A')}")
                lines.append(f"- **cell_range:** {region.get('cell_range', 'N/A')}")
                lines.append(f"- **header_rows:** {region.get('header_rows', [])}")
                lines.append(f"- **data_start_row:** {region.get('data_start_row', 'N/A')}")
                lines.append(f"- **data_end_row:** {region.get('data_end_row', 'N/A')}")
                lines.append(f"- **columns:** {region.get('columns', [])[:10]}{'...' if len(region.get('columns', [])) > 10 else ''}")
                lines.append(f"- **confidence:** {region.get('confidence', 0.0)}")
                lines.append(f"- **region_type:** {region.get('region_type', 'N/A')}")
                lines.append("\n---\n")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _export_row_normalization_samples(self, path: Path) -> None:
        """Export row normalization samples."""
        lines = [
            "# Row Normalization Samples\n",
            f"**Total rows loaded for sampling:** {len(self._rows)}\n",
            "---\n",
        ]

        # Get diverse samples from different sheets
        by_sheet: dict[str, list[dict]] = {}
        for r in self._rows:
            by_sheet.setdefault(r.get("sheet_name", ""), []).append(r)

        sample_count = 0
        for sheet_name, rows in sorted(by_sheet.items())[:5]:
            lines.append(f"## Sheet: {sheet_name} ({len(rows)} rows sampled)\n")

            for row in rows[:3]:
                sample_count += 1
                lines.append(f"### Row {sample_count} (row_number={row.get('row_number', '?')})\n")
                lines.append(f"- **row_id:** `{row.get('row_id', 'N/A')}`")
                lines.append(f"- **sheet_name:** {row.get('sheet_name', 'N/A')}")
                lines.append(f"- **table_region_id:** `{row.get('table_region_id', 'N/A')}`")

                values = row.get("values", {})
                if values:
                    lines.append(f"- **columns ({len(values)}):**")
                    for k, v in list(values.items())[:8]:
                        v_str = str(v)[:80] if v else "(empty)"
                        lines.append(f"  - `{k}`: {v_str}")
                    if len(values) > 8:
                        lines.append(f"  - ... ({len(values) - 8} more columns)")

                refs = row.get("source_cell_refs", {})
                if refs:
                    lines.append(f"- **cell_refs ({len(refs)}):** {list(refs.items())[:5]}")

                lines.append("\n---\n")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _export_sheet_type_samples(self, path: Path) -> None:
        """Export sheet type classification samples."""
        lines = [
            "# Sheet Type Classification Samples\n",
            f"**Total sheets:** {len(self._sheets)}\n",
            "---\n",
        ]

        by_type: dict[str, list[dict]] = {}
        for s in self._sheets:
            by_type.setdefault(s.get("guessed_sheet_type", "unknown_sheet"), []).append(s)

        for sheet_type, sheets in sorted(by_type.items()):
            lines.append(f"## Type: `{sheet_type}` ({len(sheets)} sheets)\n")

            for sheet in sheets[:3]:
                lines.append(f"### {sheet.get('sheet_name', 'N/A')}\n")
                lines.append(f"- **sheet_id:** `{sheet.get('sheet_id', 'N/A')}`")
                lines.append(f"- **workbook_id:** `{sheet.get('workbook_id', 'N/A')}`")
                lines.append(f"- **visible:** {sheet.get('visible', True)}")
                lines.append(f"- **max_row:** {sheet.get('max_row', 0)}")
                lines.append(f"- **max_column:** {sheet.get('max_column', 0)}")
                lines.append(f"- **non_empty_cell_count:** {sheet.get('non_empty_cell_count', 0)}")
                lines.append(f"- **merged_cell_ranges:** {len(sheet.get('merged_cell_ranges', []))}")
                lines.append(f"- **has_formula:** {sheet.get('has_formula', False)}")
                lines.append(f"- **has_comments:** {sheet.get('has_comments', False)}")
                lines.append(f"- **confidence:** {sheet.get('confidence', 0.0)}")
                lines.append("\n---\n")

        path.write_text("\n".join(lines), encoding="utf-8")
