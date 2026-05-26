#!/usr/bin/env python
"""
CLI wrapper for Stage 10: Test Retriever V2.

Full test suite:
    PYTHONPATH=src python scripts/test_retriever_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata

Single query debug:
    PYTHONPATH=src python scripts/test_retriever_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --query "支払申請の業務プロセスを説明してください。" \
      --debug
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from hermes_bedrock_agent.v2.pipelines.test_retriever_v2 import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Stage 10: Test Retriever V2"
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
        help="Run ID",
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
        help="Output directory",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Single query to test (debug mode)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug output",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Stage 10: Test Retriever V2")
    print("=" * 60)
    print(f"  Run ID:     {args.run_id}")
    print(f"  Dataset:    {args.dataset}")
    print(f"  Output Dir: {args.output_dir}")
    if args.query:
        print(f"  Query:      {args.query[:60]}...")
    print(f"  Debug:      {args.debug}")
    print("=" * 60)
    print()

    start = time.time()
    result = run_pipeline(
        output_dir=args.output_dir,
        run_id=args.run_id,
        dataset=args.dataset,
        single_query=args.query,
        debug=args.debug,
    )
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
