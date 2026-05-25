#!/usr/bin/env python
"""
CLI wrapper for Stage 06: Build Implementation Graph.

Usage:
    PYTHONPATH=src python scripts/build_implementation_graph_v2.py \\
        --config configs/murata_semantic_v2.yaml \\
        --run-id murata_semantic_v2 \\
        --dataset murata \\
        --dry-run

    PYTHONPATH=src python scripts/build_implementation_graph_v2.py \\
        --config configs/murata_semantic_v2.yaml \\
        --run-id murata_semantic_v2 \\
        --dataset murata
"""

import argparse
import logging
import sys

from hermes_bedrock_agent.v2.pipelines.build_implementation_graph import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Stage 06: Build Implementation Graph"
    )
    parser.add_argument(
        "--config",
        default="configs/murata_semantic_v2.yaml",
        help="Path to configuration YAML",
    )
    parser.add_argument(
        "--run-id",
        default="murata_semantic_v2",
        help="Run identifier (default: murata_semantic_v2)",
    )
    parser.add_argument(
        "--dataset",
        default="murata",
        help="Dataset name (default: murata)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select candidates and report stats only (no extraction)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        result = run_pipeline(
            config_path=args.config,
            run_id=args.run_id,
            dataset=args.dataset,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
        )
        print(f"\nResult: {result}")
        return 0
    except Exception as e:
        logging.error(f"Pipeline failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
