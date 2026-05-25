"""
Implementation Graph Reporter for Stage 06.

Generates the implementation_graph_report.md with comprehensive statistics
and quality metrics.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.implementation_evidence_selector import ImplSelectionStats

logger = logging.getLogger(__name__)


def generate_report(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    stats: ImplSelectionStats,
    config_path: str,
    run_id: str,
    dataset: str,
    extraction_mode: str,
    duration_seconds: float,
    output_path: Path,
) -> None:
    """Generate the implementation graph report."""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Compute node stats
    label_counts = Counter(n["label"] for n in nodes)
    relation_counts = Counter(e["relation_type"] for e in edges)

    # Evidence coverage
    nodes_with_ev = sum(1 for n in nodes if n.get("evidence_chunk_ids"))
    edges_with_ev = sum(1 for e in edges if e.get("evidence_chunk_ids"))
    node_ev_ratio = (nodes_with_ev / len(nodes) * 100) if nodes else 0
    edge_ev_ratio = (edges_with_ev / len(edges) * 100) if edges else 0

    # Node degree calculation
    degree: Counter = Counter()
    for edge in edges:
        degree[edge["source_node_id"]] += 1
        degree[edge["target_node_id"]] += 1

    # Map node_id -> display_name + label
    node_map = {n["node_id"]: (n["display_name"], n["label"]) for n in nodes}

    top_degree = degree.most_common(30)

    # Source file contribution
    source_contrib: Counter = Counter()
    for n in nodes:
        for sid in n.get("source_ids", []):
            source_contrib[sid] += 1

    # Tables and APIs
    tables = [n for n in nodes if n["label"] == "Table"]
    apis = [n for n in nodes if n["label"] == "API"]

    lines = []
    lines.append("# Implementation Graph Report\n")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Config:** {config_path}")
    lines.append(f"**Run ID:** {run_id}")
    lines.append(f"**Dataset:** {dataset}")
    lines.append(f"**Extraction Mode:** {extraction_mode}")
    lines.append(f"**Duration:** {duration_seconds:.1f}s\n")
    lines.append("---\n")

    # Input summary
    lines.append("## Input Summary\n")
    lines.append("| Metric | Value |")
    lines.append("| ------ | ----- |")
    lines.append(f"| Total evidence chunks | {stats.total_evidence_chunks} |")
    lines.append(f"| Selected implementation candidates | {stats.selected_impl_candidates} |")
    lines.append(f"| Excluded SQL dump | {stats.excluded_sql_dump} |")
    lines.append(f"| Excluded INSERT-heavy | {stats.excluded_insert_heavy} |")
    lines.append(f"| Excluded business-only | {stats.excluded_business_only} |")
    lines.append(f"| Excluded metadata-only | {stats.excluded_metadata_only} |")
    lines.append(f"| Excluded too short | {stats.excluded_too_short} |")
    lines.append(f"| Excluded no impl terms | {stats.excluded_no_impl_terms} |")
    lines.append(f"| Excluded duplicate | {stats.excluded_duplicate} |")
    lines.append("\n---\n")

    # Selected by doc_type
    lines.append("## Selected Candidates by Doc Type\n")
    lines.append("| doc_type | count |")
    lines.append("| -------- | ----- |")
    for dt, count in sorted(stats.selected_by_doc_type.items(), key=lambda x: -x[1]):
        lines.append(f"| {dt} | {count} |")

    lines.append("\n## Selected Candidates by Chunk Type\n")
    lines.append("| chunk_type | count |")
    lines.append("| ---------- | ----- |")
    for ct, count in sorted(stats.selected_by_chunk_type.items(), key=lambda x: -x[1]):
        lines.append(f"| {ct} | {count} |")
    lines.append("\n---\n")

    # Top selected sources
    lines.append("## Top Selected Source Files\n")
    lines.append("| Source | Chunks |")
    lines.append("| ------ | ------ |")
    for src, count in stats.top_selected_sources[:30]:
        lines.append(f"| {src} | {count} |")
    lines.append("\n---\n")

    # Graph summary
    lines.append("## Graph Output Summary\n")
    lines.append("| Metric | Value |")
    lines.append("| ------ | ----- |")
    lines.append(f"| Implementation nodes | {len(nodes)} |")
    lines.append(f"| Implementation edges | {len(edges)} |")
    lines.append(f"| Rejected items | {len(rejected)} |")
    lines.append("\n---\n")

    # Nodes by label
    lines.append("## Nodes by Label\n")
    lines.append("| Label | Count |")
    lines.append("| ----- | ----- |")
    for label, count in label_counts.most_common():
        lines.append(f"| {label} | {count} |")

    lines.append("\n## Edges by Relation Type\n")
    lines.append("| Relation Type | Count |")
    lines.append("| ------------- | ----- |")
    for rel, count in relation_counts.most_common():
        lines.append(f"| {rel} | {count} |")
    lines.append("\n---\n")

    # Evidence coverage
    lines.append("## Evidence Coverage\n")
    lines.append("| Metric | Value |")
    lines.append("| ------ | ----- |")
    lines.append(f"| Nodes with evidence | {nodes_with_ev} |")
    lines.append(f"| Edges with evidence | {edges_with_ev} |")
    lines.append(f"| Node evidence ratio | {node_ev_ratio:.2f}% |")
    lines.append(f"| Edge evidence ratio | {edge_ev_ratio:.2f}% |")
    lines.append("\n---\n")

    # Top 30 nodes by degree
    lines.append("## Top 30 Nodes by Degree\n")
    lines.append("| Node | Label | Degree |")
    lines.append("| ---- | ----- | ------ |")
    for nid, deg in top_degree:
        name, label = node_map.get(nid, (nid, "?"))
        lines.append(f"| {name} | {label} | {deg} |")
    lines.append("\n---\n")

    # Top tables
    if tables:
        lines.append("## Top 30 Tables\n")
        lines.append("| Table | Evidence Count |")
        lines.append("| ----- | ------------- |")
        for t in sorted(tables, key=lambda x: -len(x.get("evidence_chunk_ids", [])))[:30]:
            lines.append(f"| {t['display_name']} | {len(t.get('evidence_chunk_ids', []))} |")
        lines.append("\n---\n")

    # Top APIs
    if apis:
        lines.append("## Top 30 APIs\n")
        lines.append("| API | Evidence Count |")
        lines.append("| --- | ------------- |")
        for a in sorted(apis, key=lambda x: -len(x.get("evidence_chunk_ids", [])))[:30]:
            lines.append(f"| {a['display_name']} | {len(a.get('evidence_chunk_ids', []))} |")
        lines.append("\n---\n")

    # Warnings
    lines.append("## Warnings & Limitations\n")
    lines.append("- Extraction mode is **heuristic** — entity coverage may be incomplete")
    lines.append("- LLM-based extraction can improve recall and precision in future iterations")
    lines.append(f"- {stats.excluded_sql_dump} SQL dump chunks were excluded (JOURNAL_BASE etc.)")
    lines.append(f"- {stats.excluded_insert_heavy} INSERT-heavy chunks were excluded")
    if not apis:
        lines.append("- No API nodes extracted (no API doc chunks in current evidence)")
    lines.append("\n---\n")

    # Next action
    lines.append("## Next Recommended Action\n")
    lines.append("Execute Stage 07: Entity Resolution and Graph Quality Filter\n")
    lines.append("Merge duplicate entities across Business and Implementation graphs,")
    lines.append("resolve aliases, and filter low-quality items.\n")

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + "\n"
    output_path.write_text(content, encoding="utf-8")
    logger.info(f"Report written to {output_path}")
