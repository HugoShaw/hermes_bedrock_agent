#!/usr/bin/env python3
"""
build_unified_evidence_store_v1.py — Evidence pipeline orchestrator.

Runs all 13 stages of the evidence pipeline in sequence, writing
intermediate JSONL/Markdown artifacts to --output-dir and optionally
uploading the results to S3.

Usage:
    PYTHONPATH=src python scripts/build_unified_evidence_store_v1.py \\
        --config configs/sample_20260519_evidence_v1.yaml \\
        --run-id sample_20260519_evidence_v1 \\
        --dataset sample_20260519 \\
        --s3-uri "s3://s3-hulftchina-rd/サンプル20260519/" \\
        --output-dir data/outputs/sample_20260519_evidence_v1 \\
        --upload-s3 "s3://s3-hulftchina-rd/output/sample_20260519/"
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging setup — configure before importing pipeline modules so their
# loggers inherit the root level.
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("build_unified_evidence_store")


# ---------------------------------------------------------------------------
# Pipeline module imports
# ---------------------------------------------------------------------------

from hermes_bedrock_agent.v2.evidence_pipeline.config_loader import load_config
from hermes_bedrock_agent.v2.evidence_pipeline.s3_source_discovery import S3SourceDiscovery
from hermes_bedrock_agent.v2.evidence_pipeline.excel_parser import ExcelParser
from hermes_bedrock_agent.v2.evidence_pipeline.excel_table_parser import ExcelTableParser
from hermes_bedrock_agent.v2.evidence_pipeline.excel_visual_prescan import ExcelVisualPrescan
from hermes_bedrock_agent.v2.evidence_pipeline.excel_ooxml_visual_parser import ExcelOOXMLVisualParser
from hermes_bedrock_agent.v2.evidence_pipeline.excel_image_extractor import ExcelImageExtractor
from hermes_bedrock_agent.v2.evidence_pipeline.mermaid_parser import MermaidParser
from hermes_bedrock_agent.v2.evidence_pipeline.optional_vision_analyzer import OptionalVisionAnalyzer
from hermes_bedrock_agent.v2.evidence_pipeline.evidence_record_builder import EvidenceRecordBuilder
from hermes_bedrock_agent.v2.evidence_pipeline.evidence_markdown_exporter import EvidenceMarkdownExporter
from hermes_bedrock_agent.v2.evidence_pipeline.run_reporter import RunReporter
from hermes_bedrock_agent.v2.evidence_pipeline.s3_output_uploader import S3OutputUploader
# Semantic pipeline modules
from hermes_bedrock_agent.v2.evidence_pipeline.table_type_classifier import (
    classify_batch,
    write_classification_report,
)
from hermes_bedrock_agent.v2.evidence_pipeline.header_role_detector import detect_column_roles
from hermes_bedrock_agent.v2.evidence_pipeline.table_semantic_renderer import TableSemanticRenderer
from hermes_bedrock_agent.v2.evidence_pipeline.row_semantic_renderer import RowSemanticRenderer
from hermes_bedrock_agent.v2.evidence_pipeline.field_definition_builder import FieldDefinitionBuilder
from hermes_bedrock_agent.v2.evidence_pipeline.business_rule_evidence_builder import BusinessRuleEvidenceBuilder
from hermes_bedrock_agent.v2.evidence_pipeline.graph_hint_builder import GraphHintBuilder
from hermes_bedrock_agent.v2.evidence_pipeline.alias_keyword_generator import AliasKeywordGenerator
from hermes_bedrock_agent.v2.evidence_pipeline.evidence_quality_checker import EvidenceQualityChecker
from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord, write_jsonl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timer() -> float:
    return time.monotonic()


def _elapsed(start: float) -> float:
    return time.monotonic() - start


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return (bucket, prefix) from 's3://bucket/prefix/'."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI (must start with s3://): {uri}")
    without_scheme = uri[len("s3://"):]
    slash = without_scheme.find("/")
    if slash == -1:
        return without_scheme, ""
    return without_scheme[:slash], without_scheme[slash + 1:]


def _stage_header(name: str) -> None:
    logger.info("=" * 60)
    logger.info("STAGE: %s", name)
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evidence pipeline — unified evidence store builder v1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", required=True, help="Path to YAML config file")
    p.add_argument("--run-id", required=True, help="Run identifier (e.g. sample_20260519_evidence_v1)")
    p.add_argument("--dataset", required=True, help="Dataset name (e.g. sample_20260519)")
    p.add_argument("--s3-uri", required=True, help="S3 source URI (e.g. s3://bucket/prefix/)")
    p.add_argument("--output-dir", required=True, help="Local output directory")
    p.add_argument("--upload-s3", default=None, help="S3 destination URI for output upload (optional)")
    vision_group = p.add_mutually_exclusive_group()
    vision_group.add_argument("--use-vision", dest="use_vision", action="store_true",
                               help="Enable VLM image analysis via Bedrock")
    vision_group.add_argument("--no-vision", dest="use_vision", action="store_false",
                               help="Disable VLM image analysis")
    p.set_defaults(use_vision=None)
    return p


# ---------------------------------------------------------------------------
# Pipeline state — all intermediate results live here
# ---------------------------------------------------------------------------

class PipelineState:
    def __init__(self, dataset: str, run_id: str, output_dir: str) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.errors: list[str] = []
        self.stage_timings: dict[str, float] = {}

        # Stage outputs
        self.config: dict[str, Any] = {}
        self.discovery: dict[str, Any] = {}
        self.downloaded_files: list[dict[str, Any]] = []
        self.workbook_records: list[dict[str, Any]] = []
        self.sheet_records: list[dict[str, Any]] = []
        self.openpyxl_workbooks: dict[str, Any] = {}     # file_path → wb object
        self.table_regions: list[dict[str, Any]] = []
        self.normalized_rows: list[dict[str, Any]] = []
        self.prescan_records: list[dict[str, Any]] = []
        self.drawing_objects: list[dict[str, Any]] = []
        self.connectors: list[dict[str, Any]] = []
        self.chart_objects: list[dict[str, Any]] = []
        self.image_records: list[dict[str, Any]] = []
        self.mermaid_file_records: list[dict[str, Any]] = []
        self.mermaid_graph_records: list[dict[str, Any]] = []
        self.mermaid_node_records: list[dict[str, Any]] = []
        self.mermaid_edge_records: list[dict[str, Any]] = []
        self.visual_analysis_records: list[dict[str, Any]] = []
        self.evidence_records: list[Any] = []            # list[EvidenceRecord]
        self.evidence_jsonl_path: str = ""
        # Semantic pipeline state (stages 4a–4h)
        self.classifications: list[dict[str, Any]] = []           # classified table_regions
        self.column_roles_map: dict[str, dict[str, str]] = {}     # region_id → column_roles
        self.semantic_table_records: list[Any] = []               # table_region/header/markdown
        self.semantic_row_records: list[Any] = []                 # enriched table_row records
        self.field_definition_records: list[Any] = []             # field_definition records
        self.business_rule_records: list[Any] = []                # business_rule records
        self.sheet_summary_records: list[Any] = []                # sheet_summary records
        self.graph_hint_records: list[Any] = []                   # graph_candidate records
        self.quality_issues: list[dict[str, Any]] = []            # quality checker output

    def record_error(self, stage: str, exc: Exception) -> None:
        msg = f"[{stage}] {type(exc).__name__}: {exc}"
        self.errors.append(msg)
        logger.error(msg)

    def time_stage(self, name: str, elapsed: float) -> None:
        self.stage_timings[name] = elapsed
        logger.info("Stage '%s' completed in %.2fs", name, elapsed)

    def subdir(self, *parts: str) -> Path:
        d = self.output_dir.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def stage1_load_config(state: PipelineState, config_path: str) -> None:
    _stage_header("1 — Load config")
    t = _timer()
    try:
        state.config = load_config(yaml_path=config_path)
        logger.info("Config loaded: %d top-level keys", len(state.config))
    except Exception as exc:
        state.record_error("stage1_load_config", exc)
    state.time_stage("1_load_config", _elapsed(t))


def stage2_s3_discovery(state: PipelineState, s3_uri: str) -> None:
    _stage_header("2 — S3 source discovery")
    t = _timer()
    try:
        bucket, prefix = _parse_s3_uri(s3_uri)
        region = state.config.get("aws_region", "ap-northeast-1")
        discoverer = S3SourceDiscovery(bucket=bucket, prefix=prefix, region=region)
        state.discovery = discoverer.discover()

        manifest_path = str(state.subdir() / "s3_file_manifest.jsonl")
        discoverer.write_manifest(manifest_path, state.discovery)

        report_path = str(state.subdir("reports") / "s3_discovery_report.md")
        discoverer.write_report(report_path, state.discovery)

        logger.info(
            "Discovery: %d total (%d excel, %d mermaid)",
            state.discovery["total_count"],
            state.discovery["excel_count"],
            state.discovery["mermaid_count"],
        )

        # Download all files
        raw_dir = str(state.subdir("raw"))
        state.downloaded_files = discoverer.download_all(
            state.discovery, local_dir=raw_dir, file_classes=None
        )
        ok = sum(1 for f in state.downloaded_files if f.get("local_path"))
        logger.info("Downloaded %d/%d files to %s", ok, len(state.downloaded_files), raw_dir)

    except Exception as exc:
        state.record_error("stage2_s3_discovery", exc)

    state.time_stage("2_s3_discovery", _elapsed(t))


def stage3_excel_parse(state: PipelineState) -> None:
    _stage_header("3 — Excel workbook parsing")
    t = _timer()
    try:
        parser = ExcelParser(dataset=state.dataset, run_id=state.run_id)
        excel_files = [
            f for f in state.downloaded_files
            if f.get("local_path") and f.get("file_class") == "excel"
        ]
        logger.info("Parsing %d Excel files", len(excel_files))

        for entry in excel_files:
            local_path = entry["local_path"]
            s3_uri = entry.get("s3_uri", "")
            try:
                result = parser.parse_workbook(local_path, source_s3_uri=s3_uri)
                if result.get("error"):
                    state.errors.append(f"[stage3] {local_path}: {result['error']}")
                    logger.warning("Workbook parse error %s: %s", local_path, result["error"])
                    continue
                if result.get("workbook_record"):
                    state.workbook_records.append(result["workbook_record"])
                state.sheet_records.extend(result.get("sheet_records", []))
                if result.get("openpyxl_workbook"):
                    state.openpyxl_workbooks[local_path] = {
                        "wb": result["openpyxl_workbook"],
                        "sheet_records": result.get("sheet_records", []),
                        "s3_uri": s3_uri,
                    }
            except Exception as exc:
                state.record_error(f"stage3[{Path(local_path).name}]", exc)

        parser.write_jsonl(
            workbook_records=state.workbook_records,
            sheet_records=state.sheet_records,
            output_dir=str(state.output_dir),
        )
        logger.info(
            "Excel parse: %d workbooks, %d sheets",
            len(state.workbook_records), len(state.sheet_records),
        )
    except Exception as exc:
        state.record_error("stage3_excel_parse", exc)

    state.time_stage("3_excel_parse", _elapsed(t))


def stage4_table_parse(state: PipelineState) -> None:
    _stage_header("4 — Excel table detection")
    t = _timer()
    try:
        tparser = ExcelTableParser(dataset=state.dataset, run_id=state.run_id)

        for local_path, wb_info in state.openpyxl_workbooks.items():
            wb = wb_info["wb"]
            wb_sheet_records = wb_info["sheet_records"]
            s3_uri = wb_info["s3_uri"]
            workbook_name = Path(local_path).stem

            # Build workbook_id from first sheet record
            workbook_id = wb_sheet_records[0]["workbook_id"] if wb_sheet_records else ""

            for sheet_rec in wb_sheet_records:
                sheet_name = sheet_rec["sheet_name"]
                try:
                    ws = wb[sheet_name]
                    result = tparser.detect_tables(
                        ws=ws,
                        sheet_id=sheet_rec["sheet_id"],
                        workbook_id=workbook_id,
                        workbook_name=workbook_name,
                        source_file=local_path,
                        source_s3_uri=s3_uri,
                    )
                    state.table_regions.extend(result.get("table_regions", []))
                    state.normalized_rows.extend(result.get("normalized_rows", []))
                except Exception as exc:
                    state.record_error(
                        f"stage4[{workbook_name}/{sheet_name}]", exc
                    )

        tparser.write_jsonl(
            table_regions=state.table_regions,
            normalized_rows=state.normalized_rows,
            output_dir=str(state.output_dir),
        )
        logger.info(
            "Table parse: %d regions, %d normalized rows",
            len(state.table_regions), len(state.normalized_rows),
        )
    except Exception as exc:
        state.record_error("stage4_table_parse", exc)

    state.time_stage("4_table_parse", _elapsed(t))


def stage4a_classify_tables(state: PipelineState) -> None:
    _stage_header("4a — Table type classification")
    t = _timer()
    try:
        state.classifications = classify_batch(state.table_regions)
        report_path = str(state.subdir("reports") / "table_type_classification_report.md")
        write_classification_report(state.classifications, output_path=report_path)
        type_dist: dict[str, int] = {}
        for c in state.classifications:
            tt = c.get("table_type", "unknown_table")
            type_dist[tt] = type_dist.get(tt, 0) + 1
        logger.info(
            "Table classification: %d regions classified. Distribution: %s",
            len(state.classifications),
            type_dist,
        )
    except Exception as exc:
        state.record_error("stage4a_classify_tables", exc)
    state.time_stage("4a_classify_tables", _elapsed(t))


def stage4b_detect_header_roles(state: PipelineState) -> None:
    _stage_header("4b — Header role detection")
    t = _timer()
    try:
        report_lines: list[str] = [
            "# Header Role Detection Report",
            "",
            f"Total regions: {len(state.table_regions)}",
            "",
            "| Region ID | Sheet | Columns | Matched | Confidence |",
            "|-----------|-------|---------|---------|------------|",
        ]
        for region in state.table_regions:
            region_id = region.get("table_region_id", "")
            result = detect_column_roles(region)
            state.column_roles_map[region_id] = result["column_roles"]
            matched = sum(1 for r in result["column_roles"].values() if r != "unknown")
            report_lines.append(
                f"| {region_id} "
                f"| {region.get('sheet_name', '')} "
                f"| {len(result['column_roles'])} "
                f"| {matched} "
                f"| {result['confidence']:.3f} |"
            )

        report_path = state.subdir("reports") / "header_role_detection_report.md"
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        logger.info(
            "Header roles detected for %d regions → %s",
            len(state.column_roles_map),
            report_path,
        )
    except Exception as exc:
        state.record_error("stage4b_detect_header_roles", exc)
    state.time_stage("4b_detect_header_roles", _elapsed(t))


def stage4c_semantic_table_rendering(state: PipelineState) -> None:
    _stage_header("4c — Semantic table rendering")
    t = _timer()
    try:
        renderer = TableSemanticRenderer(dataset=state.dataset, run_id=state.run_id)
        state.semantic_table_records = renderer.render_all(
            table_regions=state.table_regions,
            classifications=state.classifications,
            column_roles_map=state.column_roles_map,
        )
        logger.info(
            "Semantic table rendering: %d records (table_region / header_structure / raw_markdown)",
            len(state.semantic_table_records),
        )
    except Exception as exc:
        state.record_error("stage4c_semantic_table_rendering", exc)
    state.time_stage("4c_semantic_table_rendering", _elapsed(t))


def stage4d_semantic_row_rendering(state: PipelineState) -> None:
    _stage_header("4d — Semantic row rendering")
    t = _timer()
    try:
        renderer = RowSemanticRenderer(dataset=state.dataset, run_id=state.run_id)
        state.semantic_row_records = renderer.render_all(
            normalized_rows=state.normalized_rows,
            table_regions=state.table_regions,
            classifications=state.classifications,
            column_roles_map=state.column_roles_map,
        )
        logger.info(
            "Semantic row rendering: %d table_row records",
            len(state.semantic_row_records),
        )
    except Exception as exc:
        state.record_error("stage4d_semantic_row_rendering", exc)
    state.time_stage("4d_semantic_row_rendering", _elapsed(t))


def stage4e_field_definitions(state: PipelineState) -> None:
    _stage_header("4e — Field definition extraction")
    t = _timer()
    try:
        builder = FieldDefinitionBuilder(dataset=state.dataset, run_id=state.run_id)
        state.field_definition_records = builder.build_all(
            normalized_rows=state.normalized_rows,
            table_regions=state.table_regions,
            classifications=state.classifications,
            column_roles_map=state.column_roles_map,
        )
        logger.info(
            "Field definitions: %d field_definition records",
            len(state.field_definition_records),
        )
    except Exception as exc:
        state.record_error("stage4e_field_definitions", exc)
    state.time_stage("4e_field_definitions", _elapsed(t))


def stage4f_business_rules(state: PipelineState) -> None:
    _stage_header("4f — Business rule extraction")
    t = _timer()
    try:
        builder = BusinessRuleEvidenceBuilder(dataset=state.dataset, run_id=state.run_id)
        state.business_rule_records = builder.build_all(
            normalized_rows=state.normalized_rows,
            table_regions=state.table_regions,
            classifications=state.classifications,
            column_roles_map=state.column_roles_map,
        )
        state.sheet_summary_records = builder.build_sheet_summaries(
            sheet_records=state.sheet_records,
            table_regions=state.table_regions,
            classifications=state.classifications,
        )
        logger.info(
            "Business rules: %d business_rule records, %d sheet_summary records",
            len(state.business_rule_records),
            len(state.sheet_summary_records),
        )
    except Exception as exc:
        state.record_error("stage4f_business_rules", exc)
    state.time_stage("4f_business_rules", _elapsed(t))


def stage4g_graph_hints(state: PipelineState) -> None:
    _stage_header("4g — Graph hint building")
    t = _timer()
    try:
        builder = GraphHintBuilder(dataset=state.dataset, run_id=state.run_id)
        state.graph_hint_records = builder.build_all(
            normalized_rows=state.normalized_rows,
            table_regions=state.table_regions,
            classifications=state.classifications,
            column_roles_map=state.column_roles_map,
        )
        report_path = str(state.subdir("reports") / "graph_hints_report.md")
        builder.write_report(hints=state.graph_hint_records, output_path=report_path)
        logger.info(
            "Graph hints: %d graph_candidate records → %s",
            len(state.graph_hint_records),
            report_path,
        )
    except Exception as exc:
        state.record_error("stage4g_graph_hints", exc)
    state.time_stage("4g_graph_hints", _elapsed(t))


def stage4h_alias_enrichment(state: PipelineState) -> None:
    _stage_header("4h — Alias/keyword enrichment")
    t = _timer()
    try:
        generator = AliasKeywordGenerator()
        all_semantic: list[EvidenceRecord] = (
            state.semantic_table_records
            + state.semantic_row_records
            + state.field_definition_records
            + state.business_rule_records
            + state.sheet_summary_records
            + state.graph_hint_records
        )
        enriched = generator.enrich_batch(all_semantic)

        # Slice enriched results back into their respective state lists
        def _retype(rec: EvidenceRecord, target: str) -> bool:
            return rec.record_type in target if isinstance(target, frozenset) else rec.record_type == target

        n_table = len(state.semantic_table_records)
        n_row = len(state.semantic_row_records)
        n_fd = len(state.field_definition_records)
        n_br = len(state.business_rule_records)
        n_ss = len(state.sheet_summary_records)
        n_gh = len(state.graph_hint_records)

        state.semantic_table_records = enriched[:n_table]
        state.semantic_row_records = enriched[n_table:n_table + n_row]
        state.field_definition_records = enriched[n_table + n_row:n_table + n_row + n_fd]
        state.business_rule_records = enriched[n_table + n_row + n_fd:n_table + n_row + n_fd + n_br]
        state.sheet_summary_records = enriched[n_table + n_row + n_fd + n_br:n_table + n_row + n_fd + n_br + n_ss]
        state.graph_hint_records = enriched[n_table + n_row + n_fd + n_br + n_ss:]

        logger.info(
            "Alias enrichment: %d semantic records enriched",
            len(enriched),
        )
    except Exception as exc:
        state.record_error("stage4h_alias_enrichment", exc)
    state.time_stage("4h_alias_enrichment", _elapsed(t))


def stage5_visual_prescan(state: PipelineState) -> None:
    _stage_header("5 — Visual prescan")
    t = _timer()
    try:
        scanner = ExcelVisualPrescan(dataset=state.dataset, run_id=state.run_id)
        sheet_by_file: dict[str, list[dict[str, Any]]] = {}
        for sr in state.sheet_records:
            sheet_by_file.setdefault(sr["source_file"], []).append(sr)

        for local_path, wb_info in state.openpyxl_workbooks.items():
            s3_uri = wb_info["s3_uri"]
            wb_sheet_records = sheet_by_file.get(local_path, [])
            try:
                prescan = scanner.scan_workbook(
                    file_path=local_path,
                    sheet_records=wb_sheet_records,
                    source_s3_uri=s3_uri,
                )
                state.prescan_records.extend(prescan)
            except Exception as exc:
                state.record_error(f"stage5[{Path(local_path).name}]", exc)

        scanner.write_jsonl(
            records=state.prescan_records,
            output_dir=str(state.output_dir),
        )
        logger.info("Visual prescan: %d sheet records", len(state.prescan_records))
    except Exception as exc:
        state.record_error("stage5_visual_prescan", exc)

    state.time_stage("5_visual_prescan", _elapsed(t))


def stage6_ooxml_visual_parse(state: PipelineState) -> None:
    _stage_header("6 — OOXML visual parsing")
    t = _timer()
    try:
        vparser = ExcelOOXMLVisualParser(dataset=state.dataset, run_id=state.run_id)
        sheet_by_file: dict[str, list[dict[str, Any]]] = {}
        for sr in state.sheet_records:
            sheet_by_file.setdefault(sr["source_file"], []).append(sr)
        prescan_by_file: dict[str, list[dict[str, Any]]] = {}
        for pr in state.prescan_records:
            prescan_by_file.setdefault(pr["source_file"], []).append(pr)

        for local_path, wb_info in state.openpyxl_workbooks.items():
            s3_uri = wb_info["s3_uri"]
            wb_sheet_records = sheet_by_file.get(local_path, [])
            wb_prescan = prescan_by_file.get(local_path, [])
            try:
                result = vparser.parse_workbook(
                    file_path=local_path,
                    sheet_records=wb_sheet_records,
                    prescan_records=wb_prescan,
                    source_s3_uri=s3_uri,
                )
                state.drawing_objects.extend(result.get("drawing_objects", []))
                state.connectors.extend(result.get("connectors", []))
                state.chart_objects.extend(result.get("chart_objects", []))
            except Exception as exc:
                state.record_error(f"stage6[{Path(local_path).name}]", exc)

        vparser.write_jsonl(
            drawing_objects=state.drawing_objects,
            connectors=state.connectors,
            chart_objects=state.chart_objects,
            output_dir=str(state.output_dir),
        )
        logger.info(
            "OOXML visual: %d shapes, %d connectors, %d charts",
            len(state.drawing_objects), len(state.connectors), len(state.chart_objects),
        )
    except Exception as exc:
        state.record_error("stage6_ooxml_visual_parse", exc)

    state.time_stage("6_ooxml_visual_parse", _elapsed(t))


def stage7_image_extract(state: PipelineState) -> None:
    _stage_header("7 — Image extraction")
    t = _timer()
    try:
        extractor = ExcelImageExtractor(dataset=state.dataset, run_id=state.run_id)
        sheet_by_file: dict[str, list[dict[str, Any]]] = {}
        for sr in state.sheet_records:
            sheet_by_file.setdefault(sr["source_file"], []).append(sr)

        for local_path, wb_info in state.openpyxl_workbooks.items():
            s3_uri = wb_info["s3_uri"]
            wb_sheet_records = sheet_by_file.get(local_path, [])
            try:
                records = extractor.extract(
                    file_path=local_path,
                    output_dir=str(state.output_dir),
                    sheet_records=wb_sheet_records,
                    source_s3_uri=s3_uri,
                )
                state.image_records.extend(records)
            except Exception as exc:
                state.record_error(f"stage7[{Path(local_path).name}]", exc)

        extractor.write_jsonl(
            records=state.image_records,
            output_dir=str(state.output_dir),
        )
        logger.info("Image extraction: %d images", len(state.image_records))
    except Exception as exc:
        state.record_error("stage7_image_extract", exc)

    state.time_stage("7_image_extract", _elapsed(t))


def stage8_mermaid_parse(state: PipelineState) -> None:
    _stage_header("8 — Mermaid parsing")
    t = _timer()
    try:
        mermaid_files = [
            f for f in state.downloaded_files
            if f.get("local_path") and f.get("file_class") == "mermaid"
        ]
        mermaid_paths = [f["local_path"] for f in mermaid_files]
        source_s3_uris = {f["local_path"]: f.get("s3_uri", "") for f in mermaid_files}

        mparser = MermaidParser(dataset=state.dataset, run_id=state.run_id)
        result = mparser.parse_files(
            file_paths=mermaid_paths,
            workbook_records=state.workbook_records,
            source_s3_uris=source_s3_uris,
        )
        state.mermaid_file_records = result.get("file_records", [])
        state.mermaid_graph_records = result.get("graph_records", [])
        state.mermaid_node_records = result.get("node_records", [])
        state.mermaid_edge_records = result.get("edge_records", [])

        mparser.write_jsonl(
            file_records=state.mermaid_file_records,
            graph_records=state.mermaid_graph_records,
            node_records=state.mermaid_node_records,
            edge_records=state.mermaid_edge_records,
            output_dir=str(state.output_dir),
        )
        logger.info(
            "Mermaid: %d files, %d graphs, %d nodes, %d edges",
            len(state.mermaid_file_records), len(state.mermaid_graph_records),
            len(state.mermaid_node_records), len(state.mermaid_edge_records),
        )
    except Exception as exc:
        state.record_error("stage8_mermaid_parse", exc)

    state.time_stage("8_mermaid_parse", _elapsed(t))


def stage9_vision_analysis(state: PipelineState) -> None:
    _stage_header("9 — Optional vision analysis")
    t = _timer()
    try:
        model_id = (
            state.config.get("bedrock_vlm_model_id")
            or os.environ.get("BEDROCK_VLM_MODEL_ID")
            or os.environ.get("VISION_LLM_MODEL_ID", "")
        )
        region = state.config.get("aws_region", "ap-northeast-1")
        analyzer = OptionalVisionAnalyzer(
            model_id=model_id,
            region=region,
            dataset=state.dataset,
            run_id=state.run_id,
        )

        if not analyzer.enabled:
            logger.info("VLM analysis skipped: no model_id configured")
        else:
            state.visual_analysis_records = analyzer.analyze(
                image_records=state.image_records,
                prescan_records=state.prescan_records,
            )
            analyzer.write_jsonl(
                records=state.visual_analysis_records,
                output_dir=str(state.output_dir),
            )
            analyzer.write_selection_report(str(state.output_dir))
            analyzer.write_raw_responses(str(state.output_dir))
            logger.info("VLM analysis: %d records", len(state.visual_analysis_records))
    except Exception as exc:
        state.record_error("stage9_vision_analysis", exc)

    state.time_stage("9_vision_analysis", _elapsed(t))


def stage10_build_evidence_records(state: PipelineState) -> None:
    _stage_header("10 — Evidence record building")
    t = _timer()
    try:
        builder = EvidenceRecordBuilder(dataset=state.dataset, run_id=state.run_id)
        # Build baseline records (excludes table_rows — those are replaced by semantic records)
        baseline = builder.build_all(
            sheet_records=state.sheet_records,
            table_regions=[],        # covered by semantic_table_records
            normalized_rows=[],      # covered by semantic_row_records
            drawing_objects=state.drawing_objects,
            connectors=state.connectors,
            chart_objects=state.chart_objects,
            image_records=state.image_records,
            graph_records=state.mermaid_graph_records,
            node_records=state.mermaid_node_records,
            edge_records=state.mermaid_edge_records,
            visual_analysis_records=state.visual_analysis_records,
        )

        # Combine: baseline non-table records + all semantic records
        semantic_all: list[EvidenceRecord] = (
            state.semantic_table_records
            + state.semantic_row_records
            + state.field_definition_records
            + state.business_rule_records
            + state.sheet_summary_records
            + state.graph_hint_records
        )

        state.evidence_records = baseline + semantic_all

        state.evidence_jsonl_path = builder.write_jsonl(
            records=state.evidence_records,
            output_dir=str(state.output_dir),
        )
        logger.info(
            "Evidence records: %d total (%d baseline + %d semantic) → %s",
            len(state.evidence_records),
            len(baseline),
            len(semantic_all),
            state.evidence_jsonl_path,
        )
    except Exception as exc:
        state.record_error("stage10_build_evidence_records", exc)

    state.time_stage("10_build_evidence_records", _elapsed(t))


def stage11_markdown_export(state: PipelineState) -> None:
    _stage_header("11 — Markdown export")
    t = _timer()
    try:
        exporter = EvidenceMarkdownExporter(dataset=state.dataset, run_id=state.run_id)
        markdown_dir = str(state.subdir("markdown"))
        paths = exporter.export_all(
            records=state.evidence_records,
            output_dir=markdown_dir,
            workbook_records=state.workbook_records,
            sheet_records=state.sheet_records,
            prescan_records=state.prescan_records,
            image_records=state.image_records,
            graph_records=state.mermaid_graph_records,
            node_records=state.mermaid_node_records,
            edge_records=state.mermaid_edge_records,
        )

        # Write a supplementary semantic detail file with table_type, column_roles, embeddings
        _write_semantic_detail_markdown(state, markdown_dir)

        logger.info("Markdown export: %d files → %s", len(paths), markdown_dir)
        for name, path in paths.items():
            logger.info("  %s → %s", name, path)
    except Exception as exc:
        state.record_error("stage11_markdown_export", exc)

    state.time_stage("11_markdown_export", _elapsed(t))


def _write_semantic_detail_markdown(state: PipelineState, markdown_dir: str) -> None:
    """Write semantic_records_detail.md with table_type, column_roles, text_for_embedding."""
    from pathlib import Path as _Path
    out = _Path(markdown_dir) / "semantic_records_detail.md"
    lines: list[str] = [
        "# Semantic Records Detail",
        "",
        f"Run: {state.run_id} | Dataset: {state.dataset}",
        "",
        "| # | RecordType | Sheet | TableType | ColumnRoles | TextForEmbedding (80ch) |",
        "|---|-----------|-------|-----------|-------------|-------------------------|",
    ]
    semantic_types = frozenset({
        "table_region", "table_row", "field_definition",
        "business_rule", "sheet_summary", "graph_candidate",
        "table_header_structure", "raw_table_markdown",
    })
    idx = 1
    for rec in state.evidence_records:
        if not hasattr(rec, "record_type"):
            continue
        if rec.record_type not in semantic_types:
            continue
        roles_str = "; ".join(
            f"{col}={role}" for col, role in (rec.column_roles or {}).items()
        )[:60]
        emb_preview = (rec.text_for_embedding or "")[:80].replace("|", "│")
        lines.append(
            f"| {idx} "
            f"| {rec.record_type} "
            f"| {rec.sheet_name} "
            f"| {rec.table_type or '-'} "
            f"| {roles_str or '-'} "
            f"| {emb_preview} |"
        )
        idx += 1
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote semantic detail markdown → %s (%d rows)", out, idx - 1)


def stage12_evidence_quality(state: PipelineState) -> None:
    _stage_header("12 — Evidence quality check")
    t = _timer()
    try:
        checker = EvidenceQualityChecker(dataset=state.dataset, run_id=state.run_id)
        state.quality_issues = checker.check_all(state.evidence_records)
        checker.write_report(issues=state.quality_issues, output_dir=str(state.output_dir))

        # Semantic evidence generation report
        _write_semantic_generation_report(state)

        logger.info(
            "Quality check: %d issues across %d records",
            len(state.quality_issues),
            len(state.evidence_records),
        )
    except Exception as exc:
        state.record_error("stage12_evidence_quality", exc)
    state.time_stage("12_evidence_quality", _elapsed(t))


def _write_semantic_generation_report(state: PipelineState) -> None:
    """Write reports/semantic_evidence_generation_report.md."""
    from collections import Counter
    type_counter: Counter[str] = Counter()
    for rec in state.evidence_records:
        if hasattr(rec, "record_type"):
            type_counter[rec.record_type] += 1

    table_type_counter: Counter[str] = Counter()
    for c in state.classifications:
        table_type_counter[c.get("table_type", "unknown_table")] += 1

    out = state.subdir("reports") / "semantic_evidence_generation_report.md"
    lines: list[str] = [
        "# Semantic Evidence Generation Report",
        "",
        f"Run: {state.run_id} | Dataset: {state.dataset}",
        "",
        "## Semantic Record Counts by Type",
        "",
        "| RecordType | Count |",
        "|-----------|-------|",
    ]
    semantic_types = [
        "table_region", "table_header_structure", "raw_table_markdown",
        "table_row", "field_definition", "business_rule",
        "sheet_summary", "graph_candidate",
    ]
    for rt in semantic_types:
        lines.append(f"| {rt} | {type_counter.get(rt, 0)} |")

    lines += [
        "",
        "## Table-Type Distribution",
        "",
        "| TableType | Count |",
        "|-----------|-------|",
    ]
    for tt, cnt in table_type_counter.most_common():
        lines.append(f"| {tt} | {cnt} |")

    total_edges = sum(
        len(r.graph_hints.get("candidate_edges", []))
        for r in state.graph_hint_records
        if hasattr(r, "graph_hints")
    )
    lines += [
        "",
        "## Graph Hints",
        "",
        f"- graph_candidate records: {len(state.graph_hint_records)}",
        f"- total candidate_edges: {total_edges}",
        "",
        "## Quality Issues",
        "",
        f"- Total issues: {len(state.quality_issues)}",
    ]

    error_count = sum(1 for i in state.quality_issues if i.get("severity") == "error")
    warn_count = sum(1 for i in state.quality_issues if i.get("severity") == "warning")
    lines += [
        f"  - errors: {error_count}",
        f"  - warnings: {warn_count}",
    ]

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote semantic evidence generation report → %s", out)


def stage13_run_report(state: PipelineState, pipeline_elapsed: float) -> None:
    _stage_header("12 — Run report generation")
    t = _timer()
    try:
        reporter = RunReporter(dataset=state.dataset, run_id=state.run_id)
        paths = reporter.generate_all(
            output_dir=str(state.output_dir),
            evidence_records=state.evidence_records,
            workbook_records=state.workbook_records,
            sheet_records=state.sheet_records,
            table_regions=state.table_regions,
            normalized_rows=state.normalized_rows,
            prescan_records=state.prescan_records,
            drawing_objects=state.drawing_objects,
            connectors=state.connectors,
            chart_objects=state.chart_objects,
            image_records=state.image_records,
            graph_records=state.mermaid_graph_records,
            node_records=state.mermaid_node_records,
            edge_records=state.mermaid_edge_records,
            visual_analysis_records=state.visual_analysis_records,
            elapsed_seconds=pipeline_elapsed,
            errors=state.errors,
        )
        logger.info("Run reports: %d files", len(paths))
    except Exception as exc:
        state.record_error("stage13_run_report", exc)

    state.time_stage("12_run_report", _elapsed(t))


def stage13_s3_upload(state: PipelineState, upload_s3_uri: str) -> None:
    _stage_header("13 — S3 upload")
    t = _timer()
    try:
        bucket, prefix = _parse_s3_uri(upload_s3_uri)
        region = state.config.get("aws_region", "ap-northeast-1")
        # append run_id to create versioned path, and set latest sibling
        target_prefix = f"{prefix.rstrip('/')}/{state.run_id}"
        latest_prefix = f"{prefix.rstrip('/')}/latest"
        uploader = S3OutputUploader(
            bucket=bucket,
            target_prefix=target_prefix,
            latest_prefix=latest_prefix,
            region=region,
            dataset=state.dataset,
            run_id=state.run_id,
        )
        result = uploader.upload(local_dir=str(state.output_dir))
        uploader.write_report(upload_result=result, output_dir=str(state.output_dir))

        if result.get("success"):
            logger.info("S3 upload succeeded → %s", result.get("target_uri"))
        else:
            err = f"S3 upload failed: {result.get('error', 'unknown')}"
            state.errors.append(f"[stage13] {err}")
            logger.error(err)
    except Exception as exc:
        state.record_error("stage13_s3_upload", exc)

    state.time_stage("13_s3_upload", _elapsed(t))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(state: PipelineState, total_elapsed: float) -> None:
    sep = "=" * 60
    print(sep)
    print(f"PIPELINE SUMMARY  run_id={state.run_id}")
    print(sep)
    print(f"  Dataset:            {state.dataset}")
    print(f"  Output dir:         {state.output_dir}")
    print(f"  Total elapsed:      {total_elapsed:.1f}s")
    print()
    print("  Counts:")
    print(f"    Excel workbooks:  {len(state.workbook_records)}")
    print(f"    Sheets:           {len(state.sheet_records)}")
    print(f"    Table regions:    {len(state.table_regions)}")
    print(f"    Normalized rows:  {len(state.normalized_rows)}")
    print(f"    Drawing objects:  {len(state.drawing_objects)}")
    print(f"    Connectors:       {len(state.connectors)}")
    print(f"    Charts:           {len(state.chart_objects)}")
    print(f"    Embedded images:  {len(state.image_records)}")
    print(f"    Mermaid graphs:   {len(state.mermaid_graph_records)}")
    print(f"    Mermaid nodes:    {len(state.mermaid_node_records)}")
    print(f"    Mermaid edges:    {len(state.mermaid_edge_records)}")
    print(f"    VLM analyses:     {len(state.visual_analysis_records)}")
    print(f"    Evidence records: {len(state.evidence_records)}")
    if state.evidence_jsonl_path:
        print(f"    JSONL output:     {state.evidence_jsonl_path}")
    print()
    print("  Stage timings:")
    for stage, elapsed in state.stage_timings.items():
        print(f"    {stage:40s}  {elapsed:.2f}s")
    print()
    if state.errors:
        print(f"  Errors ({len(state.errors)}):")
        for err in state.errors:
            print(f"    [!] {err}")
    else:
        print("  Errors: none")
    print(sep)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    logger.info("Starting evidence pipeline v1")
    logger.info("  run_id:     %s", args.run_id)
    logger.info("  dataset:    %s", args.dataset)
    logger.info("  s3_uri:     %s", args.s3_uri)
    logger.info("  output_dir: %s", args.output_dir)
    logger.info("  use_vision: %s", args.use_vision)
    logger.info("  upload_s3:  %s", args.upload_s3 or "(disabled)")

    state = PipelineState(
        dataset=args.dataset,
        run_id=args.run_id,
        output_dir=args.output_dir,
    )
    pipeline_start = _timer()

    # Critical stages: failure here means we skip downstream stages gracefully
    stage1_load_config(state, args.config)
    stage2_s3_discovery(state, args.s3_uri)

    # Excel processing chain
    stage3_excel_parse(state)
    stage4_table_parse(state)

    # Semantic enhancement stages (4a-4h)
    stage4a_classify_tables(state)
    stage4b_detect_header_roles(state)
    stage4c_semantic_table_rendering(state)
    stage4d_semantic_row_rendering(state)
    stage4e_field_definitions(state)
    stage4f_business_rules(state)
    stage4g_graph_hints(state)
    stage4h_alias_enrichment(state)

    stage5_visual_prescan(state)
    stage6_ooxml_visual_parse(state)
    stage7_image_extract(state)

    # Mermaid
    stage8_mermaid_parse(state)

    # Optional vision - auto-detect from .env if not explicitly set
    use_vision = args.use_vision
    if use_vision is None:
        # Auto-detect: enable if VLM model configured in environment
        use_vision = bool(os.environ.get("BEDROCK_VLM_MODEL_ID") or os.environ.get("VISION_LLM_MODEL_ID"))
        if use_vision:
            logger.info("Stage 9 — vision analysis: AUTO-ENABLED (VLM model found in .env)")

    if use_vision:
        stage9_vision_analysis(state)
    else:
        logger.info("Stage 9 — vision analysis: SKIPPED (--no-vision or no VLM model)")
        state.stage_timings["9_vision_analysis"] = 0.0

    # Record building and export
    stage10_build_evidence_records(state)
    stage11_markdown_export(state)

    # Quality check
    stage12_evidence_quality(state)

    total_so_far = _elapsed(pipeline_start)
    stage13_run_report(state, pipeline_elapsed=total_so_far)

    # Optional S3 upload
    if args.upload_s3:
        stage13_s3_upload(state, args.upload_s3)
    else:
        logger.info("Stage 13 — S3 upload: SKIPPED (--upload-s3 not provided)")
        state.stage_timings["13_s3_upload"] = 0.0

    total_elapsed = _elapsed(pipeline_start)
    print_summary(state, total_elapsed)

    # Exit code: 0 if critical stages produced evidence records (or at least ran)
    critical_failures = [e for e in state.errors if any(
        tag in e for tag in ["stage1_", "stage2_", "stage10_"]
    )]
    if critical_failures:
        logger.error("Critical stage failures detected — exit 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
