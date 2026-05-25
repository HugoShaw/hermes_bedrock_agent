"""
Unify Excel graph pipeline — orchestrates entity resolution, cross-layer
linking, quality filtering, evidence link normalization, and report generation for X4.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_entity_resolver import (
    ExcelEntityResolver,
)
from hermes_bedrock_agent.v2.excel.excel_cross_layer_linker import (
    ExcelCrossLayerLinker,
)
from hermes_bedrock_agent.v2.excel.excel_graph_quality_filter import (
    ExcelGraphQualityFilter,
)
from hermes_bedrock_agent.v2.excel.excel_evidence_linker import (
    ExcelEvidenceLinker,
)
from hermes_bedrock_agent.v2.excel.excel_unified_graph_reporter import (
    ExcelUnifiedGraphReporter,
)

logger = logging.getLogger(__name__)


def run_unify_graph_pipeline(
    config_path: str | Path | None = None,
    run_id: str = "sample_20260519_excel_v1",
    dataset: str = "sample_20260519",
    output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run X4 graph unification pipeline.

    Steps:
    1. Load input graphs (implementation + business)
    2. Entity resolution (dedup within layers)
    3. Cross-layer linking
    4. Quality filtering
    5. Evidence link normalization
    6. Write outputs
    7. Generate reports
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load inputs
    logger.info("Step 1: Loading input graphs")
    impl_nodes = _load_jsonl(output_dir / "implementation_nodes.jsonl")
    impl_edges = _load_jsonl(output_dir / "implementation_edges.jsonl")
    biz_nodes = _load_jsonl(output_dir / "business_nodes.jsonl")
    biz_edges = _load_jsonl(output_dir / "business_edges.jsonl")
    chunks = _load_jsonl(output_dir / "evidence_chunks.jsonl")

    logger.info(
        f"Loaded: impl={len(impl_nodes)}n/{len(impl_edges)}e, "
        f"biz={len(biz_nodes)}n/{len(biz_edges)}e, "
        f"chunks={len(chunks)}"
    )

    input_biz_nodes = len(biz_nodes)
    input_biz_edges = len(biz_edges)
    input_impl_nodes = len(impl_nodes)
    input_impl_edges = len(impl_edges)

    # 2. Entity resolution
    logger.info("Step 2: Entity resolution")
    resolver = ExcelEntityResolver(dataset=dataset, run_id=run_id)
    entity_result = resolver.resolve(impl_nodes, impl_edges, biz_nodes, biz_edges)

    # 3. Cross-layer linking
    logger.info("Step 3: Cross-layer linking")
    # Separate resolved nodes by layer for linking
    biz_resolved = [n for n in entity_result.nodes if n.get("layer") == "business"]
    impl_resolved = [n for n in entity_result.nodes if n.get("layer") == "implementation"]

    linker = ExcelCrossLayerLinker(dataset=dataset, run_id=run_id)
    cross_layer_result = linker.link(biz_resolved, impl_resolved)

    # Add cross-layer links to edges
    all_edges = entity_result.edges + cross_layer_result.links

    # 4. Quality filtering
    logger.info("Step 4: Quality filtering")
    chunk_ids = {c["chunk_id"] for c in chunks}
    quality_filter = ExcelGraphQualityFilter(dataset=dataset, run_id=run_id)
    quality_result = quality_filter.filter(
        entity_result.nodes, all_edges, chunk_ids
    )

    # 5. Evidence link normalization
    logger.info("Step 5: Evidence link normalization")
    ev_linker = ExcelEvidenceLinker(dataset=dataset, run_id=run_id)
    link_result = ev_linker.link(
        quality_result.filtered_nodes,
        quality_result.filtered_edges,
        chunks,
    )

    # 6. Write outputs
    if not dry_run:
        logger.info("Step 6: Writing outputs")
        _write_jsonl(output_dir / "filtered_graph_nodes.jsonl", quality_result.filtered_nodes)
        _write_jsonl(output_dir / "filtered_graph_edges.jsonl", quality_result.filtered_edges)
        _write_jsonl(output_dir / "graph_nodes_linked.jsonl", link_result.linked_nodes)
        _write_jsonl(output_dir / "graph_edges_linked.jsonl", link_result.linked_edges)
        _write_jsonl(output_dir / "evidence_links.jsonl", link_result.evidence_links)
        _write_jsonl(output_dir / "entity_aliases.jsonl", entity_result.alias_records)
        _write_jsonl(output_dir / "cross_layer_links.jsonl", cross_layer_result.links)
        _write_jsonl(output_dir / "rejected_graph_items.jsonl", quality_result.rejected_items)
    else:
        logger.info("Step 6: [DRY-RUN] Skipping file writes")

    # 7. Generate reports
    logger.info("Step 7: Generating reports")
    reporter = ExcelUnifiedGraphReporter(
        output_dir=output_dir, dataset=dataset, run_id=run_id
    )
    reporter.generate_quality_report(quality_result, dry_run=dry_run)
    reporter.generate_evidence_link_report(
        link_result,
        len(quality_result.filtered_nodes),
        len(quality_result.filtered_edges),
        dry_run=dry_run,
    )
    decision = reporter.generate_unified_report(
        input_biz_nodes, input_biz_edges,
        input_impl_nodes, input_impl_edges,
        entity_result, cross_layer_result,
        quality_result, link_result,
        dry_run=dry_run,
    )

    summary = {
        "decision": decision,
        "dry_run": dry_run,
        "input_biz_nodes": input_biz_nodes,
        "input_biz_edges": input_biz_edges,
        "input_impl_nodes": input_impl_nodes,
        "input_impl_edges": input_impl_edges,
        "entity_merged_nodes": entity_result.merged_node_count,
        "entity_merged_edges": entity_result.merged_edge_count,
        "alias_count": len(entity_result.alias_records),
        "cross_layer_links": len(cross_layer_result.links),
        "cross_layer_by_strategy": cross_layer_result.link_count_by_strategy,
        "cross_layer_by_relation": cross_layer_result.link_count_by_relation,
        "filtered_nodes": len(quality_result.filtered_nodes),
        "filtered_edges": len(quality_result.filtered_edges),
        "rejected_count": len(quality_result.rejected_items),
        "linked_nodes": len(link_result.linked_nodes),
        "linked_edges": len(link_result.linked_edges),
        "evidence_links": link_result.total_links,
        "nodes_with_evidence": link_result.nodes_with_evidence,
        "edges_with_evidence": link_result.edges_with_evidence,
        "node_evidence_coverage": (
            link_result.nodes_with_evidence / len(link_result.linked_nodes)
            if link_result.linked_nodes else 0
        ),
        "edge_evidence_coverage": (
            link_result.edges_with_evidence / len(link_result.linked_edges)
            if link_result.linked_edges else 0
        ),
        "nodes_by_label": quality_result.nodes_by_label,
        "edges_by_relation": quality_result.edges_by_relation,
    }

    logger.info(f"Pipeline complete. Decision: {decision}")
    return summary


def _load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file."""
    if not path.exists():
        logger.warning(f"File not found: {path}")
        return []
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info(f"Wrote {len(records)} records to {path}")
