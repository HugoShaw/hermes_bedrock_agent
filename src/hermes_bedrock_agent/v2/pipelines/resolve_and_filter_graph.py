"""
Pipeline: Resolve and Filter Graph (Stage 07).

Orchestrates the full Stage 07 pipeline:
1. Load business and implementation graph outputs
2. Run entity resolution (merge duplicates, detect aliases)
3. Run quality filter (schema validation, evidence check, reject bad items)
4. Write all outputs
5. Generate reports
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.graph_entity_resolver import GraphEntityResolver
from hermes_bedrock_agent.v2.graph.graph_quality_filter import GraphQualityFilter
from hermes_bedrock_agent.v2.graph.graph_quality_reporter import GraphQualityReporter


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file."""
    items = []
    if not path.exists():
        return items
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    """Write items to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def run_pipeline(
    output_dir: str | Path,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the full Stage 07 pipeline.
    
    Args:
        output_dir: Path to data/outputs/murata_semantic_v2/
        run_id: Run identifier
        dataset: Dataset name
        dry_run: If True, only report planned actions without writing final outputs
        
    Returns:
        Combined stats dict
    """
    output_dir = Path(output_dir)

    # ======================================================================
    # Phase 1: Load inputs
    # ======================================================================
    print("[Stage 07] Loading graph inputs...")
    business_nodes = load_jsonl(output_dir / "business_nodes.jsonl")
    business_edges = load_jsonl(output_dir / "business_edges.jsonl")
    implementation_nodes = load_jsonl(output_dir / "implementation_nodes.jsonl")
    implementation_edges = load_jsonl(output_dir / "implementation_edges.jsonl")

    print(f"  Business: {len(business_nodes)} nodes, {len(business_edges)} edges")
    print(f"  Implementation: {len(implementation_nodes)} nodes, {len(implementation_edges)} edges")
    print(f"  Total input: {len(business_nodes) + len(implementation_nodes)} nodes, "
          f"{len(business_edges) + len(implementation_edges)} edges")

    # Load previously rejected items
    rejected_biz = load_jsonl(output_dir / "rejected_business_graph_items.jsonl")
    rejected_impl = load_jsonl(output_dir / "rejected_implementation_graph_items.jsonl")
    print(f"  Previously rejected: {len(rejected_biz)} business, {len(rejected_impl)} implementation")

    # ======================================================================
    # Phase 2: Entity Resolution
    # ======================================================================
    print("\n[Stage 07] Running entity resolution...")
    resolver = GraphEntityResolver(
        business_nodes=business_nodes,
        business_edges=business_edges,
        implementation_nodes=implementation_nodes,
        implementation_edges=implementation_edges,
    )
    resolution_stats = resolver.resolve()

    print(f"  Exact node_id merges: {resolution_stats['exact_node_id_merges']}")
    print(f"  Within-layer name merges: {resolution_stats['within_layer_name_merges']}")
    print(f"  Exact edge_id merges: {resolution_stats['exact_edge_id_merges']}")
    print(f"  Resolved nodes: {resolution_stats['resolved_nodes']}")
    print(f"  Resolved edges: {resolution_stats['resolved_edges']}")
    print(f"  Alias records: {resolution_stats['alias_records']}")
    print(f"  Cross-language candidates: {resolution_stats['cross_language_candidates']}")
    print(f"  Technical variant candidates: {resolution_stats['technical_variant_candidates']}")

    if dry_run:
        print("\n[DRY-RUN] Would proceed to quality filter...")
        print(f"[DRY-RUN] Alias records to write: {len(resolver.alias_records)}")
        print("[DRY-RUN] Skipping final output writes.")
        return {
            "mode": "dry_run",
            "resolution_stats": resolution_stats,
        }

    # ======================================================================
    # Phase 3: Quality Filter
    # ======================================================================
    print("\n[Stage 07] Running quality filter...")
    quality_filter = GraphQualityFilter(
        nodes=resolver.resolved_nodes,
        edges=resolver.resolved_edges,
        run_id=run_id,
        dataset=dataset,
    )
    filter_stats = quality_filter.filter()

    print(f"  Filtered nodes: {filter_stats['filtered_nodes']}")
    print(f"  Filtered edges: {filter_stats['filtered_edges']}")
    print(f"  Rejected items: {filter_stats['rejected_items']}")
    print(f"  Node evidence ratio: {filter_stats['node_evidence_ratio']:.2%}")
    print(f"  Edge evidence ratio: {filter_stats['edge_evidence_ratio']:.2%}")
    print(f"  Isolated nodes: {filter_stats['isolated_nodes']}")
    print(f"  API node count: {filter_stats['api_node_count']}")
    print(f"  SQL dump rejected: {filter_stats['sql_dump_rejected']}")
    print(f"  JOURNAL_BASE nodes: {filter_stats['journal_base_node_count']}")

    # ======================================================================
    # Phase 4: Write Outputs
    # ======================================================================
    print("\n[Stage 07] Writing outputs...")

    # Entity aliases
    write_jsonl(output_dir / "entity_aliases.jsonl", resolver.alias_records)
    print(f"  → entity_aliases.jsonl ({len(resolver.alias_records)} records)")

    # Filtered graph
    write_jsonl(output_dir / "filtered_graph_nodes.jsonl", quality_filter.filtered_nodes)
    print(f"  → filtered_graph_nodes.jsonl ({len(quality_filter.filtered_nodes)} records)")

    write_jsonl(output_dir / "filtered_graph_edges.jsonl", quality_filter.filtered_edges)
    print(f"  → filtered_graph_edges.jsonl ({len(quality_filter.filtered_edges)} records)")

    # Rejected items (combine previously rejected + newly rejected)
    all_rejected = rejected_biz + rejected_impl + quality_filter.rejected_items
    write_jsonl(output_dir / "rejected_graph_items.jsonl", all_rejected)
    print(f"  → rejected_graph_items.jsonl ({len(all_rejected)} records)")

    # ======================================================================
    # Phase 5: Generate Reports
    # ======================================================================
    print("\n[Stage 07] Generating reports...")
    reporter = GraphQualityReporter(
        resolution_stats=resolution_stats,
        filter_stats=filter_stats,
        alias_records=resolver.alias_records,
        filtered_nodes=quality_filter.filtered_nodes,
        filtered_edges=quality_filter.filtered_edges,
        rejected_items=quality_filter.rejected_items,
        run_id=run_id,
        dataset=dataset,
    )

    # Entity resolution report
    er_report = reporter.generate_entity_resolution_report()
    er_path = output_dir / "entity_resolution_report.md"
    er_path.write_text(er_report, encoding="utf-8")
    print(f"  → entity_resolution_report.md")

    # Graph quality report
    gq_report = reporter.generate_graph_quality_report()
    gq_path = output_dir / "graph_quality_report.md"
    gq_path.write_text(gq_report, encoding="utf-8")
    print(f"  → graph_quality_report.md")

    # ======================================================================
    # Done
    # ======================================================================
    print("\n[Stage 07] COMPLETE")
    print(f"  Final graph: {filter_stats['filtered_nodes']} nodes, {filter_stats['filtered_edges']} edges")
    print(f"  Rejected: {filter_stats['rejected_items']} items")
    print(f"  Evidence: nodes {filter_stats['node_evidence_ratio']:.0%}, edges {filter_stats['edge_evidence_ratio']:.0%}")

    return {
        "mode": "full",
        "resolution_stats": resolution_stats,
        "filter_stats": filter_stats,
    }
