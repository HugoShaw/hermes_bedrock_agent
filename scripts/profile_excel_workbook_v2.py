#!/usr/bin/env python3
"""
Profile Excel workbook(s) — CLI entry point for the V2 Excel profiling pipeline.

Supports two modes:
  1. S3 prefix mode: discover and profile all Excel files under an S3 prefix
  2. Local file mode: profile a single local Excel file

Usage:
  # S3 mode
  PYTHONPATH=src python scripts/profile_excel_workbook_v2.py \
    --config configs/sample_20260519_excel_v1.yaml \
    --s3-uri "s3://s3-hulftchina-rd/サンプル20260519/" \
    --run-id sample_20260519_excel_v1 \
    --dataset sample_20260519 \
    --output-dir data/outputs/sample_20260519_excel_v1

  # Local mode
  PYTHONPATH=src python scripts/profile_excel_workbook_v2.py \
    --input /path/to/workbook.xlsx \
    --run-id sample_20260519_excel_v1 \
    --dataset sample_20260519 \
    --output-dir data/outputs/sample_20260519_excel_v1

  # With safe cleanup
  PYTHONPATH=src python scripts/profile_excel_workbook_v2.py \
    --config configs/sample_20260519_excel_v1.yaml \
    --s3-uri "s3://s3-hulftchina-rd/サンプル20260519/" \
    --output-dir data/outputs/sample_20260519_excel_v1 \
    --clean-output

Safety:
  --clean-output only removes the EXACT output-dir specified.
  It will NEVER remove data/outputs/murata_semantic_v2/ or any other run's data.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(
        description="Profile Excel workbook(s) using the V2 Excel pipeline",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to YAML config file (e.g. configs/sample_20260519_excel_v1.yaml)",
    )
    parser.add_argument(
        "--s3-uri",
        type=str,
        default=None,
        help="S3 URI prefix to discover Excel files (e.g. s3://s3-hulftchina-rd/サンプル20260519/)",
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Path to a local Excel file (alternative to --s3-uri)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="sample_20260519_excel_v1",
        help="Run identifier",
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
        help="Output directory for results",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Remove and recreate the output directory before running (SAFE: only removes the exact output-dir)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("profile_excel")

    # Validate mode
    if not args.s3_uri and not args.input and not args.config:
        parser.error("At least one of --s3-uri, --input, or --config must be specified")

    # Safety check: prevent accidental deletion of other runs
    output_dir = Path(args.output_dir).resolve()
    PROTECTED_DIRS = [
        Path("data/outputs/murata_semantic_v2").resolve(),
    ]

    if args.clean_output:
        if output_dir in PROTECTED_DIRS:
            logger.error("SAFETY: Refusing to clean protected directory: %s", output_dir)
            sys.exit(1)
        if output_dir.exists():
            logger.warning("Cleaning output directory: %s", output_dir)
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Load config
    config: dict = {}
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            logger.info("Loaded config from %s", config_path)
        else:
            logger.warning("Config file not found: %s — using defaults", config_path)

    # Override config with CLI args
    if args.dataset:
        config["dataset"] = args.dataset
    if args.run_id:
        config["run_id"] = args.run_id
    if args.output_dir:
        config["output_dir"] = str(output_dir)

    # Import pipeline (after config is loaded to give clean error on missing deps)
    try:
        from hermes_bedrock_agent.v2.pipelines.profile_excel_workbook import (
            ProfileExcelWorkbookPipeline,
        )
    except ImportError as exc:
        logger.error("Failed to import pipeline: %s", exc)
        logger.error("Make sure PYTHONPATH includes 'src/' and dependencies are installed")
        sys.exit(1)

    # Instantiate pipeline
    pipeline = ProfileExcelWorkbookPipeline(
        config=config,
        output_dir=str(output_dir),
        dataset=args.dataset,
        run_id=args.run_id,
    )

    # Run the appropriate mode
    if args.input:
        logger.info("Running in LOCAL mode: %s", args.input)
        results = pipeline.run_local(args.input)
    else:
        s3_uri = args.s3_uri or config.get("source", {}).get("s3_uri")
        if not s3_uri:
            parser.error("No S3 URI provided via --s3-uri or config source.s3_uri")
        logger.info("Running in S3 mode: %s", s3_uri)
        results = pipeline.run_s3(s3_uri=s3_uri)

    # Print summary
    print("\n" + "=" * 60)
    print("EXCEL PROFILING COMPLETE")
    print("=" * 60)

    if results.get("error"):
        print(f"\n  ERROR: {results['error']}")
        print(f"\n  Output directory: {output_dir}")
        sys.exit(1)
    else:
        print(f"\n  Output directory: {output_dir}")
        print(f"  Workbooks processed: {results.get('workbooks', 0)}")
        print(f"  Sheets profiled: {results.get('sheets', 0)}")
        print(f"  Table regions detected: {results.get('regions', 0)}")
        print(f"  Rows normalized: {results.get('rows', 0)}")
        print(f"  Cell samples: {results.get('cells', 0)}")
        print(f"  Evidence chunks generated: {results.get('chunks', 0)}")
        print()

        # List generated files
        print("  Generated files:")
        for p in sorted(output_dir.rglob("*")):
            if p.is_file():
                size_kb = p.stat().st_size / 1024
                print(f"    {p.relative_to(output_dir)} ({size_kb:.1f} KB)")
        print()


if __name__ == "__main__":
    main()
