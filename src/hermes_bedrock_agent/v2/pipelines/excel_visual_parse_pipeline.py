"""
Excel Visual Parse Pipeline — orchestrates extraction, analysis, and reporting.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import boto3

from hermes_bedrock_agent.v2.excel.excel_visual_object_extractor import ExcelVisualObjectExtractor
from hermes_bedrock_agent.v2.excel.excel_sheet_image_exporter import ExcelSheetImageExporter
from hermes_bedrock_agent.v2.excel.excel_bedrock_vision_analyzer import ExcelBedrockVisionAnalyzer
from hermes_bedrock_agent.v2.excel.excel_visual_markdown_exporter import ExcelVisualMarkdownExporter
from hermes_bedrock_agent.v2.excel.excel_visual_reporter import ExcelVisualReporter

logger = logging.getLogger(__name__)


class ExcelVisualParsePipeline:
    """Full pipeline: S3 download → extract → analyze → export markdown → report."""

    def __init__(
        self,
        config: dict[str, Any],
        output_dir: str,
        run_id: str = "",
        dataset: str = "",
        s3_uri: str = "",
        bedrock_enabled: bool = True,
        max_images_per_sheet: int = 50,
    ):
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or config.get("run_id", "")
        self.dataset = dataset or config.get("dataset", "")
        self.s3_uri = s3_uri or config.get("source", {}).get("s3_uri", "")
        self.bedrock_enabled = bedrock_enabled
        self.max_images_per_sheet = max_images_per_sheet

        # Bedrock config
        bedrock_cfg = config.get("bedrock", {})
        self.bedrock_model_id = bedrock_cfg.get("model_id", "") or os.environ.get("BEDROCK_VLM_MODEL_ID", "")
        self.bedrock_region = bedrock_cfg.get("region", "ap-northeast-1")

        # Results
        self.workbook_records: list[dict[str, Any]] = []
        self.sheet_records: list[dict[str, Any]] = []
        self.object_records: list[dict[str, Any]] = []
        self.analysis_records: list[dict[str, Any]] = []
        self.sheet_image_results: list[dict[str, Any]] = []
        self.generated_files: list[str] = []
        self.warnings: list[str] = []

    def run(self) -> dict[str, Any]:
        """Execute the full pipeline."""
        logger.info("=" * 60)
        logger.info("Excel Visual Parse Pipeline")
        logger.info("  dataset=%s  run_id=%s", self.dataset, self.run_id)
        logger.info("  s3_uri=%s", self.s3_uri)
        logger.info("  bedrock=%s  model=%s", self.bedrock_enabled, self.bedrock_model_id)
        logger.info("=" * 60)

        # Step 1: Download workbooks from S3
        local_files = self._download_workbooks()
        if not local_files:
            self.warnings.append("No workbooks downloaded from S3")
            logger.error("No workbooks found. Pipeline cannot proceed.")
            # Still generate empty report
            return self._finalize()

        # Step 2: Extract visual objects from each workbook
        for local_path, s3_key in local_files:
            wb_name = os.path.basename(s3_key)
            logger.info("Processing workbook: %s", wb_name)
            self._process_workbook(local_path, wb_name)

        # Step 3: Bedrock analysis
        if self.bedrock_enabled and self.bedrock_model_id:
            self._run_bedrock_analysis()
        else:
            self.warnings.append("Bedrock analysis disabled or model not configured")
            logger.info("Bedrock analysis skipped")

        # Step 4: Generate markdown exports
        self._generate_markdown()

        # Step 5: Generate final report
        return self._finalize()

    def _download_workbooks(self) -> list[tuple[str, str]]:
        """Download Excel files from S3."""
        local_files = []
        try:
            # Parse S3 URI
            if not self.s3_uri.startswith("s3://"):
                self.warnings.append(f"Invalid S3 URI: {self.s3_uri}")
                return []

            parts = self.s3_uri.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""

            s3 = boto3.client("s3", region_name=self.bedrock_region)
            paginator = s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

            excel_keys = []
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    ext = os.path.splitext(key)[1].lower()
                    if ext in (".xlsx", ".xlsm", ".xls"):
                        excel_keys.append(key)

            logger.info("Found %d Excel files in S3", len(excel_keys))

            # Download to temp directory
            tmp_dir = self.output_dir / "tmp_workbooks"
            tmp_dir.mkdir(parents=True, exist_ok=True)

            for key in excel_keys:
                basename = os.path.basename(key)
                local_path = str(tmp_dir / basename)
                logger.info("Downloading: %s → %s", key, local_path)
                s3.download_file(bucket, key, local_path)
                local_files.append((local_path, key))

        except Exception as e:
            self.warnings.append(f"S3 download error: {e}")
            logger.error("S3 download failed: %s", e)

        return local_files

    def _process_workbook(self, local_path: str, wb_name: str):
        """Extract visual objects from one workbook."""
        extractor = ExcelVisualObjectExtractor(
            workbook_path=local_path,
            output_dir=str(self.output_dir),
            workbook_name=wb_name,
            dataset=self.dataset,
            run_id=self.run_id,
        )
        result = extractor.extract_all()

        self.workbook_records.append(result.get("workbook_record", {}))
        self.sheet_records.extend(result.get("sheet_records", []))
        self.object_records.extend(result.get("object_records", []))
        self.warnings.extend(w.get("message", str(w)) if isinstance(w, dict) else str(w)
                            for w in result.get("warnings", []))

        # Sheet image export
        sheet_names = [s.get("sheet_name", "") for s in result.get("sheet_records", [])]
        exporter = ExcelSheetImageExporter(output_dir=str(self.output_dir))
        img_results = exporter.export_sheet_images(local_path, wb_name, sheet_names)
        self.sheet_image_results.extend(img_results)
        self.warnings.extend(exporter.warnings)

    def _run_bedrock_analysis(self):
        """Run Bedrock vision analysis on extracted images."""
        analyzer = ExcelBedrockVisionAnalyzer(
            model_id=self.bedrock_model_id,
            region=self.bedrock_region,
            max_images=self.max_images_per_sheet * len(self.workbook_records),
            run_id=self.run_id,
            dataset=self.dataset,
        )

        # Build image targets from extracted objects
        image_targets = []
        for obj in self.object_records:
            if obj.get("object_type") == "embedded_image" and obj.get("image_path"):
                image_targets.append({
                    "image_path": obj["image_path"],
                    "workbook_name": obj.get("workbook_name", ""),
                    "sheet_name": obj.get("sheet_name", ""),
                    "sheet_id": obj.get("sheet_id", ""),
                    "workbook_id": obj.get("workbook_id", ""),
                    "visual_object_id": obj.get("visual_object_id", ""),
                    "analysis_target_type": "embedded_image",
                })

        if not image_targets:
            self.warnings.append("No analyzable images found for Bedrock")
            logger.info("No images to analyze with Bedrock")
            return

        logger.info("Sending %d images to Bedrock for analysis", len(image_targets))
        results = analyzer.analyze_all_images(image_targets)
        self.analysis_records = [asdict(r) for r in results]
        self.warnings.extend(analyzer.warnings)
        logger.info("Bedrock analysis complete: %d results", len(self.analysis_records))

    def _generate_markdown(self):
        """Generate all markdown exports."""
        exporter = ExcelVisualMarkdownExporter(
            workbook_records=self.workbook_records,
            sheet_records=self.sheet_records,
            object_records=self.object_records,
            analysis_records=self.analysis_records,
            sheet_image_results=self.sheet_image_results,
            output_dir=str(self.output_dir),
            run_id=self.run_id,
            dataset=self.dataset,
            s3_uri=self.s3_uri,
            warnings=self.warnings,
        )
        files = exporter.export_all()
        self.generated_files.extend(files)

    def _finalize(self) -> dict[str, Any]:
        """Generate final report and write JSONL outputs."""
        # Write JSONL files
        jsonl_dir = self.output_dir / "jsonl"
        jsonl_dir.mkdir(parents=True, exist_ok=True)

        # Workbook records
        wb_path = jsonl_dir / "visual_workbooks.jsonl"
        with open(wb_path, "w", encoding="utf-8") as f:
            for r in self.workbook_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.generated_files.append(str(wb_path))

        # Sheet records
        sh_path = jsonl_dir / "visual_sheets.jsonl"
        with open(sh_path, "w", encoding="utf-8") as f:
            for r in self.sheet_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.generated_files.append(str(sh_path))

        # Object records
        obj_path = jsonl_dir / "visual_objects.jsonl"
        with open(obj_path, "w", encoding="utf-8") as f:
            for r in self.object_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.generated_files.append(str(obj_path))

        # Analysis records
        if self.analysis_records:
            an_path = jsonl_dir / "visual_analyses.jsonl"
            with open(an_path, "w", encoding="utf-8") as f:
                for r in self.analysis_records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.generated_files.append(str(an_path))

        # Generate final report
        reporter = ExcelVisualReporter(
            workbook_records=self.workbook_records,
            sheet_records=self.sheet_records,
            object_records=self.object_records,
            analysis_records=self.analysis_records,
            sheet_image_results=self.sheet_image_results,
            generated_files=self.generated_files,
            output_dir=str(self.output_dir),
            run_id=self.run_id,
            dataset=self.dataset,
            s3_uri=self.s3_uri,
            warnings=self.warnings,
            bedrock_used=self.bedrock_enabled and len(self.analysis_records) > 0,
            model_id=self.bedrock_model_id,
        )
        report_path = reporter.generate_report()
        self.generated_files.append(report_path)

        summary = {
            "status": "completed",
            "workbook_count": len(self.workbook_records),
            "sheet_count": len(self.sheet_records),
            "visual_object_count": len(self.object_records),
            "bedrock_analysis_count": len(self.analysis_records),
            "generated_files": self.generated_files,
            "warning_count": len(self.warnings),
            "output_dir": str(self.output_dir),
        }
        logger.info("Pipeline complete: %s", json.dumps(summary, indent=2))
        return summary
