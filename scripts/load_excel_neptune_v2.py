#!/usr/bin/env python3
"""
Load Excel graph into Neptune — CLI entry point for X5 pipeline.

Usage (dry-run, default — Cypher export only):
    PYTHONPATH=src python scripts/load_excel_neptune_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1 \
        --layer all \
        --dry-run \
        --export-cypher data/outputs/sample_20260519_excel_v1/load_neptune.cypher

Usage (execute — clear existing graph and load new):
    PYTHONPATH=src python scripts/load_excel_neptune_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1 \
        --layer all \
        --execute \
        --clear-before-load \
        --export-cypher data/outputs/sample_20260519_excel_v1/load_neptune.cypher

IMPORTANT: --execute requires --clear-before-load for this dataset
           to avoid mixing with existing Murata graph data.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


def main():
    parser = argparse.ArgumentParser(
        description="X5: Load Excel Graph into Neptune"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/sample_20260519_excel_v1.yaml",
        help="Path to config YAML",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="sample_20260519_excel_v1",
        help="Run ID for this pipeline execution",
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
        help="Output directory for graph data",
    )
    parser.add_argument(
        "--layer",
        type=str,
        choices=["business", "implementation", "evidence", "all"],
        default="all",
        help="Which graph layer to export (default: all)",
    )
    parser.add_argument(
        "--export-cypher",
        type=str,
        default=None,
        help="Path to write Cypher export file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate and export only (no Neptune connection)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually execute Neptune load (requires --clear-before-load)",
    )
    parser.add_argument(
        "--clear-before-load",
        action="store_true",
        default=False,
        help="Clear existing Neptune graph before loading (DESTRUCTIVE)",
    )
    parser.add_argument(
        "--neptune-graph-id",
        type=str,
        default="",
        help="Neptune graph ID (or set NEPTUNE_GRAPH_ID env)",
    )
    parser.add_argument(
        "--neptune-region",
        type=str,
        default="ap-northeast-1",
        help="Neptune AWS region",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Batch size for Neptune queries (default: 50)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Delay between batches in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    # Safety checks
    if args.clear_before_load and not args.execute:
        print("ERROR: --clear-before-load requires --execute")
        return 1

    if args.execute and not args.clear_before_load:
        print("ERROR: --execute requires --clear-before-load for this dataset")
        print("       (to avoid mixing with existing graph data)")
        return 1

    # Resolve Neptune config
    neptune_graph_id = (
        args.neptune_graph_id
        or os.environ.get("NEPTUNE_GRAPH_ID", "")
    )
    if not neptune_graph_id:
        try:
            import yaml
            with open(args.config) as f:
                cfg = yaml.safe_load(f)
            neptune_graph_id = cfg.get("neptune", {}).get("graph_id", "")
        except Exception:
            pass

    # If --execute is set, disable dry_run
    effective_dry_run = not args.execute

    print("=" * 60)
    print("X5: Excel Neptune Export and Load")
    print("=" * 60)
    print(f"  Run ID:          {args.run_id}")
    print(f"  Dataset:         {args.dataset}")
    print(f"  Output Dir:      {args.output_dir}")
    print(f"  Layer:           {args.layer}")
    print(f"  Mode:            {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"  Clear first:     {args.clear_before_load}")
    print(f"  Neptune ID:      {neptune_graph_id or 'NOT SET'}")
    print(f"  Neptune Region:  {args.neptune_region}")
    print(f"  Batch size:      {args.batch_size}")
    print(f"  Delay:           {args.delay}s")
    if args.export_cypher:
        print(f"  Cypher output:   {args.export_cypher}")
    print("=" * 60)
    print()

    from hermes_bedrock_agent.v2.pipelines.load_excel_neptune import run_pipeline

    start = time.time()
    result = run_pipeline(
        output_dir=args.output_dir,
        run_id=args.run_id,
        dataset=args.dataset,
        layer=args.layer,
        dry_run=effective_dry_run,
        execute=args.execute,
        clear_before_load=args.clear_before_load,
        cypher_output_path=args.export_cypher,
        neptune_graph_id=neptune_graph_id,
        neptune_region=args.neptune_region,
        batch_size=args.batch_size,
        delay=args.delay,
    )
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
