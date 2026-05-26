"""CLI entry point: python -m app.doc_pipeline [options]

Stage selection:
  --stages all        Full pipeline (default)
  --stages parse      S3 discovery → Excel→PDF → Image → VLM → Markdown
  --stages ingest     Chunking → Vector → Graph (requires --parsed-dir or existing run)
  --stages images     Only generate PDFs and images (for visual review)
  --stages vlm        Only run VLM on existing images
"""

from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.doc_pipeline",
        description="Standardised document parsing pipeline: S3 → LanceDB + Neptune",
    )

    # Source selection (mutually exclusive)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--s3-prefix", metavar="PREFIX",
        help='S3 prefix to scan (e.g. "サンプル20260519/" or "s3://bucket/prefix/")',
    )
    source.add_argument(
        "--file", metavar="PATH",
        help="Local path to a single Excel workbook",
    )

    # For ingest-only runs
    parser.add_argument(
        "--parsed-dir", metavar="DIR",
        help="Path to existing vlm_parsed/ directory (use with --stages ingest)",
    )

    # Output
    parser.add_argument(
        "--output-dir", metavar="DIR", default=None,
        help="Base output directory for this run",
    )

    # Stage selection
    parser.add_argument(
        "--stages",
        choices=["all", "parse", "ingest", "images", "vlm"],
        default="all",
        help="Which pipeline stages to run (default: all)",
    )

    # LanceDB write mode
    parser.add_argument(
        "--replace", action="store_true",
        help="Delete existing rows for this workbook before adding new ones",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Drop and recreate the entire LanceDB table",
    )

    # Incremental mode
    parser.add_argument(
        "--incremental", action="store_true",
        help="Skip workbooks already processed in --output-dir",
    )

    # Ground-truth Mermaid override
    parser.add_argument(
        "--ground-truth", metavar="FILE",
        help="Path to a .mmd file to inject as authoritative flowchart",
    )
    parser.add_argument(
        "--sheet", type=int, metavar="N",
        help="Sheet index (1-based) to apply --ground-truth to",
    )

    # Graph control
    parser.add_argument(
        "--no-graph", action="store_true",
        help="Skip Neptune graph stage",
    )

    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    # Validate
    if args.stages == "ingest" and not (args.file or args.s3_prefix or args.parsed_dir):
        parser.error("--stages ingest requires --file, --s3-prefix, or --parsed-dir")

    if args.ground_truth and not args.sheet:
        parser.error("--ground-truth requires --sheet N")

    if args.stages == "images" and not (args.file or args.s3_prefix):
        parser.error("--stages images requires --file or --s3-prefix")

    # Determine write mode
    if args.rebuild:
        mode = "rebuild"
    elif args.replace:
        mode = "replace"
    else:
        mode = "append"

    # Import after arg parsing to avoid slow startup on --help
    from .config import config
    from .runners.full_pipeline import run_pipeline
    from .runners.incremental import run_incremental

    if args.incremental:
        if not args.s3_prefix:
            parser.error("--incremental requires --s3-prefix")
        summary = run_incremental(
            s3_prefix=args.s3_prefix,
            output_dir=args.output_dir or "outputs/incremental",
            mode=mode,
            skip_graph=args.no_graph,
        )
    else:
        summary = run_pipeline(
            xlsx_path=args.file,
            s3_prefix=args.s3_prefix,
            output_dir=args.output_dir,
            parsed_dir=args.parsed_dir,
            stages=args.stages,
            mode=mode,
            ground_truth=args.ground_truth,
            sheet_index=args.sheet,
            skip_graph=args.no_graph,
            cfg=config,
        )

    import json
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
