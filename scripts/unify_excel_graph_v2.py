#!/usr/bin/env python3
"""
Unify Excel graph — CLI entry point for X4 pipeline.

Usage:
    PYTHONPATH=src python scripts/unify_excel_graph_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1

    # Dry run:
    PYTHONPATH=src python scripts/unify_excel_graph_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="X4: Unify Excel Graph (Entity Resolution + Cross-Layer + Evidence Link)"
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

    # Run pipeline
    from hermes_bedrock_agent.v2.pipelines.unify_excel_graph import (
        run_unify_graph_pipeline,
    )

    summary = run_unify_graph_pipeline(
        config_path=args.config,
        run_id=run_id,
        dataset=dataset,
        output_dir=output_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("X4: Unify Excel Graph — Summary")
    print("=" * 60)
    print(f"Decision: {summary['decision']}")
    print(f"Mode: {'DRY-RUN' if summary['dry_run'] else 'ACTUAL'}")
    print(f"")
    print(f"Input: biz={summary['input_biz_nodes']}n/{summary['input_biz_edges']}e, "
          f"impl={summary['input_impl_nodes']}n/{summary['input_impl_edges']}e")
    print(f"")
    print(f"Entity Resolution:")
    print(f"  Merged nodes: {summary['entity_merged_nodes']}")
    print(f"  Merged edges: {summary['entity_merged_edges']}")
    print(f"  Aliases: {summary['alias_count']}")
    print(f"")
    print(f"Cross-Layer Links: {summary['cross_layer_links']}")
    print(f"  By strategy: {summary['cross_layer_by_strategy']}")
    print(f"  By relation: {summary['cross_layer_by_relation']}")
    print(f"")
    print(f"Quality Filter:")
    print(f"  Filtered nodes: {summary['filtered_nodes']}")
    print(f"  Filtered edges: {summary['filtered_edges']}")
    print(f"  Rejected: {summary['rejected_count']}")
    print(f"")
    print(f"Evidence Links:")
    print(f"  Linked nodes: {summary['linked_nodes']}")
    print(f"  Linked edges: {summary['linked_edges']}")
    print(f"  Total links: {summary['evidence_links']}")
    print(f"  Node coverage: {summary['node_evidence_coverage']:.1%}")
    print(f"  Edge coverage: {summary['edge_evidence_coverage']:.1%}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
