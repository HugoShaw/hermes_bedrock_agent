#!/usr/bin/env python3
"""
CLI: Excel Visual Parse — extract visual objects and analyze with Bedrock.

Usage:
    PYTHONPATH=src python scripts/excel_visual_parse_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --s3-uri "s3://s3-hulftchina-rd/サンプル20260519/" \
        --run-id sample_20260519_excel_v1 \
        --dataset sample_20260519 \
        --output-dir data/outputs/sample_20260519_excel_v1/visual_parse \
        --bedrock-enabled

    # Without Bedrock (object extraction only):
    PYTHONPATH=src python scripts/excel_visual_parse_v2.py \
        --config configs/sample_20260519_excel_v1.yaml \
        --no-bedrock
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(
        description="Excel Visual Parse Pipeline — extract and analyze visual content"
    )
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--s3-uri", help="Override S3 URI from config")
    parser.add_argument("--run-id", help="Override run_id from config")
    parser.add_argument("--dataset", help="Override dataset from config")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--bedrock-enabled", action="store_true", default=True,
                       help="Enable Bedrock vision analysis (default: true)")
    parser.add_argument("--no-bedrock", action="store_true",
                       help="Disable Bedrock analysis (extraction only)")
    parser.add_argument("--max-images", type=int, default=50,
                       help="Max images to analyze per workbook (default: 50)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")
    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Load .env if present
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path) as ef:
            for line in ef:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

    # Resolve parameters
    run_id = args.run_id or config.get("run_id", "sample_20260519_excel_v1")
    dataset = args.dataset or config.get("dataset", "sample_20260519")
    s3_uri = args.s3_uri or config.get("source", {}).get("s3_uri", "")
    output_dir = args.output_dir or str(
        Path(config.get("output_dir", f"data/outputs/{run_id}")) / "visual_parse"
    )
    bedrock_enabled = args.bedrock_enabled and not args.no_bedrock

    print(f"\n{'='*60}")
    print(f"Excel Visual Parse Pipeline")
    print(f"  config:   {config_path}")
    print(f"  run_id:   {run_id}")
    print(f"  dataset:  {dataset}")
    print(f"  s3_uri:   {s3_uri}")
    print(f"  output:   {output_dir}")
    print(f"  bedrock:  {bedrock_enabled}")
    print(f"  max_imgs: {args.max_images}")
    print(f"{'='*60}\n")

    # Run pipeline
    from hermes_bedrock_agent.v2.pipelines.excel_visual_parse_pipeline import (
        ExcelVisualParsePipeline,
    )

    pipeline = ExcelVisualParsePipeline(
        config=config,
        output_dir=output_dir,
        run_id=run_id,
        dataset=dataset,
        s3_uri=s3_uri,
        bedrock_enabled=bedrock_enabled,
        max_images_per_sheet=args.max_images,
    )
    result = pipeline.run()

    # Print summary
    print(f"\n{'='*60}")
    print(f"RESULT: {result.get('status', 'unknown')}")
    print(f"  Workbooks:        {result.get('workbook_count', 0)}")
    print(f"  Sheets:           {result.get('sheet_count', 0)}")
    print(f"  Visual Objects:   {result.get('visual_object_count', 0)}")
    print(f"  Bedrock Analyses: {result.get('bedrock_analysis_count', 0)}")
    print(f"  Warnings:         {result.get('warning_count', 0)}")
    print(f"  Output Dir:       {result.get('output_dir', '')}")
    print(f"{'='*60}\n")

    if result.get("generated_files"):
        print("Generated files:")
        for f in sorted(result["generated_files"]):
            print(f"  {f}")


if __name__ == "__main__":
    main()
