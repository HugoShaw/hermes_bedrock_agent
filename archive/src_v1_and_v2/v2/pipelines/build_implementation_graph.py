"""
Pipeline: Build Implementation Graph (Stage 06).

Orchestrates the full Stage 06 pipeline:
1. Load evidence chunks
2. Select implementation candidate evidence
3. Build implementation graph (nodes + edges)
4. Generate report
5. Save all outputs

Supports --dry-run mode which only selects candidates and reports stats.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.implementation_evidence_selector import (
    ImplSelectionStats,
    save_candidate_evidence,
    select_implementation_evidence,
)
from hermes_bedrock_agent.v2.graph.implementation_graph_builder import (
    ImplGraphConfig,
    build_implementation_graph,
    save_graph_outputs,
)
from hermes_bedrock_agent.v2.graph.implementation_graph_reporter import (
    generate_report,
)

logger = logging.getLogger(__name__)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file into a list of dicts."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def run_pipeline(
    config_path: str,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    dry_run: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Run the Stage 06 Implementation Graph pipeline.

    Args:
        config_path: Path to the config YAML.
        run_id: Run identifier.
        dataset: Dataset name.
        dry_run: If True, only select candidates and report (no extraction).
        output_dir: Override output directory.

    Returns:
        Summary dict with counts and paths.
    """
    start_time = time.time()

    # Determine output directory
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = Path(f"data/outputs/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Step 1: Load evidence chunks
    # =========================================================================
    evidence_path = out_dir / "evidence_chunks.jsonl"
    logger.info(f"Loading evidence chunks from {evidence_path}")
    evidence_chunks = _load_jsonl(evidence_path)
    logger.info(f"Loaded {len(evidence_chunks)} evidence chunks")

    # =========================================================================
    # Step 2: Select implementation candidate evidence
    # =========================================================================
    logger.info("Selecting implementation candidate evidence...")
    candidates, stats = select_implementation_evidence(evidence_chunks)

    # Save candidates
    candidates_path = out_dir / "implementation_candidate_evidence.jsonl"
    save_candidate_evidence(candidates, candidates_path)
    logger.info(f"Saved {stats.selected_impl_candidates} candidates to {candidates_path}")

    # Print stats summary
    print(f"\n=== Implementation Evidence Selection ===")
    print(f"  Total chunks: {stats.total_evidence_chunks}")
    print(f"  Selected candidates: {stats.selected_impl_candidates}")
    print(f"  Excluded SQL dump: {stats.excluded_sql_dump}")
    print(f"  Excluded INSERT-heavy: {stats.excluded_insert_heavy}")
    print(f"  Excluded business-only: {stats.excluded_business_only}")
    print(f"  Excluded too short: {stats.excluded_too_short}")
    print(f"  Excluded no impl terms: {stats.excluded_no_impl_terms}")
    print(f"  Excluded duplicate: {stats.excluded_duplicate}")
    print(f"  By doc_type: {stats.selected_by_doc_type}")
    print(f"  By chunk_type: {stats.selected_by_chunk_type}")

    if dry_run:
        elapsed = time.time() - start_time
        print(f"\n=== DRY RUN COMPLETE ({elapsed:.1f}s) ===")
        print(f"  Would extract implementation graph from {stats.selected_impl_candidates} candidates")
        print(f"  Top sources: {stats.top_selected_sources[:10]}")
        return {
            "mode": "dry_run",
            "candidates_selected": stats.selected_impl_candidates,
            "duration_seconds": elapsed,
            "candidates_path": str(candidates_path),
        }

    # =========================================================================
    # Step 3: Build implementation graph
    # =========================================================================
    logger.info("Building implementation graph...")
    graph_config = ImplGraphConfig(run_id=run_id, dataset=dataset)

    # Optionally load documents/sections (not strictly needed for heuristic)
    documents = None
    sections = None
    docs_path = out_dir / "documents.jsonl"
    sections_path = out_dir / "sections.jsonl"
    if docs_path.exists():
        documents = _load_jsonl(docs_path)
    if sections_path.exists():
        sections = _load_jsonl(sections_path)

    nodes, edges, rejected = build_implementation_graph(
        candidates, documents=documents, sections=sections, config=graph_config
    )

    # =========================================================================
    # Step 4: Save graph outputs
    # =========================================================================
    save_graph_outputs(nodes, edges, rejected, out_dir)

    # =========================================================================
    # Step 5: Generate report
    # =========================================================================
    elapsed = time.time() - start_time
    report_path = out_dir / "implementation_graph_report.md"
    generate_report(
        nodes=nodes,
        edges=edges,
        rejected=rejected,
        stats=stats,
        config_path=config_path,
        run_id=run_id,
        dataset=dataset,
        extraction_mode="heuristic",
        duration_seconds=elapsed,
        output_path=report_path,
    )

    print(f"\n=== Stage 06 Complete ({elapsed:.1f}s) ===")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Edges: {len(edges)}")
    print(f"  Rejected: {len(rejected)}")
    print(f"  Report: {report_path}")

    return {
        "mode": "full",
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "rejected_count": len(rejected),
        "candidates_selected": stats.selected_impl_candidates,
        "duration_seconds": elapsed,
        "output_dir": str(out_dir),
        "report_path": str(report_path),
    }
