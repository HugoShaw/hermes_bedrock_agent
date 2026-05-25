"""
V2 Pipeline: Build Business Semantic Graph

Can be run as a module:
    python -m hermes_bedrock_agent.v2.pipelines.build_business_semantic_graph ...

Or via the wrapper script:
    python scripts/build_business_semantic_graph_v2.py ...

Pipeline steps:
  1. Load documents.jsonl, sections.jsonl, evidence_chunks.jsonl
  2. Select business candidate evidence (filter out SQL dumps, code, config)
  3. Build business graph nodes and edges (heuristic extraction)
  4. Validate schema compliance
  5. Deduplicate and write outputs
  6. Generate report
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def run_pipeline(
    config_path: str,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    dry_run: bool = False,
    max_candidates: int = 2000,
    verbose: bool = False,
) -> None:
    """Run the Stage 05 Business Semantic Graph pipeline."""
    import yaml

    from hermes_bedrock_agent.v2.graph.business_evidence_selector import (
        save_candidate_evidence,
        select_business_evidence,
    )
    from hermes_bedrock_agent.v2.graph.business_graph_builder import (
        BuilderState,
        BusinessGraphConfig,
        build_business_graph,
        save_graph_outputs,
    )
    from hermes_bedrock_agent.v2.graph.business_graph_reporter import generate_report

    start_time = time.time()

    # Setup logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    output_dir = Path(config.get("output", {}).get("base_dir", f"data/outputs/{run_id}"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Stage 05: Business Semantic Graph")
    logger.info(f"  Config: {config_path}")
    logger.info(f"  Run ID: {run_id}")
    logger.info(f"  Dataset: {dataset}")
    logger.info(f"  Output: {output_dir}")
    logger.info(f"  Dry run: {dry_run}")
    logger.info("")

    # Step 1: Load Stage 04 outputs
    logger.info("Step 1: Loading Stage 04 outputs...")
    documents_path = output_dir / "documents.jsonl"
    sections_path = output_dir / "sections.jsonl"
    evidence_path = output_dir / "evidence_chunks.jsonl"

    if not evidence_path.exists():
        logger.error(f"Evidence chunks not found: {evidence_path}")
        logger.error("Run Stage 04 first: build_vector_evidence_store_v2.py")
        sys.exit(1)

    documents = load_jsonl(documents_path) if documents_path.exists() else []
    sections = load_jsonl(sections_path) if sections_path.exists() else []
    evidence_chunks = load_jsonl(evidence_path)

    logger.info(f"  Documents: {len(documents)}")
    logger.info(f"  Sections: {len(sections)}")
    logger.info(f"  Evidence chunks: {len(evidence_chunks)}")
    logger.info("")

    # Step 2: Select business candidate evidence
    logger.info("Step 2: Selecting business candidate evidence...")
    candidates, stats = select_business_evidence(
        evidence_chunks,
        max_candidates=max_candidates,
    )

    # Save candidate evidence
    candidate_path = output_dir / "business_candidate_evidence.jsonl"
    save_candidate_evidence(candidates, candidate_path)

    logger.info(f"  Selected: {stats.selected_business_candidates}")
    logger.info(f"  Excluded SQL dump: {stats.excluded_sql_dump}")
    logger.info(f"  Excluded code/config: {stats.excluded_code_config}")
    logger.info(f"  Excluded no biz terms: {stats.excluded_no_business_terms}")
    logger.info(f"  Excluded INSERT-heavy: {stats.excluded_insert_heavy}")
    logger.info(f"  Excluded duplicate: {stats.excluded_duplicate}")
    logger.info(f"  Excluded too short: {stats.excluded_too_short}")
    logger.info("")

    if dry_run:
        logger.info("=== DRY RUN MODE ===")
        logger.info("Skipping graph extraction. Candidate evidence saved.")
        logger.info(f"  Candidate file: {candidate_path}")
        logger.info(f"  Candidates by doc_type: {stats.selected_by_doc_type}")
        logger.info(f"  Candidates by chunk_type: {stats.selected_by_chunk_type}")
        logger.info("")
        logger.info("Top source files:")
        for src, count in stats.top_selected_sources[:15]:
            logger.info(f"    {count:4d}  {src}")
        duration = time.time() - start_time
        logger.info(f"\nDry run complete in {duration:.1f}s")
        return

    # Step 3: Build business graph
    logger.info("Step 3: Building Business Semantic Graph (heuristic mode)...")
    graph_config = BusinessGraphConfig(
        run_id=run_id,
        dataset=dataset,
        max_nodes=500,
        max_edges=1000,
    )
    state = build_business_graph(candidates, config=graph_config)
    logger.info(f"  Nodes: {state.node_count}")
    logger.info(f"  Edges: {state.edge_count}")
    logger.info(f"  Rejected: {len(state.rejected)}")
    logger.info("")

    # Step 4: Save outputs
    logger.info("Step 4: Saving outputs...")
    nodes_path, edges_path, rejected_path = save_graph_outputs(state, output_dir)
    logger.info(f"  Nodes: {nodes_path}")
    logger.info(f"  Edges: {edges_path}")
    logger.info(f"  Rejected: {rejected_path}")
    logger.info("")

    # Step 5: Generate report
    duration = time.time() - start_time
    logger.info("Step 5: Generating report...")
    report_path = generate_report(
        state,
        stats,
        output_dir=output_dir,
        run_id=run_id,
        dataset=dataset,
        extraction_mode="heuristic",
        duration_seconds=duration,
        config_path=config_path,
    )
    logger.info(f"  Report: {report_path}")
    logger.info("")

    # Final summary
    logger.info("=" * 60)
    logger.info(f"Stage 05 COMPLETE in {duration:.1f}s")
    logger.info(f"  Business nodes: {state.node_count}")
    logger.info(f"  Business edges: {state.edge_count}")
    logger.info(f"  Rejected items: {len(state.rejected)}")
    logger.info(f"  Extraction mode: heuristic")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Build Business Semantic Graph (Stage 05)"
    )
    parser.add_argument(
        "--config", required=True, help="Path to config YAML"
    )
    parser.add_argument(
        "--run-id", default="murata_semantic_v2", help="Run identifier"
    )
    parser.add_argument(
        "--dataset", default="murata", help="Dataset name"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Select candidates only, do not extract graph"
    )
    parser.add_argument(
        "--max-candidates", type=int, default=2000,
        help="Maximum candidate evidence chunks to select"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()

    run_pipeline(
        config_path=args.config,
        run_id=args.run_id,
        dataset=args.dataset,
        dry_run=args.dry_run,
        max_candidates=args.max_candidates,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
