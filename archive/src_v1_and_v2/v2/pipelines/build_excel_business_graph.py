"""
Build Excel business graph pipeline — orchestrates evidence selection,
business graph extraction, quality filtering, and report generation for X3.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_business_evidence_selector import (
    ExcelBusinessEvidenceSelector,
)
from hermes_bedrock_agent.v2.excel.excel_business_graph_builder import (
    ExcelBusinessGraphBuilder,
)
from hermes_bedrock_agent.v2.excel.excel_business_graph_reporter import (
    ExcelBusinessGraphReporter,
)

logger = logging.getLogger(__name__)


def run_business_graph_pipeline(
    config_path: str | Path | None = None,
    run_id: str = "sample_20260519_excel_v1",
    dataset: str = "sample_20260519",
    output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run X3 business graph extraction pipeline.

    Steps:
    1. Load and select business candidate evidence
    2. Load normalized rows for row-level extraction
    3. Build business graph (process, rules, terms)
    4. Deduplicate and quality-filter
    5. Write outputs
    6. Generate report

    Returns summary dict.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Select business candidate evidence
    logger.info("Step 1: Selecting business candidate evidence")
    selector = ExcelBusinessEvidenceSelector(output_dir=output_dir)
    selector.load_data()
    selected_chunks, selection_result = selector.select()
    selector.write_results(selected_chunks)

    selection_stats = selection_result.to_dict()
    logger.info(
        f"Selected {len(selected_chunks)} / {selection_stats['total_chunks']} "
        f"chunks from {len(selection_stats['selected_sheets'])} sheets"
    )

    # 2. Load normalized rows
    logger.info("Step 2: Loading normalized rows")
    rows_path = output_dir / "excel_rows_normalized.jsonl"
    rows = []
    if rows_path.exists():
        rows = [json.loads(l) for l in open(rows_path)]
        logger.info(f"Loaded {len(rows)} normalized rows")

    # 3. Build business graph
    logger.info("Step 3: Building business graph")
    builder = ExcelBusinessGraphBuilder(
        dataset=dataset, run_id=run_id, output_dir=output_dir
    )
    result = builder.build(selected_chunks, rows)

    logger.info(
        f"Built: {len(result.nodes)} nodes, {len(result.edges)} edges, "
        f"{len(result.rejected)} rejected"
    )

    if dry_run:
        logger.info("[DRY-RUN] Skipping file writes")
        # Still generate report for dry-run
        reporter = ExcelBusinessGraphReporter(
            output_dir=output_dir, dataset=dataset, run_id=run_id
        )
        decision = reporter.generate_report(result, selection_stats, dry_run=True)
    else:
        # 4. Write outputs
        logger.info("Step 4: Writing outputs")
        files = builder.write_outputs()

        # 5. Generate report
        logger.info("Step 5: Generating report")
        reporter = ExcelBusinessGraphReporter(
            output_dir=output_dir, dataset=dataset, run_id=run_id
        )
        decision = reporter.generate_report(result, selection_stats, dry_run=False)

    summary = {
        "decision": decision,
        "dry_run": dry_run,
        "total_nodes": len(result.nodes),
        "total_edges": len(result.edges),
        "node_count_by_label": result.node_count_by_label,
        "edge_count_by_relation": result.edge_count_by_relation,
        "process_count": result.process_count,
        "step_count": result.step_count,
        "rule_count": result.rule_count,
        "term_count": result.term_count,
        "function_count": result.function_count,
        "domain_count": result.domain_count,
        "evidence_coverage_nodes": result.evidence_coverage_nodes,
        "evidence_coverage_edges": result.evidence_coverage_edges,
        "rejected_count": len(result.rejected),
        "low_confidence_count": len(result.low_confidence),
        "selection_stats": selection_stats,
    }

    logger.info(f"Pipeline complete. Decision: {decision}")
    return summary
