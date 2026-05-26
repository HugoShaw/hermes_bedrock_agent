"""
Business Graph Reporter for Stage 05.

Generates the business_graph_report.md with comprehensive statistics
and quality metrics.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.business_evidence_selector import SelectionStats
from hermes_bedrock_agent.v2.graph.business_graph_builder import BuilderState

logger = logging.getLogger(__name__)


def generate_report(
    state: BuilderState,
    stats: SelectionStats,
    *,
    output_dir: Path,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    extraction_mode: str = "heuristic",
    duration_seconds: float = 0.0,
    config_path: str = "",
) -> Path:
    """Generate the business graph report.

    Args:
        state: Builder state with nodes, edges, rejected items.
        stats: Selection statistics.
        output_dir: Directory to write the report.
        run_id: Run identifier.
        dataset: Dataset name.
        extraction_mode: 'heuristic', 'llm', or 'hybrid'.
        duration_seconds: Pipeline execution duration.
        config_path: Path to config file used.

    Returns:
        Path to the generated report.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "business_graph_report.md"

    # Compute statistics
    node_label_counts = Counter(n["label"] for n in state.nodes.values())
    edge_relation_counts = Counter(e["relation_type"] for e in state.edges.values())

    # Source document contribution
    source_counter: Counter = Counter()
    for node in state.nodes.values():
        for sid in node.get("source_ids", []):
            source_counter[sid] += 1

    # Evidence coverage
    nodes_with_evidence = sum(
        1 for n in state.nodes.values() if n.get("evidence_chunk_ids")
    )
    edges_with_evidence = sum(
        1 for e in state.edges.values() if e.get("evidence_chunk_ids")
    )
    node_evidence_ratio = (
        nodes_with_evidence / len(state.nodes) if state.nodes else 0.0
    )
    edge_evidence_ratio = (
        edges_with_evidence / len(state.edges) if state.edges else 0.0
    )

    # Node degree calculation
    degree_counter: Counter = Counter()
    for edge in state.edges.values():
        degree_counter[edge["source_node_id"]] += 1
        degree_counter[edge["target_node_id"]] += 1

    top_nodes_by_degree = []
    for node_id, degree in degree_counter.most_common(30):
        node = state.nodes.get(node_id)
        if node:
            top_nodes_by_degree.append((node["display_name"], node["label"], degree))

    # Build report
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = []
    lines.append("# Business Semantic Graph Report")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Config:** {config_path}")
    lines.append(f"**Run ID:** {run_id}")
    lines.append(f"**Dataset:** {dataset}")
    lines.append(f"**Extraction Mode:** {extraction_mode}")
    lines.append(f"**Duration:** {duration_seconds:.1f}s")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Input Summary
    lines.append("## Input Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| ------ | ----- |")
    lines.append(f"| Total evidence chunks | {stats.total_evidence_chunks} |")
    lines.append(f"| Selected business candidates | {stats.selected_business_candidates} |")
    lines.append(f"| Excluded SQL dump | {stats.excluded_sql_dump} |")
    lines.append(f"| Excluded code/config | {stats.excluded_code_config} |")
    lines.append(f"| Excluded metadata-only | {stats.excluded_metadata_only} |")
    lines.append(f"| Excluded too short | {stats.excluded_too_short} |")
    lines.append(f"| Excluded no business terms | {stats.excluded_no_business_terms} |")
    lines.append(f"| Excluded INSERT-heavy | {stats.excluded_insert_heavy} |")
    lines.append(f"| Excluded duplicate | {stats.excluded_duplicate} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Selected by doc_type
    lines.append("## Selected Candidates by Doc Type")
    lines.append("")
    lines.append("| doc_type | count |")
    lines.append("| -------- | ----- |")
    for dt, count in sorted(stats.selected_by_doc_type.items(), key=lambda x: -x[1]):
        lines.append(f"| {dt} | {count} |")
    lines.append("")

    # Selected by chunk_type
    lines.append("## Selected Candidates by Chunk Type")
    lines.append("")
    lines.append("| chunk_type | count |")
    lines.append("| ---------- | ----- |")
    for ct, count in sorted(stats.selected_by_chunk_type.items(), key=lambda x: -x[1]):
        lines.append(f"| {ct} | {count} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Top source files
    lines.append("## Top Selected Source Files")
    lines.append("")
    lines.append("| Source | Chunks |")
    lines.append("| ------ | ------ |")
    for src, count in stats.top_selected_sources[:30]:
        lines.append(f"| {src} | {count} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Graph Output
    lines.append("## Graph Output Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| ------ | ----- |")
    lines.append(f"| Business nodes | {state.node_count} |")
    lines.append(f"| Business edges | {state.edge_count} |")
    lines.append(f"| Rejected items | {len(state.rejected)} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Node count by label
    lines.append("## Nodes by Label")
    lines.append("")
    lines.append("| Label | Count |")
    lines.append("| ----- | ----- |")
    for label, count in node_label_counts.most_common():
        lines.append(f"| {label} | {count} |")
    lines.append("")

    # Edge count by relation type
    lines.append("## Edges by Relation Type")
    lines.append("")
    lines.append("| Relation Type | Count |")
    lines.append("| ------------- | ----- |")
    for rel, count in edge_relation_counts.most_common():
        lines.append(f"| {rel} | {count} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Evidence Coverage
    lines.append("## Evidence Coverage")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| ------ | ----- |")
    lines.append(f"| Nodes with evidence | {nodes_with_evidence} |")
    lines.append(f"| Edges with evidence | {edges_with_evidence} |")
    lines.append(f"| Node evidence ratio | {node_evidence_ratio:.2%} |")
    lines.append(f"| Edge evidence ratio | {edge_evidence_ratio:.2%} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Top nodes by degree
    lines.append("## Top 30 Nodes by Degree")
    lines.append("")
    lines.append("| Node | Label | Degree |")
    lines.append("| ---- | ----- | ------ |")
    for display_name, label, degree in top_nodes_by_degree:
        lines.append(f"| {display_name} | {label} | {degree} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Warnings
    lines.append("## Warnings & Limitations")
    lines.append("")
    warnings = []
    if extraction_mode == "heuristic":
        warnings.append("- Extraction mode is **heuristic** — entity coverage may be incomplete")
        warnings.append("- LLM-based extraction can improve recall and precision in future iterations")
    if stats.excluded_sql_dump > 1000:
        warnings.append(f"- {stats.excluded_sql_dump} SQL dump chunks were excluded (JOURNAL_BASE etc.)")
    if node_evidence_ratio < 1.0:
        warnings.append(f"- {state.node_count - nodes_with_evidence} nodes lack evidence links")
    if edge_evidence_ratio < 1.0:
        warnings.append(f"- {state.edge_count - edges_with_evidence} edges lack evidence links")
    if not warnings:
        warnings.append("- No critical warnings")
    for w in warnings:
        lines.append(w)
    lines.append("")
    lines.append("---")
    lines.append("")

    # Next action
    lines.append("## Next Recommended Action")
    lines.append("")
    lines.append("Execute Stage 06: Implementation Graph")
    lines.append("")
    lines.append("Build the Implementation Graph from source code, SQL DDL, API docs,")
    lines.append("and configuration files. Link implementation entities to evidence chunks.")
    lines.append("")

    report_content = "\n".join(lines)
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"Report written to {report_path}")

    return report_path
