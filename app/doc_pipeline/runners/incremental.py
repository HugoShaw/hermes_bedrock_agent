"""Incremental pipeline runner — skips files already present in the output directory."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from ..config import PipelineConfig, config as _default_config

logger = logging.getLogger(__name__)


def _already_processed(workbook_name: str, output_dir: str) -> bool:
    """True if the workbook's vlm_parsed/ directory exists and has substantial content."""
    parsed_dir = Path(output_dir) / workbook_name / "vlm_parsed"
    if not parsed_dir.exists():
        return False
    md_files = list(parsed_dir.glob("sheet_*.md"))
    if not md_files:
        return False
    # Require at least half the files to have substantial content
    substantial = [f for f in md_files if f.stat().st_size > 200]
    return len(substantial) >= len(md_files) // 2


def run_incremental(
    s3_prefix: str,
    output_dir: str,
    cfg: Optional[PipelineConfig] = None,
    mode: str = "append",
    skip_graph: bool = False,
) -> dict:
    """Run the full pipeline but skip workbooks already processed in output_dir.

    Returns a summary dict with 'processed', 'skipped', and 'failed' lists.
    """
    from ..stages.s3_discovery import discover, download_excel_files
    from .full_pipeline import run_pipeline

    cfg = cfg or _default_config

    logger.info("=== Incremental run: %s ===", s3_prefix)
    manifest = discover(s3_prefix, cfg=cfg)
    dl_dir = os.path.join(output_dir, "downloads")
    manifest = download_excel_files(manifest, dl_dir, cfg=cfg)

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for sf in manifest.excel_files:
        if not sf.local_path:
            continue
        workbook_name = Path(sf.local_path).stem

        if _already_processed(workbook_name, output_dir):
            logger.info("Skipping (already processed): %s", workbook_name)
            skipped.append(workbook_name)
            continue

        logger.info("Processing: %s", workbook_name)
        try:
            run_pipeline(
                xlsx_path=sf.local_path,
                output_dir=output_dir,
                stages="all",
                mode=mode,
                skip_graph=skip_graph,
                cfg=cfg,
            )
            processed.append(workbook_name)
        except Exception as e:
            logger.error("Failed: %s — %s", workbook_name, e)
            failed.append(workbook_name)

    summary = {
        "s3_prefix": s3_prefix,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
    }
    logger.info(
        "Incremental run complete: %d processed, %d skipped, %d failed",
        len(processed), len(skipped), len(failed),
    )
    return summary
