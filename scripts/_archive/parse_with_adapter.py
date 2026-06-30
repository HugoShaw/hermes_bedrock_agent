#!/usr/bin/env python3
"""Run parse pipeline using the ExcelVlmAdapter (subprocess UNO) approach.

This script replaces the CLI `dualrag parse` path for environments where
the venv Python can't access UNO bindings directly. It:
1. Discovers and downloads Excel files from S3
2. Uses ExcelVlmAdapter._convert_excel_subprocess for Excel→PDF (via /usr/bin/python3)
3. Runs PDF→Images, VLM parsing, and post-processing in-process (venv Python)
4. Saves VLM-parsed markdown to the output directory

Usage:
    uv run python scripts/parse_with_adapter.py \
        --s3-prefix "s3://s3-hulftchina-rd/サンプル20260519/" \
        --output-dir outputs/refactor_sample_20260519/run_YYYYMMDD_HHMMSS
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Parse Excel from S3 via adapter pattern")
    parser.add_argument("--s3-prefix", required=True, help="S3 prefix to scan")
    parser.add_argument("--output-dir", required=True, help="Output base directory")
    parser.add_argument("--skip-graph", action="store_true", default=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    run_dir = Path(args.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: S3 Discovery
    from hermes_bedrock_agent.parsing.s3_discovery import discover, download_excel_files
    logger.info("Stage 1: S3 Discovery")
    logger.info("Scanning %s …", args.s3_prefix)
    manifest = discover(args.s3_prefix)
    logger.info("  Found %d excel files", len(manifest.excel_files))

    dl_dir = run_dir / "downloads"
    manifest = download_excel_files(manifest, str(dl_dir))

    xlsx_paths = []
    for sf in manifest.excel_files:
        if sf.local_path:
            xlsx_paths.append(Path(sf.local_path))

    if not xlsx_paths:
        logger.error("No Excel files found/downloaded")
        sys.exit(1)

    logger.info("Will process %d Excel files", len(xlsx_paths))

    # Import pipeline components
    from hermes_bedrock_agent.parsing.excel_vlm_adapter import ExcelVlmAdapter
    from hermes_bedrock_agent.parsing.pdf_parser import render_all_sheets
    from hermes_bedrock_agent.parsing.vlm_client import parse_all_sheets
    from hermes_bedrock_agent.parsing.text_parser import post_process_all
    from hermes_bedrock_agent.parsing.models import SheetPDF, SheetInfo

    adapter = ExcelVlmAdapter()
    summary = []

    for xlsx_path in xlsx_paths:
        wb_name = xlsx_path.stem
        wb_dir = run_dir / wb_name
        pdf_dir = wb_dir / "pdf"
        image_dir = wb_dir / "images"
        parsed_dir = wb_dir / "vlm_parsed"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        image_dir.mkdir(parents=True, exist_ok=True)
        parsed_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("Processing: %s", wb_name)
        logger.info("=" * 60)

        # Step 1: Excel → PDF via subprocess (/usr/bin/python3 + UNO)
        logger.info("Stage 2: Excel → PDF (via /usr/bin/python3 subprocess)")
        try:
            sheet_pdfs_data = adapter._convert_excel_subprocess(xlsx_path, pdf_dir)
        except Exception as e:
            logger.error("Excel→PDF failed for %s: %s", wb_name, e)
            summary.append({"workbook": wb_name, "status": "FAILED", "error": str(e)})
            continue

        if not sheet_pdfs_data:
            logger.error("No sheets returned for %s", wb_name)
            summary.append({"workbook": wb_name, "status": "FAILED", "error": "no sheets"})
            continue

        # Reconstruct SheetPDF objects
        pdf_objects = []
        for sp_data in sheet_pdfs_data:
            si_data = sp_data["sheet_info"]
            si = SheetInfo(**si_data)
            pdf_objects.append(SheetPDF(
                sheet_info=si,
                pdf_path=sp_data.get("pdf_path", ""),
                page_size=tuple(sp_data.get("page_size", (0, 0))),
                pages=sp_data.get("pages", 0),
                paper_label=sp_data.get("paper_label", ""),
            ))

        logger.info("  %d sheets converted to PDF", len(pdf_objects))

        # Step 2: PDF → Images
        logger.info("Stage 3: PDF → Images")
        all_images = render_all_sheets(pdf_objects, str(image_dir))
        if not all_images:
            logger.error("PDF→Image rendering returned no results for %s", wb_name)
            summary.append({"workbook": wb_name, "status": "FAILED", "error": "no images"})
            continue
        logger.info("  %d sheet image sets rendered", len(all_images))

        # Step 3: VLM Parsing
        logger.info("Stage 4: VLM Parsing")
        parse_results = parse_all_sheets(
            all_images, str(parsed_dir),
            resume=True,
            workbook_name=wb_name,
        )
        logger.info("  %d sheets VLM-parsed", len(parse_results))

        # Step 4: Post-processing
        logger.info("Stage 5: Markdown Post-processing")
        parse_results = post_process_all(parse_results)

        # Save per-sheet markdown to vlm_parsed/
        for pr in parse_results:
            sheet_idx = pr.sheet_info.index
            md_path = parsed_dir / f"sheet_{sheet_idx:02d}.md"
            md_path.write_text(pr.markdown, encoding="utf-8")

        summary.append({
            "workbook": wb_name,
            "status": "OK",
            "sheets_parsed": len(parse_results),
            "output_dir": str(wb_dir),
            "pdf_count": len(pdf_objects),
            "image_sets": len(all_images),
        })
        logger.info("Done: %d sheets → %s", len(parse_results), parsed_dir)

    # Also handle mermaid/ground-truth files if present
    if manifest.ground_truth_files:
        from hermes_bedrock_agent.parsing.models import FileType
        from hermes_bedrock_agent.parsing.mermaid_parser import parse_mermaid_file, detect_mermaid_in_markdown
        from hermes_bedrock_agent.parsing.s3_discovery import download_mermaid_files

        logger.info("Stage 6: Mermaid / Ground-truth file parsing")
        manifest = download_mermaid_files(manifest, str(dl_dir))

        mermaid_out_dir = run_dir / "mermaid"
        for stem, s3f in manifest.ground_truth_files.items():
            if s3f.file_type == FileType.MERMAID and s3f.local_path:
                out = mermaid_out_dir / stem
                result = parse_mermaid_file(s3f.local_path, str(out))
                logger.info("  Mermaid: %s → %d nodes, %d edges", stem, len(result.nodes), len(result.edges))
            elif s3f.file_type == FileType.MARKDOWN and s3f.local_path:
                blocks = detect_mermaid_in_markdown(s3f.local_path)
                if blocks:
                    logger.info("  Markdown %s: found %d mermaid blocks", stem, len(blocks))

    # Final summary
    logger.info("=" * 60)
    logger.info("PARSE COMPLETE")
    logger.info("=" * 60)
    for s in summary:
        status = s.get("status", "?")
        wb = s.get("workbook", "?")
        if status == "OK":
            logger.info("  ✓ %s: %d sheets", wb, s["sheets_parsed"])
        else:
            logger.info("  ✗ %s: %s", wb, s.get("error", "unknown"))

    # Save summary JSON
    summary_path = run_dir / "parse_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info("Summary saved to: %s", summary_path)

    # Return non-zero if any failures
    if any(s.get("status") != "OK" for s in summary):
        sys.exit(1)


if __name__ == "__main__":
    main()
