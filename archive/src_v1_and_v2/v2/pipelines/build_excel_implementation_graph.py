"""
Build Excel implementation graph pipeline — orchestrates evidence selection,
graph extraction, quality filtering, and report generation for X2.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_implementation_evidence_selector import (
    ExcelImplementationEvidenceSelector,
)
from hermes_bedrock_agent.v2.excel.excel_implementation_graph_builder import (
    ExcelImplementationGraphBuilder,
)
from hermes_bedrock_agent.v2.excel.excel_implementation_graph_reporter import (
    ExcelImplementationGraphReporter,
)

logger = logging.getLogger(__name__)


class BuildExcelImplementationGraphPipeline:
    """Pipeline for X2: Excel Implementation Graph Extraction.

    Steps:
    1. Select implementation-relevant evidence chunks
    2. Run mapping extractor + API extractor
    3. Merge, deduplicate, quality filter
    4. Write outputs (nodes, edges, rejected, low-confidence)
    5. Generate report
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
        output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
    ) -> None:
        self.config = config or {}
        self.dataset = dataset
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        """Execute the full pipeline.

        Parameters
        ----------
        dry_run : bool
            If True, only report what would be done without writing graph files.

        Returns
        -------
        dict with pipeline results.
        """
        logger.info(f"=== X2: Build Excel Implementation Graph ===")
        logger.info(f"Dataset: {self.dataset}, Run ID: {self.run_id}")
        logger.info(f"Output: {self.output_dir}")
        logger.info(f"Dry run: {dry_run}")

        # Step 1: Select candidate evidence
        logger.info("Step 1: Selecting implementation candidate evidence...")
        selector = ExcelImplementationEvidenceSelector(output_dir=self.output_dir)
        selector.load_data()
        selected_chunks, selection_result = selector.select()

        if not dry_run:
            selector.write_results()

        logger.info(
            f"Selected {selection_result.selected_chunks}/{selection_result.total_chunks} "
            f"chunks from {len(selection_result.selected_sheets)} sheets"
        )

        if not selected_chunks:
            logger.error("No candidate chunks selected — cannot build graph")
            return {"error": "no_candidates", "selection": selection_result.to_dict()}

        # Step 2: Build implementation graph
        logger.info("Step 2: Extracting implementation graph...")
        builder = ExcelImplementationGraphBuilder(
            dataset=self.dataset,
            run_id=self.run_id,
            output_dir=self.output_dir,
        )
        stats = builder.build(selected_chunks, dry_run=dry_run)

        logger.info(
            f"Extracted {stats['node_count']} nodes, {stats['edge_count']} edges, "
            f"{stats['maps_to_count']} MAPS_TO"
        )

        # Step 3: Generate report
        logger.info("Step 3: Generating report...")
        reporter = ExcelImplementationGraphReporter(
            dataset=self.dataset,
            run_id=self.run_id,
            output_dir=self.output_dir,
        )
        report_path = reporter.generate_report(
            stats=stats,
            selection_result=selection_result,
            nodes=builder.nodes,
            edges=builder.edges,
            rejected=builder.rejected,
            low_confidence=builder.low_confidence,
        )

        # Final summary
        result = {
            "dry_run": dry_run,
            "selection": selection_result.to_dict(),
            "stats": stats,
            "node_count": len(builder.nodes),
            "edge_count": len(builder.edges),
            "maps_to_count": stats.get("maps_to_count", 0),
            "rejected_count": len(builder.rejected),
            "low_confidence_count": len(builder.low_confidence),
            "report_path": str(report_path),
            "outputs": {
                "implementation_nodes": str(self.output_dir / "implementation_nodes.jsonl"),
                "implementation_edges": str(self.output_dir / "implementation_edges.jsonl"),
                "rejected": str(self.output_dir / "rejected_excel_implementation_graph_items.jsonl"),
                "low_confidence": str(self.output_dir / "low_confidence_excel_implementation_items.jsonl"),
                "candidate_evidence": str(self.output_dir / "excel_implementation_candidate_evidence.jsonl"),
                "report": str(report_path),
            },
        }

        logger.info(f"=== X2 Complete: {stats['node_count']} nodes, {stats['edge_count']} edges ===")
        return result
