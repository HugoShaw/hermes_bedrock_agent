#!/usr/bin/env python3
"""
Export parsed Excel content as Markdown for human verification — CLI entry point (X7).

Usage:
    PYTHONPATH=src python scripts/export_excel_parsed_markdown_v2.py \
      --config configs/sample_20260519_excel_v1.yaml \
      --run-id sample_20260519_excel_v1 \
      --dataset sample_20260519 \
      --input-dir data/outputs/sample_20260519_excel_v1 \
      --output-dir data/outputs/sample_20260519_excel_v1/markdown_export \
      --split-by-workbook \
      --split-by-sheet \
      --include-cell-samples \
      --include-evidence-chunks \
      --include-normalized-rows \
      --include-table-regions \
      --max-rows-per-table 0
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
        description="Export parsed Excel content as Markdown for human verification (X7)"
    )
    parser.add_argument("--config", required=True, help="Config YAML path")
    parser.add_argument("--run-id", required=True, help="Run ID")
    parser.add_argument("--dataset", required=True, help="Dataset name")
    parser.add_argument("--input-dir", required=True, help="Input directory with JSONL files")
    parser.add_argument("--output-dir", required=True, help="Output directory for Markdown files")
    parser.add_argument("--split-by-workbook", action="store_true", default=False)
    parser.add_argument("--split-by-sheet", action="store_true", default=False)
    parser.add_argument("--include-cell-samples", action="store_true", default=False)
    parser.add_argument("--include-evidence-chunks", action="store_true", default=False)
    parser.add_argument("--include-normalized-rows", action="store_true", default=False)
    parser.add_argument("--include-table-regions", action="store_true", default=False)
    parser.add_argument("--max-cell-text-length", type=int, default=1000)
    parser.add_argument("--max-rows-per-table", type=int, default=0, help="0 = all rows")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    options = {
        "split_by_workbook": args.split_by_workbook,
        "split_by_sheet": args.split_by_sheet,
        "include_cell_samples": args.include_cell_samples,
        "include_evidence_chunks": args.include_evidence_chunks,
        "include_normalized_rows": args.include_normalized_rows,
        "include_table_regions": args.include_table_regions,
        "max_cell_text_length": args.max_cell_text_length,
        "max_rows_per_table": args.max_rows_per_table,
    }

    print("=" * 60)
    print("X7: Excel Parsed Content Markdown Export")
    print("=" * 60)
    print(f"  Run ID:     {args.run_id}")
    print(f"  Dataset:    {args.dataset}")
    print(f"  Input Dir:  {args.input_dir}")
    print(f"  Output Dir: {args.output_dir}")
    print(f"  Options:    {options}")
    print("=" * 60)
    print()

    start = time.time()

    from hermes_bedrock_agent.v2.pipelines.export_excel_parsed_markdown import (
        run_markdown_export_pipeline,
    )

    result = run_markdown_export_pipeline(
        config=config,
        run_id=args.run_id,
        dataset=args.dataset,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        options=options,
    )

    elapsed = time.time() - start

    print()
    print("[X7] RESULTS")
    print(f"  Workbooks exported: {result['stats']['workbooks']}")
    print(f"  Sheets exported: {result['stats']['sheets']}")
    print(f"  Table regions: {result['stats']['table_regions']}")
    print(f"  Normalized rows: {result['stats']['normalized_rows']}")
    print(f"  Evidence chunks: {result['stats']['evidence_chunks']}")
    print(f"  Files generated: {len(result['generated_files'])}")
    print()
    print("  Generated files:")
    for f in sorted(result['generated_files']):
        print(f"    {f}")
    print()
    print(f"Completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
