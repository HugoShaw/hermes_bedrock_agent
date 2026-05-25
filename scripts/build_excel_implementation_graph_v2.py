#!/usr/bin/env python3
"""
Build Excel implementation graph — CLI entry point for X2 pipeline.

Usage:
    PYTHONPATH=src python scripts/build_excel_implementation_graph_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1

    Add --dry-run to preview extraction without writing files.
    Add --verbose for detailed logging.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="X2: Build Excel Implementation Graph"
    )
    parser.add_argument("--config", type=str, help="Config YAML file path")
    parser.add_argument("--run-id", type=str, default="sample_20260519_excel_v1")
    parser.add_argument("--dataset", type=str, default="sample_20260519")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/outputs/sample_20260519_excel_v1",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview extraction without writing graph files",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config if provided
    config = {}
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            import yaml
            config = yaml.safe_load(config_path.read_text()) or {}
            logging.info(f"Loaded config from {config_path}")
        else:
            logging.warning(f"Config file not found: {config_path}")

    # Override with CLI args
    dataset = args.dataset or config.get("dataset", "sample_20260519")
    run_id = args.run_id or config.get("run_id", "sample_20260519_excel_v1")
    output_dir = args.output_dir or config.get("output_dir", "data/outputs/sample_20260519_excel_v1")

    # Safety check: never write to murata output
    if "murata" in str(output_dir).lower():
        logging.error("SAFETY: Cannot write to murata output directory!")
        return 1

    # Run pipeline
    from hermes_bedrock_agent.v2.pipelines.build_excel_implementation_graph import (
        BuildExcelImplementationGraphPipeline,
    )

    pipeline = BuildExcelImplementationGraphPipeline(
        config=config,
        dataset=dataset,
        run_id=run_id,
        output_dir=output_dir,
    )

    try:
        result = pipeline.run(dry_run=args.dry_run)
    except Exception as e:
        logging.error(f"Pipeline failed: {e}", exc_info=True)
        return 1

    # Print summary
    print("\n" + "=" * 60)
    print("X2: Excel Implementation Graph Extraction — Results")
    print("=" * 60)
    print(f"Dry run: {result.get('dry_run', False)}")
    print(f"Nodes extracted: {result.get('node_count', 0)}")
    print(f"Edges extracted: {result.get('edge_count', 0)}")
    print(f"MAPS_TO edges: {result.get('maps_to_count', 0)}")
    print(f"Rejected: {result.get('rejected_count', 0)}")
    print(f"Low-confidence: {result.get('low_confidence_count', 0)}")

    stats = result.get("stats", {})
    print(f"\nNode labels: {stats.get('node_count_by_label', {})}")
    print(f"Edge relations: {stats.get('edge_count_by_relation', {})}")
    print(f"Evidence coverage (nodes): {stats.get('evidence_coverage_nodes', 0):.1%}")
    print(f"Evidence coverage (edges): {stats.get('evidence_coverage_edges', 0):.1%}")
    print(f"\nReport: {result.get('report_path', 'N/A')}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
