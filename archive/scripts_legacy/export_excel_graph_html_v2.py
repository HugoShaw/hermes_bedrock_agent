#!/usr/bin/env python3
"""
Export Excel graph as interactive HTML visualization — CLI entry point for X6.

Usage (from Neptune):
    PYTHONPATH=src python scripts/export_excel_graph_html_v2.py \
      --config configs/sample_20260519_excel_v1.yaml \
      --run-id sample_20260519_excel_v1 \
      --dataset sample_20260519 \
      --output-dir data/outputs/sample_20260519_excel_v1/visualization \
      --source neptune \
      --layout force

Usage (JSONL fallback):
    PYTHONPATH=src python scripts/export_excel_graph_html_v2.py \
      --config configs/sample_20260519_excel_v1.yaml \
      --run-id sample_20260519_excel_v1 \
      --dataset sample_20260519 \
      --output-dir data/outputs/sample_20260519_excel_v1/visualization \
      --source jsonl \
      --layout force
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(
        description="Export Excel graph as interactive HTML visualization (X6)"
    )
    parser.add_argument("--config", required=True, help="Config YAML path")
    parser.add_argument("--run-id", required=True, help="Run ID")
    parser.add_argument("--dataset", required=True, help="Dataset name")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--source", choices=["neptune", "jsonl"], default="neptune",
        help="Data source: neptune (live query) or jsonl (local files)"
    )
    parser.add_argument(
        "--layout", choices=["force", "hierarchical"], default="force",
        help="Graph layout algorithm"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    print("=" * 60)
    print("X6: Excel Neptune Full Graph HTML Visualization Export")
    print("=" * 60)
    print(f"  Run ID:       {args.run_id}")
    print(f"  Dataset:      {args.dataset}")
    print(f"  Output Dir:   {args.output_dir}")
    print(f"  Source:       {args.source}")
    print(f"  Layout:       {args.layout}")
    print("=" * 60)
    print()

    start = time.time()

    from hermes_bedrock_agent.v2.pipelines.export_excel_graph_html import (
        run_export_pipeline,
    )

    result = run_export_pipeline(
        config=config,
        run_id=args.run_id,
        dataset=args.dataset,
        output_dir=args.output_dir,
        source=args.source,
        layout=args.layout,
    )

    elapsed = time.time() - start

    print()
    print("[X6] RESULTS")
    print(f"  Source: {result['source']}")
    print(f"  Nodes exported: {result['node_count']}")
    print(f"  Edges exported: {result['edge_count']}")
    print()
    print("  Label counts:")
    for label, count in sorted(result["label_counts"].items(), key=lambda x: -x[1]):
        print(f"    {label}: {count}")
    print()
    print("  Relation counts:")
    for rel, count in sorted(result["rel_counts"].items(), key=lambda x: -x[1]):
        print(f"    {rel}: {count}")
    print()
    print("  Validation:")
    for key, val in result["validation"].items():
        print(f"    {key}: {val}")
    print()
    print("  Generated files:")
    for f in sorted(result["generated_files"]):
        print(f"    {f}")
    print()
    print(f"Completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
