"""
Profile Excel workbook pipeline — orchestrates the full Excel profiling workflow.

Stages:
1. S3 discovery (list Excel files)
2. Download and load workbooks
3. Profile each sheet
4. Detect table regions
5. Normalize rows
6. Build evidence chunks
7. Generate reports
8. Write JSONL outputs
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_schema import (
    ExcelWorkbookRecord,
    ExcelSheetRecord,
    ExcelTableRegion,
    ExcelRowRecord,
    ExcelCellEvidence,
)
from hermes_bedrock_agent.v2.excel.s3_excel_discovery import S3ExcelDiscovery
from hermes_bedrock_agent.v2.excel.workbook_loader import WorkbookLoader
from hermes_bedrock_agent.v2.excel.sheet_profiler import SheetProfiler
from hermes_bedrock_agent.v2.excel.table_region_detector import TableRegionDetector
from hermes_bedrock_agent.v2.excel.row_normalizer import RowNormalizer
from hermes_bedrock_agent.v2.excel.excel_evidence_builder import ExcelEvidenceBuilder
from hermes_bedrock_agent.v2.excel.excel_reporter import ExcelReporter
from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord
from hermes_bedrock_agent.v2.schemas.evidence_schema import EvidenceChunk

logger = logging.getLogger(__name__)


class ProfileExcelWorkbookPipeline:
    """Orchestrate the full Excel workbook profiling pipeline.

    Parameters
    ----------
    config : dict
        Configuration dictionary (parsed from YAML).
    output_dir : str
        Output directory path.
    dataset : str
        Dataset name.
    run_id : str
        Run identifier.
    """

    def __init__(
        self,
        config: dict[str, Any],
        output_dir: str,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.config = config
        self.output_dir = Path(output_dir)
        self.dataset = dataset
        self.run_id = run_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Excel config
        excel_config = config.get("excel", {})
        self.sample_cells = excel_config.get("sample_non_empty_cells", 200)
        self.max_cell_text_length = excel_config.get("max_cell_text_length", 500)
        self.include_hidden = excel_config.get("include_hidden_sheets", False)

    def run_s3(
        self,
        s3_uri: str | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline from S3 discovery.

        Parameters
        ----------
        s3_uri : str or None
            S3 URI override. If None, uses config source.s3_uri.

        Returns
        -------
        dict with pipeline results.
        """
        # Parse S3 URI
        if s3_uri is None:
            source_config = self.config.get("source", {})
            s3_uri = source_config.get("s3_uri", "")

        if not s3_uri:
            raise ValueError("No S3 URI provided in config or arguments")

        # Parse bucket and prefix from URI
        if s3_uri.startswith("s3://"):
            parts = s3_uri[5:].split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
        else:
            source_config = self.config.get("source", {})
            bucket = source_config.get("s3_bucket", "s3-hulftchina-rd")
            prefix = s3_uri

        region = self.config.get("source", {}).get("region", "ap-northeast-1")

        # Step 1: S3 Discovery
        logger.info("Step 1: S3 Discovery")
        discovery_client = S3ExcelDiscovery(bucket=bucket, prefix=prefix, region=region)
        discovery = discovery_client.discover()

        # Write manifest
        manifest_path = str(self.output_dir / "s3_file_manifest.jsonl")
        discovery_client.write_manifest(manifest_path, discovery)

        # Write discovery report
        report_path = str(self.output_dir / "s3_discovery_report.md")
        discovery_client.write_report(report_path, discovery)

        if discovery.get("error"):
            logger.error("S3 discovery failed: %s", discovery["error"])
            return {"error": discovery["error"], "discovery": discovery}

        if not discovery["excel_files"]:
            logger.warning("No Excel files found under %s", s3_uri)
            return {"error": "No Excel files found", "discovery": discovery}

        # Step 2-7: Process each Excel file
        return self._process_files(discovery, discovery_client)

    def run_local(self, input_path: str) -> dict[str, Any]:
        """Run the pipeline on a local Excel file.

        Parameters
        ----------
        input_path : str
            Local path to an Excel file.

        Returns
        -------
        dict with pipeline results.
        """
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {input_path}")

        discovery = {
            "all_files": [{"key": str(path), "size": path.stat().st_size, "extension": path.suffix.lower(), "is_excel": True, "file_name": path.name}],
            "excel_files": [{"key": str(path), "size": path.stat().st_size, "extension": path.suffix.lower(), "is_excel": True, "file_name": path.name}],
            "non_excel_files": [],
            "total_count": 1,
            "excel_count": 1,
            "error": None,
        }

        return self._process_local_file(input_path, discovery)

    def _process_files(
        self,
        discovery: dict[str, Any],
        s3_client: S3ExcelDiscovery,
    ) -> dict[str, Any]:
        """Download and process discovered Excel files."""
        all_workbooks: list[ExcelWorkbookRecord] = []
        all_sheets: list[ExcelSheetRecord] = []
        all_regions: list[ExcelTableRegion] = []
        all_rows: list[ExcelRowRecord] = []
        all_cells: list[ExcelCellEvidence] = []
        all_chunks: list[EvidenceChunk] = []

        loader = WorkbookLoader(dataset=self.dataset, run_id=self.run_id)
        profiler = SheetProfiler(
            sample_cells=self.sample_cells,
            max_cell_text_length=self.max_cell_text_length,
        )
        detector = TableRegionDetector()
        normalizer = RowNormalizer(max_cell_text_length=self.max_cell_text_length)
        evidence_builder = ExcelEvidenceBuilder(
            dataset=self.dataset,
            run_id=self.run_id,
            project=self.dataset,
        )

        for file_entry in discovery["excel_files"]:
            key = file_entry["key"]
            ext = file_entry["extension"]
            logger.info("Processing Excel file: %s", key)

            if ext == ".xls":
                logger.warning("Skipping .xls file (unsupported by openpyxl): %s", key)
                continue

            # Download to temp file
            try:
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp_path = tmp.name
                s3_client.download_file(key, tmp_path)
            except Exception as exc:
                logger.error("Failed to download %s: %s", key, exc)
                continue

            try:
                results = self._process_single_workbook(
                    file_path=tmp_path,
                    source_path=key,
                    loader=loader,
                    profiler=profiler,
                    detector=detector,
                    normalizer=normalizer,
                    evidence_builder=evidence_builder,
                )
                all_workbooks.extend(results["workbooks"])
                all_sheets.extend(results["sheets"])
                all_regions.extend(results["regions"])
                all_rows.extend(results["rows"])
                all_cells.extend(results["cells"])
                all_chunks.extend(results["chunks"])
            except Exception as exc:
                logger.error("Failed to process %s: %s", key, exc)
                continue
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        # Write outputs
        self._write_outputs(all_workbooks, all_sheets, all_regions, all_rows, all_cells, all_chunks)

        # Generate reports
        reporter = ExcelReporter(str(self.output_dir))
        reporter.write_profile_report(all_workbooks, all_sheets, all_regions, all_rows, all_chunks, discovery)
        reporter.write_evidence_design_report(all_workbooks, all_sheets, all_regions, all_chunks)

        return {
            "discovery": discovery,
            "workbooks": len(all_workbooks),
            "sheets": len(all_sheets),
            "regions": len(all_regions),
            "rows": len(all_rows),
            "cells": len(all_cells),
            "chunks": len(all_chunks),
            "error": None,
        }

    def _process_local_file(
        self,
        input_path: str,
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Process a single local Excel file."""
        loader = WorkbookLoader(dataset=self.dataset, run_id=self.run_id)
        profiler = SheetProfiler(
            sample_cells=self.sample_cells,
            max_cell_text_length=self.max_cell_text_length,
        )
        detector = TableRegionDetector()
        normalizer = RowNormalizer(max_cell_text_length=self.max_cell_text_length)
        evidence_builder = ExcelEvidenceBuilder(
            dataset=self.dataset,
            run_id=self.run_id,
            project=self.dataset,
        )

        results = self._process_single_workbook(
            file_path=input_path,
            source_path=input_path,
            loader=loader,
            profiler=profiler,
            detector=detector,
            normalizer=normalizer,
            evidence_builder=evidence_builder,
        )

        all_workbooks = results["workbooks"]
        all_sheets = results["sheets"]
        all_regions = results["regions"]
        all_rows = results["rows"]
        all_cells = results["cells"]
        all_chunks = results["chunks"]

        self._write_outputs(all_workbooks, all_sheets, all_regions, all_rows, all_cells, all_chunks)

        reporter = ExcelReporter(str(self.output_dir))
        reporter.write_profile_report(all_workbooks, all_sheets, all_regions, all_rows, all_chunks, discovery)
        reporter.write_evidence_design_report(all_workbooks, all_sheets, all_regions, all_chunks)

        return {
            "discovery": discovery,
            "workbooks": len(all_workbooks),
            "sheets": len(all_sheets),
            "regions": len(all_regions),
            "rows": len(all_rows),
            "cells": len(all_cells),
            "chunks": len(all_chunks),
            "error": None,
        }

    def _process_single_workbook(
        self,
        file_path: str,
        source_path: str,
        loader: WorkbookLoader,
        profiler: SheetProfiler,
        detector: TableRegionDetector,
        normalizer: RowNormalizer,
        evidence_builder: ExcelEvidenceBuilder,
    ) -> dict[str, Any]:
        """Process a single workbook file through the full pipeline."""
        # Step 2: Load workbook
        wb_record, sheet_records, wb = loader.load(file_path, source_path)

        # Create document ID for evidence linking
        document_id = DocumentRecord.generate_id(source_path, self.dataset)

        # Steps 3-6: Profile, detect, normalize, build evidence
        profiled_sheets: list[ExcelSheetRecord] = []
        all_cells: list[ExcelCellEvidence] = []
        all_regions: list[ExcelTableRegion] = []
        all_rows: list[ExcelRowRecord] = []
        all_chunks: list[EvidenceChunk] = []

        for sheet_record in sheet_records:
            if not self.include_hidden and not sheet_record.visible:
                logger.info("Skipping hidden sheet: %s", sheet_record.sheet_name)
                continue

            ws = wb[sheet_record.sheet_name]

            # Step 3: Profile sheet
            updated_sheet, cells = profiler.profile_sheet(ws, sheet_record, wb_record.workbook_id)
            profiled_sheets.append(updated_sheet)
            all_cells.extend(cells)

            # Step 4: Detect table regions
            regions = detector.detect(ws, updated_sheet, wb_record.workbook_id)
            all_regions.extend(regions)

            # Step 5: Normalize rows
            section_id = f"sh_{updated_sheet.sheet_id}"
            for region in regions:
                rows = normalizer.normalize_region(ws, region, wb_record.workbook_id)
                all_rows.extend(rows)

                # Step 6: Build evidence chunks from rows
                row_chunks = evidence_builder.build_row_chunks(
                    rows=rows,
                    region=region,
                    wb_record=wb_record,
                    sheet_record=updated_sheet,
                    document_id=document_id,
                    section_id=section_id,
                )
                all_chunks.extend(row_chunks)

            # Build sheet summary chunk
            sheet_chunk = evidence_builder.build_sheet_summary_chunk(
                sheet_record=updated_sheet,
                wb_record=wb_record,
                regions=regions,
                document_id=document_id,
                section_id=section_id,
            )
            all_chunks.append(sheet_chunk)

        # Build workbook summary chunk
        wb_summary = evidence_builder.build_workbook_summary_chunk(
            wb_record=wb_record,
            sheet_records=profiled_sheets,
            document_id=document_id,
        )
        all_chunks.insert(0, wb_summary)

        # Close workbook
        wb.close()

        return {
            "workbooks": [wb_record],
            "sheets": profiled_sheets,
            "regions": all_regions,
            "rows": all_rows,
            "cells": all_cells,
            "chunks": all_chunks,
        }

    def _write_outputs(
        self,
        workbooks: list[ExcelWorkbookRecord],
        sheets: list[ExcelSheetRecord],
        regions: list[ExcelTableRegion],
        rows: list[ExcelRowRecord],
        cells: list[ExcelCellEvidence],
        chunks: list[EvidenceChunk],
    ) -> None:
        """Write all JSONL output files."""
        self._write_jsonl(workbooks, "excel_workbooks.jsonl")
        self._write_jsonl(sheets, "excel_sheets.jsonl")
        self._write_jsonl(regions, "excel_table_regions.jsonl")
        self._write_jsonl(rows, "excel_rows_normalized.jsonl")
        self._write_jsonl(cells, "excel_cells_sample.jsonl")
        self._write_jsonl(chunks, "evidence_chunks.jsonl")

    def _write_jsonl(self, records: list[Any], filename: str) -> None:
        """Write records to a JSONL file."""
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(record.to_jsonl() + "\n")
        logger.info("Wrote %d records to %s", len(records), path)
