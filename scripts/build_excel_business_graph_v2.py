#!/usr/bin/env python3
"""
Build Excel business graph — CLI entry point for X3 pipeline.

Usage:
    PYTHONPATH=src python scripts/build_excel_business_graph_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1

    # Dry run:
    PYTHONPATH=src python scripts/build_excel_business_graph_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="X3: Build Excel Business Graph"
    )
    parser.add_argument("--config", type=str, help="Config YAML path")
    parser.add_argument("--run-id", type=str, default="sample_20260519_excel_v1")
    parser.add_argument("--dataset", type=str, default="sample_20260519")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/outputs/sample_20260519_excel_v1",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--clean-output", action="store_true",
        help="Remove business_nodes/edges before run (safe: only touches this run_id)"
    )

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

    # Override from CLI
    run_id = args.run_id or config.get("run_id", "sample_20260519_excel_v1")
    dataset = args.dataset or config.get("dataset", "sample_20260519")
    output_dir = args.output_dir or config.get("output_dir", "data/outputs/sample_20260519_excel_v1")

    # Safety: only clean this run_id's business outputs
    if args.clean_output:
        out_path = Path(output_dir)
        for fname in [
            "business_nodes.jsonl",
            "business_edges.jsonl",
            "rejected_excel_business_graph_items.jsonl",
            "low_confidence_excel_business_items.jsonl",
            "excel_business_candidate_evidence.jsonl",
            "excel_business_graph_report.md",
        ]:
            target = out_path / fname
            if target.exists():
                target.unlink()
                logging.info(f"Cleaned: {target}")

    # Run pipeline
    from hermes_bedrock_agent.v2.pipelines.build_excel_business_graph import (
        run_business_graph_pipeline,
    )

    summary = run_business_graph_pipeline(
        config_path=args.config,
        run_id=run_id,
        dataset=dataset,
        output_dir=output_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("X3: Excel Business Graph Extraction — Summary")
    print("=" * 60)
    print(f"Decision: {summary['decision']}")
    print(f"Mode: {'DRY-RUN' if summary['dry_run'] else 'ACTUAL'}")
    print(f"Total nodes: {summary['total_nodes']}")
    print(f"Total edges: {summary['total_edges']}")
    print(f"  BusinessProcess: {summary['process_count']}")
    print(f"  BusinessStep: {summary['step_count']}")
    print(f"  BusinessRule: {summary['rule_count']}")
    print(f"  BusinessTerm: {summary['term_count']}")
    print(f"  Function: {summary['function_count']}")
    print(f"  BusinessDomain: {summary['domain_count']}")
    print(f"Evidence coverage (nodes): {summary['evidence_coverage_nodes']:.1%}")
    print(f"Evidence coverage (edges): {summary['evidence_coverage_edges']:.1%}")
    print(f"Rejected: {summary['rejected_count']}")
    print(f"Low-confidence: {summary['low_confidence_count']}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
