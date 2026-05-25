#!/usr/bin/env python
"""
CLI wrapper for Stage 09: Neptune Export and Loader.

Usage (dry-run, default — Cypher export only):
    PYTHONPATH=src python scripts/load_neptune_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --layer all \
        --dry-run \
        --export-cypher data/outputs/murata_semantic_v2/load_neptune.cypher

Usage (execute — actual Neptune write, requires explicit flag):
    PYTHONPATH=src python scripts/load_neptune_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --layer all \
        --execute

Usage (clear + execute — destructive, requires both flags):
    PYTHONPATH=src python scripts/load_neptune_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --layer all \
        --execute --clear-before-load
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from hermes_bedrock_agent.v2.pipelines.load_neptune_v2 import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Stage 09: Neptune Export and Loader"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/murata_semantic_v2.yaml",
        help="Path to config YAML",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="murata_semantic_v2",
        help="Run ID for this pipeline execution",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="murata",
        help="Dataset name",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/outputs/murata_semantic_v2",
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
        help="Custom Cypher output file path (default: auto-generated based on layer)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run mode: export Cypher, validate, no Neptune writes (default)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="EXECUTE mode: actually write to Neptune (requires config)",
    )
    parser.add_argument(
        "--clear-before-load",
        action="store_true",
        default=False,
        help="Clear Neptune graph before loading (requires --execute)",
    )
    parser.add_argument(
        "--neptune-graph-id",
        type=str,
        default="",
        help="Neptune graph ID (overrides config/env)",
    )
    parser.add_argument(
        "--neptune-region",
        type=str,
        default="ap-northeast-1",
        help="Neptune region (default: ap-northeast-1)",
    )

    args = parser.parse_args()

    # Resolve Neptune config from args, env, or config file
    neptune_graph_id = (
        args.neptune_graph_id
        or os.environ.get("NEPTUNE_GRAPH_ID", "")
    )
    # Try reading from YAML if not set
    if not neptune_graph_id:
        try:
            import yaml
            with open(args.config) as f:
                cfg = yaml.safe_load(f)
            neptune_graph_id = cfg.get("neptune", {}).get("graph_id", "")
        except Exception:
            pass

    # Safety check
    if args.clear_before_load and not args.execute:
        print("ERROR: --clear-before-load requires --execute")
        return 1

    # If --execute is set, disable dry_run
    effective_dry_run = not args.execute

    print("=" * 60)
    print("Stage 09: Neptune Export and Loader")
    print("=" * 60)
    print(f"  Run ID:        {args.run_id}")
    print(f"  Dataset:       {args.dataset}")
    print(f"  Output Dir:    {args.output_dir}")
    print(f"  Layer:         {args.layer}")
    print(f"  Mode:          {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"  Clear first:   {args.clear_before_load}")
    print(f"  Neptune ID:    {neptune_graph_id or 'NOT SET'}")
    print(f"  Neptune Region:{args.neptune_region}")
    if args.export_cypher:
        print(f"  Cypher output: {args.export_cypher}")
    print("=" * 60)
    print()

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
    )
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
