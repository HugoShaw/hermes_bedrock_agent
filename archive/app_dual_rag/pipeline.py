"""CLI orchestrator for the dual-RAG pipeline.

Runs:
  1. Dataset building   — chunking + metadata enrichment → chunks.jsonl
  2. Vector store load  — embedding + LanceDB ingestion
  3. Graph build        — entity extraction + Neptune upsert
  4. Validation         — chunk counts, LanceDB schema, graph stats

Usage:
  uv run python -m app.dual_rag.pipeline [--skip-vector] [--skip-graph] [--dry-run-graph]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dual_rag.pipeline")


def _step(title: str) -> None:
    logger.info("=" * 60)
    logger.info("STEP: %s", title)
    logger.info("=" * 60)


def run_pipeline(
    skip_vector: bool = False,
    skip_graph: bool = False,
    dry_run_graph: bool = False,
    chunks_path: Path | None = None,
) -> dict:
    from .config import config
    from .dataset_builder import build_dataset, load_chunks
    from .graph_builder import build_graph
    from .vector_store_loader import load_vector_store

    results: dict = {}
    t0 = time.time()

    # ── Step 1: Dataset building ──────────────────────────────────────────────
    _step("Dataset building (chunking + metadata enrichment)")
    out_path = chunks_path or config.chunks_jsonl
    chunks = build_dataset(output_path=out_path)
    results["chunk_count"] = len(chunks)
    logger.info("Chunks built: %d → %s", len(chunks), out_path)

    if len(chunks) == 0:
        logger.error("No chunks produced — aborting pipeline")
        sys.exit(1)

    # ── Step 2: Vector store loading ──────────────────────────────────────────
    if not skip_vector:
        _step("Vector store loading (Bedrock embed → LanceDB)")
        written = load_vector_store(chunks)
        results["vector_written"] = written
        logger.info("Vector store: %d records written", written)
    else:
        logger.info("SKIP: vector store loading")
        results["vector_written"] = 0

    # ── Step 3: Graph building ────────────────────────────────────────────────
    if not skip_graph:
        _step("Graph building (entity extraction → Neptune)")
        graph_stats = build_graph(chunks, dry_run=dry_run_graph)
        results["graph"] = graph_stats
        logger.info(
            "Graph: %d nodes, %d edges (errors: %d)",
            graph_stats["node_count"],
            graph_stats["edge_count"],
            graph_stats["error_count"],
        )
    else:
        logger.info("SKIP: graph building")
        results["graph"] = {}

    # ── Step 4: Validation ────────────────────────────────────────────────────
    _step("Validation")
    _validate(config, results, skip_vector, skip_graph)

    elapsed = time.time() - t0
    results["elapsed_seconds"] = round(elapsed, 1)
    logger.info("Pipeline complete in %.1f seconds", elapsed)

    # Write summary
    summary_path = config.output_dir / "pipeline_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Summary written → %s", summary_path)

    return results


def _validate(config, results: dict, skip_vector: bool, skip_graph: bool) -> None:
    import lancedb

    # Validate JSONL
    jsonl_path = config.chunks_jsonl
    if jsonl_path.exists():
        with open(jsonl_path) as f:
            line_count = sum(1 for line in f if line.strip())
        logger.info("VALIDATE chunks.jsonl: %d lines", line_count)
        if line_count < 50:
            logger.warning("Chunk count seems low (%d), expected 150+", line_count)
    else:
        logger.error("VALIDATE FAIL: chunks.jsonl not found at %s", jsonl_path)

    # Validate LanceDB
    if not skip_vector:
        try:
            db = lancedb.connect(config.vector_local_store_path)
            if config.vector_collection in db.table_names():
                table = db.open_table(config.vector_collection)
                row_count = table.count_rows()
                logger.info(
                    "VALIDATE LanceDB '%s': %d rows, schema: %s",
                    config.vector_collection,
                    row_count,
                    [f.name for f in table.schema],
                )
                results["lancedb_rows"] = row_count
            else:
                logger.error("VALIDATE FAIL: collection '%s' not found", config.vector_collection)
        except Exception as exc:
            logger.error("VALIDATE LanceDB error: %s", exc)

    # Validate Neptune
    if not skip_graph and results.get("graph", {}).get("node_count", 0) > 0:
        try:
            from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
            client = NeptuneClient()
            if client.is_configured:
                stats = client.get_graph_statistics()
                logger.info(
                    "VALIDATE Neptune: %s nodes, %s edges",
                    stats.get("node_count"),
                    stats.get("edge_count"),
                )
                results["neptune_stats"] = stats
        except Exception as exc:
            logger.warning("VALIDATE Neptune stats failed: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dual-RAG pipeline: VLM markdown → LanceDB + Neptune")
    parser.add_argument("--skip-vector", action="store_true", help="Skip LanceDB embedding/ingestion")
    parser.add_argument("--skip-graph", action="store_true", help="Skip Neptune graph loading")
    parser.add_argument("--dry-run-graph", action="store_true", help="Extract graph entities but do not write to Neptune")
    parser.add_argument("--chunks-path", type=Path, default=None, help="Override path for chunks.jsonl")
    args = parser.parse_args()

    results = run_pipeline(
        skip_vector=args.skip_vector,
        skip_graph=args.skip_graph,
        dry_run_graph=args.dry_run_graph,
        chunks_path=args.chunks_path,
    )

    print("\n── Pipeline Results ──────────────────────────────────────")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
