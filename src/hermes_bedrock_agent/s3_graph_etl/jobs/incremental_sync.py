"""Incremental sync job - only processes new/changed files.

Usage:
    python -m hermes_bedrock_agent.s3_graph_etl.jobs.incremental_sync
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion import run_ingestion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/ingestion.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run incremental sync - processes only new/changed files."""
    Path("logs").mkdir(exist_ok=True)

    logger.info("Starting incremental sync")
    result = run_ingestion(dry_run=False)
    logger.info("Incremental sync complete: %s", result)

    if result.get("files_failed", 0) > 0:
        logger.warning("Some files failed - check logs/errors.log")
        # Write failures to error log
        with open("logs/errors.log", "a") as f:
            f.write(f"Incremental sync: {result.get('files_failed', 0)} failures\n")


if __name__ == "__main__":
    main()
