"""Main ingestion job - scan S3, parse files, build graph, load to Neptune.

Usage:
    python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --dry-run
    python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --once
    python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --prefix output/semantic_map
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from hermes_bedrock_agent.config import Settings
from hermes_bedrock_agent.s3_graph_etl.embeddings.bedrock_embedder import BedrockEmbedder, MockEmbedder
from hermes_bedrock_agent.s3_graph_etl.graph_builder.builder import GraphBuilder
from hermes_bedrock_agent.s3_graph_etl.graph_builder.loader import GraphLoader
from hermes_bedrock_agent.s3_graph_etl.parsers.file_router import FileRouter
from hermes_bedrock_agent.s3_graph_etl.schemas import DocumentChunk
from hermes_bedrock_agent.s3_graph_etl.sources.file_registry import FileRegistry
from hermes_bedrock_agent.s3_graph_etl.sources.s3_reader import S3Reader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/ingestion.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


def run_ingestion(
    dry_run: bool = True,
    prefix: str | None = None,
    max_files: int | None = None,
) -> dict:
    """Run the full ingestion pipeline."""
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("Starting ingestion (dry_run=%s, prefix=%s, max_files=%s)", dry_run, prefix, max_files)

    # 1. Load settings
    try:
        settings = Settings.from_env()
    except ValueError:
        # In dry-run mode without full .env, use minimal config
        logger.warning("Settings incomplete, using defaults for dry-run")
        settings = None

    # 2. Initialize components
    file_router = FileRouter()
    registry = FileRegistry()

    # Choose embedder
    if dry_run:
        embedder = MockEmbedder(dimension=1024)
    else:
        if settings:
            embedder = BedrockEmbedder(settings.embedding)
        else:
            embedder = MockEmbedder(dimension=1024)

    graph_builder = GraphBuilder(embedder=embedder, skip_embedding=dry_run)
    loader = GraphLoader(dry_run=dry_run, neptune_config=settings.neptune if settings else None)

    # 3. Scan S3 (skip if dry-run with no real S3 credentials)
    files = []
    if not dry_run or (settings and settings.s3.bucket):
        try:
            s3_config = settings.s3 if settings else None
            s3_reader = S3Reader(s3_config)
            files = s3_reader.scan(prefix=prefix, max_files=max_files)
            logger.info("Found %d files to process", len(files))
        except Exception as exc:
            logger.error("S3 scan failed: %s", exc)
            if dry_run:
                logger.info("[DRY-RUN] Generating sample output with no S3 files")
                files = []
            else:
                raise
    else:
        logger.info("[DRY-RUN] Skipping S3 scan (no credentials configured)")

    # 4. Filter by registry (only new/changed files)
    to_process = [f for f in files if registry.needs_processing(f)]
    logger.info("Files needing processing: %d (of %d total)", len(to_process), len(files))

    # 5. Parse files
    all_chunks: list[DocumentChunk] = []
    processed_count = 0
    failed_count = 0

    for file_record in to_process:
        registry.upsert(file_record)
        try:
            # Download and parse
            tmp_path = s3_reader.download_to_temp(file_record.key)
            chunks = file_router.route(tmp_path, file_record.uri)
            all_chunks.extend(chunks)
            registry.mark_done(file_record.uri, chunk_count=len(chunks))
            processed_count += 1

            # Cleanup temp file
            Path(tmp_path).unlink(missing_ok=True)

        except Exception as exc:
            logger.error("Failed to process %s: %s", file_record.uri, exc)
            registry.mark_failed(file_record.uri, str(exc))
            failed_count += 1

    logger.info("Parsing complete: %d files processed, %d failed, %d chunks total",
                processed_count, failed_count, len(all_chunks))

    # 6. Build graph
    if all_chunks:
        nodes, edges = graph_builder.build(all_chunks)
        logger.info("Graph built: %d nodes, %d edges", len(nodes), len(edges))

        # 7. Load to Neptune / artifacts
        result = loader.load(nodes, edges)
    else:
        result = {"nodes_written": 0, "edges_written": 0, "mode": "dry_run" if dry_run else "no_data"}
        logger.info("No chunks to process")

    # 8. Save registry
    registry.save()

    elapsed = time.time() - start_time
    result.update({
        "files_scanned": len(files),
        "files_processed": processed_count,
        "files_failed": failed_count,
        "chunks_total": len(all_chunks),
        "elapsed_seconds": round(elapsed, 2),
    })

    logger.info("Ingestion complete in %.1fs: %s", elapsed, result)
    logger.info("=" * 60)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="S3 Graph ETL Ingestion")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Dry-run mode (no Neptune writes)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--prefix", type=str, default=None, help="S3 prefix to scan")
    parser.add_argument("--max-files", type=int, default=None, help="Max files to process")
    args = parser.parse_args()

    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)

    dry_run = args.dry_run
    if not args.once and not args.dry_run:
        # Default to dry-run if neither --once nor --dry-run specified
        dry_run = True

    result = run_ingestion(dry_run=dry_run, prefix=args.prefix, max_files=args.max_files)
    print(f"\nResult: {result}")


if __name__ == "__main__":
    main()
