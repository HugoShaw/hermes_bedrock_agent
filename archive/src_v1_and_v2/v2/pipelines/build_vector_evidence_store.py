"""
V2 Pipeline: Build Vector Evidence Store

Can be run as a module:
    python -m hermes_bedrock_agent.v2.pipelines.build_vector_evidence_store ...

Or via the wrapper script:
    python scripts/build_vector_evidence_store_v2.py ...
"""
from __future__ import annotations

import argparse
import logging
import sys

from hermes_bedrock_agent.v2.evidence.evidence_store_builder import EvidenceStoreBuilder


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the V2 Vector Evidence Store (Stage 04)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the run config YAML (e.g. configs/murata_semantic_v2.yaml)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the run_id from config (default: read from config)",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Override the dataset from config (default: read from config)",
    )
    parser.add_argument(
        "--jsonl-only",
        action="store_true",
        default=True,
        help="Only generate JSONL outputs, skip vector index (default)",
    )
    parser.add_argument(
        "--build-index",
        action="store_true",
        default=False,
        help="Build the LanceDB vector index after generating JSONL",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Limit number of S3 files to load (for dev/testing)",
    )
    parser.add_argument(
        "--summary-mode",
        choices=["extractive", "none"],
        default="extractive",
        help="Summary generation mode (default: extractive)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the Vector Evidence Store pipeline."""
    args = parse_args(argv)

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    build_index = args.build_index  # --build-index overrides --jsonl-only

    builder = EvidenceStoreBuilder(
        config_path=args.config,
        run_id=args.run_id,
        dataset=args.dataset,
        build_index=build_index,
        max_files=args.max_files,
        summary_mode=args.summary_mode,
    )

    stats = builder.run()

    # Exit code: 0 = success, 1 = partial (documents failed), 2 = fatal
    if stats.errors:
        return 2
    if stats.documents_failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
