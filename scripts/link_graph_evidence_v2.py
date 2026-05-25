#!/usr/bin/env python
"""
CLI wrapper for Stage 08: Evidence Linker.

Usage:
    PYTHONPATH=src python scripts/link_graph_evidence_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --dry-run

    PYTHONPATH=src python scripts/link_graph_evidence_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from hermes_bedrock_agent.v2.pipelines.link_graph_evidence import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Stage 08: Evidence Linker"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/murata_semantic_v2.yaml",
        help="Path to config YAML (currently unused, for future extension)",
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
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (report only, no final outputs)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Stage 08: Evidence Linker")
    print("=" * 60)
    print(f"  Run ID:     {args.run_id}")
    print(f"  Dataset:    {args.dataset}")
    print(f"  Output Dir: {args.output_dir}")
    print(f"  Dry Run:    {args.dry_run}")
    print("=" * 60)
    print()

    start = time.time()
    result = run_pipeline(
        output_dir=args.output_dir,
        run_id=args.run_id,
        dataset=args.dataset,
        dry_run=args.dry_run,
    )
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
