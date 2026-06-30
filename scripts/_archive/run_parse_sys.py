#!/usr/bin/env python3
"""Run DualRAG parse using system Python (for UNO access).

Usage:
    /usr/bin/python3 scripts/run_parse_sys.py --s3-prefix "14_債務奉行クラウド/" --project-id "14_債務奉行クラウド"
"""
import sys
import os
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.chdir(str(Path(__file__).resolve().parent.parent))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from hermes_bedrock_agent.config import config
from hermes_bedrock_agent.parsing.s3_discovery import discover, download_excel_files
from hermes_bedrock_agent.parsing.excel_parser import convert_excel_to_pdfs
from hermes_bedrock_agent.parsing.pdf_parser import render_all_sheets
from hermes_bedrock_agent.parsing.vlm_client import parse_all_sheets
from hermes_bedrock_agent.parsing.text_parser import post_process_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
for noisy in ("boto3", "botocore", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("dualrag.parse")


def main():
    parser = argparse.ArgumentParser(description="DualRAG Parse (system Python)")
    parser.add_argument("--s3-prefix", required=True, help="S3 prefix (directory path within bucket)")
    parser.add_argument("--project-id", required=True, help="Project ID")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument("--stages", default="all", help="Stages: all|parse")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_dir:
        run_dir = Path(args.output_dir)
    else:
        run_dir = Path(f"outputs/{args.project_id}/run_{ts}")
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== DualRAG Parse ===")
    logger.info("Project ID: %s", args.project_id)
    logger.info("S3 Prefix: %s", args.s3_prefix)
    logger.info("Output: %s", run_dir)

    # Stage 1: S3 Discovery
    logger.info("Stage 1: S3 Discovery")
    manifest = discover(args.s3_prefix)
    logger.info("  Found %d Excel files", len(manifest.excel_files))
    for f in manifest.excel_files:
        logger.info("    %s", f.key)

    # Download
    dl_dir = run_dir / "downloads"
    manifest = download_excel_files(manifest, str(dl_dir))

    xlsx_paths = []
    for sf in manifest.excel_files:
        if sf.local_path:
            xlsx_paths.append((Path(sf.local_path), f"s3://{config.s3_bucket}/{sf.key}"))

    logger.info("  Downloaded %d files to %s", len(xlsx_paths), dl_dir)

    # Process each workbook
    summary = []
    for i, (xlsx_path, s3_excel_path) in enumerate(xlsx_paths, 1):
        wb_name = xlsx_path.stem
        wb_dir = run_dir / wb_name
        pdf_dir = wb_dir / "pdf"
        image_dir = wb_dir / "images"
        parsed_dir = wb_dir / "vlm_parsed"

        logger.info("[%d/%d] Processing: %s", i, len(xlsx_paths), wb_name)

        try:
            # Stage 2: Excel → PDF
            logger.info("  Stage 2: Excel → PDF")
            sheet_pdfs = convert_excel_to_pdfs(str(xlsx_path), str(pdf_dir))
            logger.info("    → %d sheet PDFs", len(sheet_pdfs))

            # Stage 3: PDF → Images
            logger.info("  Stage 3: PDF → Images")
            all_images = render_all_sheets(sheet_pdfs, str(image_dir))
            logger.info("    → %d image sets", len(all_images))

            # Stage 4: VLM Parsing
            logger.info("  Stage 4: VLM Parsing")
            parse_results = parse_all_sheets(all_images, str(parsed_dir), resume=True, workbook_name=wb_name)
            logger.info("    → %d sheets parsed", len(parse_results))

            # Stage 5: Markdown Post-processing
            logger.info("  Stage 5: Markdown Post-processing")
            parse_results = post_process_all(parse_results)

            summary.append({
                "workbook": wb_name,
                "sheets_parsed": len(parse_results),
                "output_dir": str(wb_dir),
                "status": "success",
            })
            logger.info("  ✓ Done: %d sheets → %s", len(parse_results), parsed_dir)

        except Exception as e:
            logger.error("  ✗ FAILED: %s: %s", type(e).__name__, e)
            summary.append({
                "workbook": wb_name,
                "sheets_parsed": 0,
                "output_dir": str(wb_dir),
                "status": "error",
                "error": str(e),
            })

    # Write summary
    summary_path = run_dir / "parse_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    logger.info("=== Parse Complete ===")
    logger.info("Summary: %s", summary_path)
    for item in summary:
        logger.info("  %s: %s (%d sheets)", item["workbook"], item["status"], item["sheets_parsed"])


if __name__ == "__main__":
    main()
