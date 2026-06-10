"""CLI entry point for experiment import.

Usage:
    python -m hermes_bedrock_agent.experiments.import_cli \
        --experiment-dir outputs/experiments/chunk_graph_eval \
        --target all \
        --lancedb-write \
        --neptune-import \
        --fail-if-exists
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .import_eval_variants import ImportConfig, run_import


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("boto3", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import experiment eval variants into LanceDB and Neptune",
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=Path("outputs/experiments/chunk_graph_eval"),
        help="Path to experiment output root",
    )
    parser.add_argument(
        "--target",
        default="all",
        help="'all' or specific experiment_project_id",
    )
    parser.add_argument(
        "--lancedb-write",
        action="store_true",
        default=True,
        help="Enable LanceDB import (default: enabled)",
    )
    parser.add_argument(
        "--no-lancedb",
        action="store_true",
        help="Disable LanceDB import",
    )
    parser.add_argument(
        "--neptune-import",
        action="store_true",
        default=True,
        help="Enable Neptune import (default: enabled)",
    )
    parser.add_argument(
        "--no-neptune",
        action="store_true",
        help="Disable Neptune import",
    )
    parser.add_argument(
        "--fail-if-exists",
        action="store_true",
        default=True,
        help="Skip experiments that already exist (default)",
    )
    parser.add_argument(
        "--replace-experiment",
        action="store_true",
        help="Delete and replace existing experiment data",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip import, only run validation queries",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.05,
        help="Delay between embedding API calls (default: 0.05)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Embedding batch size for LanceDB (default: 25)",
    )
    parser.add_argument(
        "--lancedb-path",
        default="",
        help="Override LanceDB path",
    )
    parser.add_argument(
        "--neptune-graph-id",
        default="",
        help="Override Neptune graph ID",
    )
    parser.add_argument(
        "--normalize-possibly-related",
        action="store_true",
        help="Normalize POSSIBLY_RELATED edges before import (review_status=pending, confidence<=0.70, view_scope=candidate)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)
    logger = logging.getLogger("hermes.import")

    icfg = ImportConfig(
        experiment_dir=args.experiment_dir,
        target=args.target,
        lancedb_write=not args.no_lancedb,
        neptune_import=not args.no_neptune,
        replace_experiment=args.replace_experiment,
        validate_only=args.validate_only,
        delay_seconds=args.delay_seconds,
        batch_size=args.batch_size,
        lancedb_path=args.lancedb_path,
        neptune_graph_id=args.neptune_graph_id,
    )

    logger.info("Import config:")
    logger.info("  experiment_dir: %s", icfg.experiment_dir)
    logger.info("  target: %s", icfg.target)
    logger.info("  lancedb_write: %s", icfg.lancedb_write)
    logger.info("  neptune_import: %s", icfg.neptune_import)
    logger.info("  replace_experiment: %s", icfg.replace_experiment)
    logger.info("  validate_only: %s", icfg.validate_only)
    logger.info("  batch_size: %d", icfg.batch_size)
    logger.info("  delay_seconds: %.3f", icfg.delay_seconds)

    results = run_import(icfg)

    print("\n" + "=" * 60)
    print("IMPORT RESULTS")
    print("=" * 60)
    for r in results:
        status_icon = "✓" if r["status"] == "completed" else "✗"
        print(f"\n  {status_icon} {r['experiment_project_id']}")
        if r["status"] == "completed":
            print(f"    LanceDB: {r.get('lancedb_imported', 0)} chunks")
            print(f"    Neptune: {r.get('neptune_nodes_imported', 0)} nodes, {r.get('neptune_edges_imported', 0)} edges")
            val = r.get("validation", {})
            print(f"    Validation: LanceDB={val.get('lancedb_match', '?')}, Neptune nodes={val.get('neptune_node_match', '?')}, edges={val.get('neptune_edge_match', '?')}")
        else:
            print(f"    Error: {r.get('error', 'unknown')}")

    print()


if __name__ == "__main__":
    main()
