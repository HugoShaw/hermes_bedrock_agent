"""Main pipeline orchestrator.

Coordinates all stages:
  inventory -> atlas -> parse_plan -> execution -> normalization -> review

Usage:
    from app.excel_parse_pipeline.pipeline import run_pipeline
    from app.excel_parse_pipeline.config import PipelineConfig
    run_pipeline(PipelineConfig())
"""
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .config import PipelineConfig
from .io.s3_io import S3IO
from .inventory.source_scanner import scan_sources, download_source_files, save_manifest
from .atlas.workbook_atlas import build_workbook_atlas, save_workbook_atlas, save_sheet_atlases
from .atlas.region_detector import detect_regions, save_region_atlas
from .planning.parse_plan_generator import (
    generate_parse_plan, save_parse_plan, generate_plan_review
)
from .execution.parse_plan_executor import ParsePlanExecutor, save_execution_results
from .execution.mermaid_parser import parse_mermaid_file, save_mermaid_results
from .normalization.graph_builder import normalize_to_graph, save_graph
from .normalization.kb_chunk_builder import build_kb_chunks
from .review.html_review_builder import build_review_html
from .review.quality_report import generate_quality_report

logger = logging.getLogger(__name__)


def run_pipeline(config: Optional[PipelineConfig] = None) -> dict:
    """Run the full parse pipeline end-to-end."""
    if config is None:
        config = PipelineConfig()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Ensure output directories
    config.ensure_dirs()
    output_dir = config.output_dir

    logger.info("=" * 60)
    logger.info("Excel Parse Pipeline - Starting")
    logger.info(f"  Input: s3://{config.s3_bucket}/{config.s3_input_prefix}")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 60)

    start_time = time.time()

    # ----- Stage 1: Source Inventory -----
    logger.info("Stage 1: Source Inventory")
    manifest = scan_sources(config)
    save_manifest(config, manifest)
    
    excel_count = manifest["scan_summary"]["excel_files"]
    mermaid_count = manifest["scan_summary"]["mermaid_files"]
    logger.info(f"  Found {excel_count} Excel files, {mermaid_count} Mermaid files")

    # ----- Stage 2: Download Files -----
    logger.info("Stage 2: Download Files")
    downloaded = download_source_files(config, manifest)
    logger.info(f"  Downloaded {len(downloaded)} files to {config.downloads_dir}")

    # ----- Stage 3: Build Atlas + Detect Regions -----
    logger.info("Stage 3: Workbook Atlas + Region Detection")
    workbook_atlases = []
    all_regions_by_workbook = {}  # wb_name -> {sheet_name -> [regions]}

    for excel_file in manifest["excel_files"]:
        local_path = excel_file.get("local_path")
        if not local_path:
            continue

        wb_filename = Path(local_path).name
        logger.info(f"  Building atlas: {wb_filename}")
        try:
            atlas = build_workbook_atlas(local_path)
            atlas["source_s3_key"] = excel_file["key"]
            workbook_atlases.append(atlas)

            # Detect regions for each sheet
            regions_by_sheet = {}
            for sheet in atlas.get("sheets", []):
                regions = detect_regions(sheet)
                regions_by_sheet[sheet["sheet_name"]] = regions

            all_regions_by_workbook[atlas["workbook_name"]] = regions_by_sheet

        except Exception as e:
            logger.error(f"  Error processing {wb_filename}: {e}", exc_info=True)

    # Save atlases
    if workbook_atlases:
        for atlas in workbook_atlases:
            save_workbook_atlas(atlas, output_dir)
            save_sheet_atlases(atlas, output_dir)
        
        # Save combined region atlas
        combined_regions = {}
        for wb_name, sheets in all_regions_by_workbook.items():
            for sheet_name, regions in sheets.items():
                combined_regions[sheet_name] = regions
        save_region_atlas(combined_regions, output_dir)

    logger.info(f"  Atlases built for {len(workbook_atlases)} workbooks")

    # ----- Stage 4: Parse Plan Generation -----
    logger.info("Stage 4: AI Parse Plan Generation")
    parse_plans = []

    all_sheet_plans = []
    all_region_plans = []

    for atlas in workbook_atlases:
        wb_name = atlas["workbook_name"]
        regions_by_sheet = all_regions_by_workbook.get(wb_name, {})

        logger.info(f"  Generating parse plan for: {wb_name}")
        try:
            plan = generate_parse_plan(atlas, regions_by_sheet, config)
            parse_plans.append(plan)
        except Exception as e:
            logger.error(f"  Parse plan generation failed for {wb_name}: {e}", exc_info=True)
            parse_plans.append({
                "workbook_name": wb_name,
                "workbook_type": "unknown",
                "confidence": 0.0,
                "sheets": [],
                "global_uncertainties": [f"Complete failure: {str(e)}"],
                "human_review_required": ["entire_workbook"],
            })

        # Collect sheet/region plans for combined JSONL
        current_plan = parse_plans[-1]
        for sheet in current_plan.get("sheets", []):
            all_sheet_plans.append(sheet)
            for region in sheet.get("regions", []):
                all_region_plans.append({"workbook": wb_name, "sheet_name": sheet["sheet_name"], **region})

    # Save combined parse plan artifacts
    plans_dir = output_dir / "parse_plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    # Save all workbook plans as a list
    all_plans_path = plans_dir / "workbook_parse_plan.json"
    with open(all_plans_path, "w", encoding="utf-8") as f:
        json.dump(parse_plans, f, ensure_ascii=False, indent=2, default=str)

    # Sheet plans JSONL
    with open(plans_dir / "sheet_parse_plans.jsonl", "w", encoding="utf-8") as f:
        for sp in all_sheet_plans:
            f.write(json.dumps(sp, ensure_ascii=False, default=str) + "\n")

    # Region plans JSONL
    with open(plans_dir / "region_parse_plans.jsonl", "w", encoding="utf-8") as f:
        for rp in all_region_plans:
            f.write(json.dumps(rp, ensure_ascii=False, default=str) + "\n")

    # Generate combined review
    generate_plan_review({"workbook_name": "all", "sheets": all_sheet_plans,
                          "global_uncertainties": [], "human_review_required": []}, output_dir)

    logger.info(f"  Generated {len(parse_plans)} parse plans")

    # ----- Stage 5: Parse Plan Execution -----
    logger.info("Stage 5: Parse Plan Execution")
    execution_results_list = []

    for i, plan in enumerate(parse_plans):
        wb_name = plan.get("workbook_name", f"workbook_{i}")

        # Find corresponding local file
        local_path = None
        for excel_file in manifest["excel_files"]:
            lpath = excel_file.get("local_path")
            if lpath and Path(lpath).name == wb_name:
                local_path = lpath
                break

        if not local_path:
            # Fallback: match by index
            if i < len(manifest["excel_files"]):
                local_path = manifest["excel_files"][i].get("local_path")

        if local_path:
            logger.info(f"  Executing plan for: {wb_name}")
            try:
                executor = ParsePlanExecutor(local_path, plan, config)
                results = executor.execute()
                execution_results_list.append(results)
                save_execution_results(results, output_dir)
            except Exception as e:
                logger.error(f"  Execution failed for {wb_name}: {e}", exc_info=True)
                execution_results_list.append(_empty_results())
        else:
            logger.warning(f"  No local file found for: {wb_name}")
            execution_results_list.append(_empty_results())

    logger.info(f"  Execution complete for {len(execution_results_list)} workbooks")

    # ----- Stage 6: Mermaid Parsing -----
    logger.info("Stage 6: Mermaid File Parsing")
    mermaid_results = []

    for mermaid_file in manifest.get("mermaid_files", []):
        local_path = mermaid_file.get("local_path")
        if not local_path:
            continue

        logger.info(f"  Parsing Mermaid: {Path(local_path).name}")
        try:
            related_wb = _infer_related_workbook(Path(local_path).name, workbook_atlases)
            result = parse_mermaid_file(
                local_path,
                related_workbook=related_wb,
                related_sheet=""
            )
            result["s3_key"] = mermaid_file["key"]
            mermaid_results.append(result)
        except Exception as e:
            logger.error(f"  Mermaid parse failed for {local_path}: {e}")

    if mermaid_results:
        save_mermaid_results(mermaid_results, output_dir)
    logger.info(f"  Parsed {len(mermaid_results)} Mermaid files")

    # ----- Stage 7: GraphRAG Normalization -----
    logger.info("Stage 7: GraphRAG Normalization")
    all_graph = {"nodes": [], "edges": []}

    for atlas, plan, exec_results in zip(workbook_atlases, parse_plans, execution_results_list):
        graph = normalize_to_graph(exec_results, mermaid_results, plan, atlas)
        all_graph["nodes"].extend(graph["nodes"])
        all_graph["edges"].extend(graph["edges"])

    # Mermaid-only (not tied to workbooks)
    if mermaid_results and not workbook_atlases:
        for mermaid in mermaid_results:
            graph = normalize_to_graph(_empty_results(), [mermaid], {}, {"workbook_name": "standalone"})
            all_graph["nodes"].extend(graph["nodes"])
            all_graph["edges"].extend(graph["edges"])

    graph_stats = save_graph(all_graph, output_dir)
    logger.info(f"  Graph: {graph_stats['nodes']['count']} nodes, "
                f"{graph_stats['edges']['count']} edges")

    # ----- Stage 8: KB Chunks -----
    logger.info("Stage 8: KB Chunk Generation")
    kb_results = {}

    for atlas, plan, exec_results in zip(workbook_atlases, parse_plans, execution_results_list):
        kb = build_kb_chunks(atlas, plan, exec_results, mermaid_results, output_dir)
        kb_results.update(kb)

    logger.info(f"  Generated {len(kb_results)} KB chunk files")

    # ----- Stage 9: Quality Report -----
    logger.info("Stage 9: Quality Report")
    quality_report = generate_quality_report(
        manifest, workbook_atlases, parse_plans,
        execution_results_list, mermaid_results, graph_stats, output_dir
    )
    logger.info(f"  Issues: {len(quality_report.get('issues', []))}")
    logger.info(f"  Human review items: {len(quality_report.get('human_review_required', []))}")

    # ----- Stage 10: HTML Review -----
    logger.info("Stage 10: HTML Review Reports")
    review_results = {}

    for atlas, plan, exec_results in zip(workbook_atlases, parse_plans, execution_results_list):
        reviews = build_review_html(atlas, plan, exec_results, mermaid_results, quality_report, output_dir)
        review_results.update(reviews)

    logger.info(f"  Generated {len(review_results)} review HTML files")

    # ----- Stage 11: S3 Sync -----
    logger.info("Stage 11: S3 Output Sync")
    s3_synced = False
    if config.s3_output_prefix:
        try:
            s3 = S3IO(config.s3_bucket, config.aws_region)
            s3.sync_directory(output_dir, config.s3_output_prefix)
            s3_synced = True
            logger.info(f"  Synced to s3://{config.s3_bucket}/{config.s3_output_prefix}")
        except Exception as e:
            logger.warning(f"  S3 sync failed (non-fatal): {e}")

    # ----- Final Summary -----
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Pipeline Complete")
    logger.info(f"  Duration: {elapsed:.1f}s")
    logger.info(f"  Output: {output_dir}")
    if s3_synced:
        logger.info(f"  S3 output: s3://{config.s3_bucket}/{config.s3_output_prefix}")
    logger.info("=" * 60)

    return {
        "status": "complete",
        "duration_seconds": elapsed,
        "output_dir": str(output_dir),
        "s3_synced": s3_synced,
        "statistics": quality_report.get("statistics", {}),
        "issue_count": len(quality_report.get("issues", [])),
        "human_review_count": len(quality_report.get("human_review_required", [])),
    }


def _empty_results() -> dict:
    """Return empty execution results."""
    return {
        "tables": [],
        "fields": [],
        "mappings": [],
        "transformations": [],
        "conditions": [],
        "uncertain_records": [],
        "unresolved_references": [],
    }


def _infer_related_workbook(mermaid_filename: str, atlases: list) -> str:
    """Try to infer which workbook a Mermaid file relates to."""
    stem = Path(mermaid_filename).stem.lower()
    for atlas in atlases:
        wb_name = atlas.get("workbook_name", "").lower()
        if len(stem) > 3 and len(wb_name) > 3:
            if stem[:5] in wb_name or wb_name[:5] in stem:
                return atlas.get("workbook_name", "")
    return ""
