#!/usr/bin/env python3
"""
Review Excel evidence quality — CLI entry point for the X1 review pipeline.

Usage:
    PYTHONPATH=src python scripts/review_excel_evidence_quality_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1 \
        --sample-size 30 \
        --export-samples
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from hermes_bedrock_agent.v2.pipelines.review_excel_evidence_quality import (
    ReviewExcelEvidenceQualityPipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review Excel evidence quality and GraphRAG readiness (X1 stage)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/sample_20260519_excel_v1.yaml",
        help="Path to project YAML config",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="sample_20260519_excel_v1",
        help="Run identifier",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="sample_20260519",
        help="Dataset name",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/outputs/sample_20260519_excel_v1",
        help="Output directory (must contain X0 outputs)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=30,
        help="Number of samples to export for review",
    )
    parser.add_argument(
        "--export-samples",
        action="store_true",
        help="Export human-readable sample files",
    )
    parser.add_argument(
        "--fix-safe-issues",
        action="store_true",
        help="Apply safe fixes (writes to *_reviewed.jsonl, does not overwrite originals)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config
    config = {}
    config_path = Path(args.config)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        logging.info(f"Loaded config from {config_path}")
    else:
        logging.warning(f"Config not found: {config_path}, using defaults")

    # Validate output directory has X0 data
    output_dir = Path(args.output_dir)
    required_files = [
        "evidence_chunks.jsonl",
        "excel_sheets.jsonl",
        "excel_table_regions.jsonl",
        "excel_rows_normalized.jsonl",
    ]
    missing = [f for f in required_files if not (output_dir / f).exists()]
    if missing:
        logging.error(f"Missing required X0 outputs in {output_dir}: {missing}")
        logging.error("Run X0 profiling first: scripts/profile_excel_workbook_v2.py")
        return 1

    # Run pipeline
    pipeline = ReviewExcelEvidenceQualityPipeline(
        config=config,
        output_dir=output_dir,
        dataset=args.dataset,
        run_id=args.run_id,
        sample_size=args.sample_size,
        export_samples=args.export_samples,
        fix_safe_issues=args.fix_safe_issues,
    )

    try:
        results = pipeline.run()
    except Exception as e:
        logging.error(f"Pipeline failed: {e}", exc_info=True)
        return 1

    # Print final summary
    decision = results.get("decision", {})
    print()
    print("=" * 60)
    print("X1 REVIEW COMPLETE")
    print("=" * 60)
    print()
    print(f"  Decision: {decision.get('verdict', 'UNKNOWN')}")
    print(f"  Reasons: {'; '.join(decision.get('reasons', []))}")
    if decision.get("risks"):
        print(f"  Risks: {'; '.join(decision.get('risks', []))}")
    print()

    qs = results.get("quality_summary", {})
    print(f"  Evidence chunks: {qs.get('total_chunks', 0)}")
    print(f"  Avg quality score: {qs.get('avg_score', 0)}")
    print(f"  Ready: {qs.get('readiness_counts', {}).get('ready', 0)}")
    print(f"  Caution: {qs.get('readiness_counts', {}).get('caution', 0)}")
    print(f"  Exclude: {qs.get('readiness_counts', {}).get('exclude', 0)}")
    print()

    rs = results.get("readiness_summary", {})
    print(f"  Business Graph candidate sheets: {rs.get('business_graph_candidates', 0)}")
    print(f"  Implementation Graph candidate sheets: {rs.get('implementation_graph_candidates', 0)}")
    print(f"  Low-confidence sheets: {rs.get('low_confidence_sheets', 0)}")
    print()

    print("  Generated files:")
    for report in results.get("reports_generated", []):
        print(f"    {report}")
    for sample in results.get("sample_files", []):
        print(f"    {sample}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
