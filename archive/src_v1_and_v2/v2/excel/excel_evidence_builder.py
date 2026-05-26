"""
Excel evidence builder — convert Excel structures into V2 EvidenceChunk records.

Chunk mapping:
- Workbook summary → chunk_type = summary
- Sheet summary → chunk_type = section
- Table region → chunk_type = table
- Normalized row → chunk_type = table or small
- Config-like sheet → chunk_type = config
- Test-like sheet → chunk_type = testcase
- API-like sheet → chunk_type = api
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from hermes_bedrock_agent.v2.schemas.evidence_schema import EvidenceChunk
from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord
from hermes_bedrock_agent.v2.excel.excel_schema import (
    ExcelWorkbookRecord,
    ExcelSheetRecord,
    ExcelTableRegion,
    ExcelRowRecord,
)

logger = logging.getLogger(__name__)

# Mapping from sheet type to default chunk type for rows
SHEET_TYPE_TO_CHUNK_TYPE: dict[str, str] = {
    "field_mapping_sheet": "table",
    "api_interface_sheet": "api",
    "data_dictionary_sheet": "table",
    "business_process_sheet": "table",
    "code_master_sheet": "table",
    "business_rule_sheet": "table",
    "test_case_sheet": "testcase",
    "screen_definition_sheet": "table",
    "system_config_sheet": "config",
    "operation_sheet": "operation",
    "unknown_sheet": "table",
}

# Max text length for a single evidence chunk
MAX_CHUNK_TEXT_LENGTH = 3000


class ExcelEvidenceBuilder:
    """Build V2 EvidenceChunk records from Excel profiling results.

    Parameters
    ----------
    dataset : str
        Dataset name.
    run_id : str
        Run identifier.
    project : str
        Project name.
    max_rows_per_chunk : int
        Maximum rows to combine into a single table chunk.
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
        project: str = "sample_20260519",
        max_rows_per_chunk: int = 10,
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.project = project
        self.max_rows_per_chunk = max_rows_per_chunk

    def build_workbook_summary_chunk(
        self,
        wb_record: ExcelWorkbookRecord,
        sheet_records: list[ExcelSheetRecord],
        document_id: str,
    ) -> EvidenceChunk:
        """Create a summary evidence chunk for the entire workbook."""
        sheet_info_lines = []
        for sr in sheet_records:
            vis = "visible" if sr.visible else "hidden"
            sheet_info_lines.append(
                f"  - {sr.sheet_name} ({vis}, {sr.max_row}行x{sr.max_column}列, "
                f"type={sr.guessed_sheet_type}, confidence={sr.confidence})"
            )

        text = (
            f"Workbook: {wb_record.file_name}\n"
            f"Extension: {wb_record.file_extension}\n"
            f"Source: {wb_record.source_path}\n"
            f"Sheet count: {wb_record.sheet_count} "
            f"(visible={wb_record.visible_sheet_count}, hidden={wb_record.hidden_sheet_count})\n"
            f"Sheets:\n" + "\n".join(sheet_info_lines)
        )

        chunk_id = EvidenceChunk.generate_id(
            document_id=document_id,
            section_id=None,
            chunk_index=0,
            content_hash=EvidenceChunk.content_hash(text),
        )

        return EvidenceChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            section_id=None,
            project=self.project,
            dataset=self.dataset,
            run_id=self.run_id,
            doc_type="business_doc",
            chunk_type="summary",
            title=f"Workbook Summary: {wb_record.file_name}",
            text=text,
            heading_path=[wb_record.file_name],
            source_path=wb_record.source_path,
            language="ja",
            metadata={
                "workbook_id": wb_record.workbook_id,
                "workbook_name": wb_record.file_name,
                "parser": "excel_v2",
                "s3_uri": wb_record.source_path,
            },
        )

    def build_sheet_summary_chunk(
        self,
        sheet_record: ExcelSheetRecord,
        wb_record: ExcelWorkbookRecord,
        regions: list[ExcelTableRegion],
        document_id: str,
        section_id: str,
    ) -> EvidenceChunk:
        """Create a section-level evidence chunk summarizing a sheet."""
        region_info = []
        for r in regions:
            region_info.append(
                f"  - Region {r.cell_range}: {len(r.columns)} columns, "
                f"rows {r.data_start_row}-{r.data_end_row}, type={r.region_type}"
            )

        text = (
            f"Workbook: {wb_record.file_name}\n"
            f"Sheet: {sheet_record.sheet_name}\n"
            f"Sheet index: {sheet_record.sheet_index}\n"
            f"Size: {sheet_record.max_row}行 x {sheet_record.max_column}列\n"
            f"Non-empty cells: {sheet_record.non_empty_cell_count}\n"
            f"Merged cells: {len(sheet_record.merged_cell_ranges)}\n"
            f"Has formula: {sheet_record.has_formula}\n"
            f"Has comments: {sheet_record.has_comments}\n"
            f"Guessed type: {sheet_record.guessed_sheet_type} (confidence={sheet_record.confidence})\n"
            f"Table regions: {len(regions)}\n"
        )
        if region_info:
            text += "Regions:\n" + "\n".join(region_info)

        chunk_id = EvidenceChunk.generate_id(
            document_id=document_id,
            section_id=section_id,
            chunk_index=0,
            content_hash=EvidenceChunk.content_hash(text),
        )

        return EvidenceChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            section_id=section_id,
            project=self.project,
            dataset=self.dataset,
            run_id=self.run_id,
            doc_type="business_doc",
            chunk_type="section",
            title=f"Sheet: {sheet_record.sheet_name}",
            text=text,
            heading_path=[wb_record.file_name, sheet_record.sheet_name],
            source_path=wb_record.source_path,
            language="ja",
            metadata={
                "workbook_id": wb_record.workbook_id,
                "workbook_name": wb_record.file_name,
                "sheet_id": sheet_record.sheet_id,
                "sheet_name": sheet_record.sheet_name,
                "sheet_index": sheet_record.sheet_index,
                "guessed_sheet_type": sheet_record.guessed_sheet_type,
                "parser": "excel_v2",
                "s3_uri": wb_record.source_path,
            },
        )

    def build_row_chunks(
        self,
        rows: list[ExcelRowRecord],
        region: ExcelTableRegion,
        wb_record: ExcelWorkbookRecord,
        sheet_record: ExcelSheetRecord,
        document_id: str,
        section_id: str,
    ) -> list[EvidenceChunk]:
        """Convert normalized rows into evidence chunks.

        Groups rows into batches of max_rows_per_chunk.
        """
        if not rows:
            return []

        # Determine chunk type from sheet type
        chunk_type = SHEET_TYPE_TO_CHUNK_TYPE.get(
            sheet_record.guessed_sheet_type, "table"
        )

        chunks: list[EvidenceChunk] = []
        batch: list[ExcelRowRecord] = []
        chunk_index = 0

        for row in rows:
            batch.append(row)
            if len(batch) >= self.max_rows_per_chunk:
                chunk = self._build_batch_chunk(
                    batch=batch,
                    region=region,
                    wb_record=wb_record,
                    sheet_record=sheet_record,
                    document_id=document_id,
                    section_id=section_id,
                    chunk_type=chunk_type,
                    chunk_index=chunk_index,
                )
                if chunk:
                    chunks.append(chunk)
                batch = []
                chunk_index += 1

        # Final batch
        if batch:
            chunk = self._build_batch_chunk(
                batch=batch,
                region=region,
                wb_record=wb_record,
                sheet_record=sheet_record,
                document_id=document_id,
                section_id=section_id,
                chunk_type=chunk_type,
                chunk_index=chunk_index,
            )
            if chunk:
                chunks.append(chunk)

        return chunks

    def _build_batch_chunk(
        self,
        batch: list[ExcelRowRecord],
        region: ExcelTableRegion,
        wb_record: ExcelWorkbookRecord,
        sheet_record: ExcelSheetRecord,
        document_id: str,
        section_id: str,
        chunk_type: str,
        chunk_index: int,
    ) -> EvidenceChunk | None:
        """Build a single evidence chunk from a batch of rows."""
        # Build human-readable text
        lines = [
            f"Workbook: {wb_record.file_name}",
            f"Sheet: {sheet_record.sheet_name}",
            f"Region: {region.cell_range}",
            f"Rows: {batch[0].row_number}-{batch[-1].row_number}",
            "",
        ]

        for row in batch:
            row_parts = []
            for col_name, val in row.normalized_values.items():
                if val:
                    row_parts.append(f"{col_name}: {val}")
            if row_parts:
                row_text = f"Row {row.row_number}: " + " | ".join(row_parts)
                lines.append(row_text)

        text = "\n".join(lines)

        # Truncate if too long
        if len(text) > MAX_CHUNK_TEXT_LENGTH:
            text = text[:MAX_CHUNK_TEXT_LENGTH] + "\n... (truncated)"

        # Don't create empty chunks
        if not text.strip() or len(text.strip()) < 10:
            return None

        chunk_id = EvidenceChunk.generate_id(
            document_id=document_id,
            section_id=section_id,
            chunk_index=chunk_index + 100,  # Offset to avoid collision with summary chunks
            content_hash=EvidenceChunk.content_hash(text),
        )

        return EvidenceChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            section_id=section_id,
            project=self.project,
            dataset=self.dataset,
            run_id=self.run_id,
            doc_type="business_doc",
            chunk_type=chunk_type,
            title=f"{sheet_record.sheet_name} [{region.cell_range}] rows {batch[0].row_number}-{batch[-1].row_number}",
            text=text,
            heading_path=[wb_record.file_name, sheet_record.sheet_name, region.cell_range],
            source_path=wb_record.source_path,
            language="ja",
            metadata={
                "workbook_id": wb_record.workbook_id,
                "workbook_name": wb_record.file_name,
                "sheet_id": sheet_record.sheet_id,
                "sheet_name": sheet_record.sheet_name,
                "sheet_index": sheet_record.sheet_index,
                "guessed_sheet_type": sheet_record.guessed_sheet_type,
                "table_region_id": region.table_region_id,
                "cell_range": region.cell_range,
                "row_numbers": [r.row_number for r in batch],
                "columns": region.columns,
                "has_formula": sheet_record.has_formula,
                "has_comment": sheet_record.has_comments,
                "parser": "excel_v2",
                "s3_uri": wb_record.source_path,
            },
        )
