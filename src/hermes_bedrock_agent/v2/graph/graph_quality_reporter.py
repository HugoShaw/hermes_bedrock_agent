"""
Graph Quality Reporter for Stage 07.

Generates:
- entity_resolution_report.md
- graph_quality_report.md
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class GraphQualityReporter:
    """Generates Stage 07 reports."""

    def __init__(
        self,
        resolution_stats: dict[str, Any],
        filter_stats: dict[str, Any],
        alias_records: list[dict[str, Any]],
        filtered_nodes: list[dict[str, Any]],
        filtered_edges: list[dict[str, Any]],
        rejected_items: list[dict[str, Any]],
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
    ):
        self.resolution_stats = resolution_stats
        self.filter_stats = filter_stats
        self.alias_records = alias_records
        self.filtered_nodes = filtered_nodes
        self.filtered_edges = filtered_edges
        self.rejected_items = rejected_items
        self.run_id = run_id
        self.dataset = dataset

    def generate_entity_resolution_report(self) -> str:
        """Generate entity_resolution_report.md content."""
        s = self.resolution_stats
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Entity Resolution Report",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            f"**Generated:** {now}",
            f"**Stage:** 07 - Entity Resolution and Graph Quality",
            "",
            "---",
            "",
            "## 1. Input Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Business Nodes | {s['input_business_nodes']} |",
            f"| Business Edges | {s['input_business_edges']} |",
            f"| Implementation Nodes | {s['input_implementation_nodes']} |",
            f"| Implementation Edges | {s['input_implementation_edges']} |",
            f"| **Total Input Nodes** | **{s['total_input_nodes']}** |",
            f"| **Total Input Edges** | **{s['total_input_edges']}** |",
            "",
            "---",
            "",
            "## 2. Merge Summary",
            "",
            f"| Merge Type | Count |",
            f"|------------|-------|",
            f"| Exact node_id duplicate merges | {s['exact_node_id_merges']} |",
            f"| Exact edge_id duplicate merges | {s['exact_edge_id_merges']} |",
            f"| Within-layer name duplicate merges | {s['within_layer_name_merges']} |",
            f"| **Resolved Nodes** | **{s['resolved_nodes']}** |",
            f"| **Resolved Edges** | **{s['resolved_edges']}** |",
            "",
            "---",
            "",
            "## 3. Alias Records",
            "",
            f"| Alias Type | Count |",
            f"|------------|-------|",
        ]

        alias_types = Counter(a["alias_type"] for a in self.alias_records)
        for atype, count in alias_types.most_common():
            lines.append(f"| {atype} | {count} |")
        lines.append(f"| **Total** | **{len(self.alias_records)}** |")
        lines.append("")

        # Examples of cross-language candidates
        cross_lang = [a for a in self.alias_records if a["alias_type"] == "cross_language_candidate"]
        if cross_lang:
            lines.extend([
                "---",
                "",
                "## 4. Cross-Language Alias Candidates (NOT auto-merged)",
                "",
                "These are potential cross-language aliases detected but NOT automatically merged.",
                "Manual review is recommended before merging.",
                "",
            ])
            for a in cross_lang[:20]:
                lines.append(f"- **{a['alias']}** → canonical: `{a['canonical_node_id']}`")
                lines.append(f"  - Reason: {a['reason']}")
                lines.append(f"  - Confidence: {a['confidence']}")
                lines.append("")

        # Examples of technical variants
        tech_variants = [a for a in self.alias_records if a["alias_type"] == "technical_variant"]
        if tech_variants:
            lines.extend([
                "---",
                "",
                "## 5. Technical Variant Candidates",
                "",
            ])
            for a in tech_variants[:20]:
                lines.append(f"- **{a['alias']}** → canonical: `{a['canonical_node_id']}`")
                lines.append(f"  - Reason: {a['reason']}")
                lines.append("")

        # Existing aliases
        exact_aliases = [a for a in self.alias_records if a["alias_type"] == "exact"]
        if exact_aliases:
            lines.extend([
                "---",
                "",
                "## 6. Pre-existing Aliases (from extraction)",
                "",
                f"Total: {len(exact_aliases)} pre-existing alias records.",
                "",
            ])
            for a in exact_aliases[:15]:
                lines.append(f"- `{a['canonical_node_id']}` → alias: **{a['alias']}**")

        lines.extend([
            "",
            "---",
            "",
            "## 7. Warnings and Limitations",
            "",
            "- Cross-language alias detection is keyword-based; may miss non-obvious aliases.",
            "- Only exact/normalized matches are auto-merged; fuzzy matches are candidates only.",
            "- No LLM-assisted entity resolution in this stage (heuristic only).",
            "- Generic names ('data', 'system', 'process') are flagged but not merged.",
            "",
            "---",
            "",
            "## 8. Next Recommended Action",
            "",
            "Proceed to Stage 08 (Evidence Linker) to add post-hoc evidence links.",
            "Cross-language alias candidates should be reviewed manually before merging.",
            "",
        ])

        return "\n".join(lines)

    def generate_graph_quality_report(self) -> str:
        """Generate graph_quality_report.md content."""
        s = self.filter_stats
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Graph Quality Report",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            f"**Generated:** {now}",
            f"**Stage:** 07 - Entity Resolution and Graph Quality",
            "",
            "---",
            "",
            "## 1. Overall Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Input Nodes (after resolution) | {s['input_nodes']} |",
            f"| Input Edges (after resolution) | {s['input_edges']} |",
            f"| **Filtered Nodes (kept)** | **{s['filtered_nodes']}** |",
            f"| **Filtered Edges (kept)** | **{s['filtered_edges']}** |",
            f"| Rejected Items | {s['rejected_items']} |",
            f"| Rejected Nodes | {s['rejected_nodes']} |",
            f"| Rejected Edges | {s['rejected_edges']} |",
            "",
            "---",
            "",
            "## 2. Node Labels Distribution",
            "",
            f"| Label | Count |",
            f"|-------|-------|",
        ]
        for label, count in sorted(s["node_labels"].items(), key=lambda x: -x[1]):
            lines.append(f"| {label} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## 3. Relation Types Distribution",
            "",
            f"| Relation Type | Count |",
            f"|---------------|-------|",
        ])
        for rel, count in sorted(s["edge_relations"].items(), key=lambda x: -x[1]):
            lines.append(f"| {rel} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## 4. Layer Distribution",
            "",
            "### Nodes by Layer",
            "",
            f"| Layer | Count |",
            f"|-------|-------|",
        ])
        for layer, count in s["node_layers"].items():
            lines.append(f"| {layer} | {count} |")

        lines.extend([
            "",
            "### Edges by Layer",
            "",
            f"| Layer | Count |",
            f"|-------|-------|",
        ])
        for layer, count in s["edge_layers"].items():
            lines.append(f"| {layer} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## 5. Evidence Coverage",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Nodes with evidence | {s['nodes_with_evidence']} / {s['filtered_nodes']} |",
            f"| Node evidence ratio | {s['node_evidence_ratio']:.2%} |",
            f"| Edges with evidence | {s['edges_with_evidence']} / {s['filtered_edges']} |",
            f"| Edge evidence ratio | {s['edge_evidence_ratio']:.2%} |",
            "",
            "---",
            "",
            "## 6. Quality Warnings",
            "",
            f"| Warning Type | Count |",
            f"|--------------|-------|",
            f"| Isolated nodes (degree=0) | {s['isolated_nodes']} |",
            f"| Generic name warnings | {s['generic_name_warnings']} |",
            f"| API nodes (may need enrichment) | {s['api_node_count']} |",
            "",
        ])

        # API node warning
        if s["api_node_count"] == 0:
            lines.extend([
                "⚠️ **API Node Count = 0**: No standalone API documentation was found in the current",
                "evidence set. API nodes can be added in future iterations when API docs are available.",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## 7. SQL Dump Contamination Check",
            "",
            f"- SQL dump artifacts rejected: {s['sql_dump_rejected']}",
            f"- JOURNAL_BASE nodes in filtered graph: {s['journal_base_node_count']}",
            "",
        ])
        if s["journal_base_node_count"] <= 5:
            lines.append("✅ JOURNAL_BASE does NOT dominate the graph.")
        else:
            lines.append("⚠️ JOURNAL_BASE has significant presence — review needed.")
        lines.append("")

        # Top high-degree nodes
        lines.extend([
            "---",
            "",
            "## 8. Top 30 High-Degree Nodes",
            "",
            "| Node | Label | Layer | Degree |",
            "|------|-------|-------|--------|",
        ])
        degree_sorted = sorted(
            self.filtered_nodes,
            key=lambda n: n.get("properties", {}).get("degree", 0),
            reverse=True,
        )[:30]
        for n in degree_sorted:
            d = n.get("properties", {}).get("degree", 0)
            lines.append(f"| {n['name'][:40]} | {n['label']} | {n['layer']} | {d} |")

        # Top rejected items
        if self.rejected_items:
            lines.extend([
                "",
                "---",
                "",
                "## 9. Top 30 Rejected Items",
                "",
                "| ID | Type | Reasons |",
                "|----|------|---------|",
            ])
            for item in self.rejected_items[:30]:
                item_id = item.get("item_id", "?")[:40]
                item_type = item.get("item_type", "?")
                reasons = "; ".join(item.get("reasons", []))[:80]
                lines.append(f"| {item_id} | {item_type} | {reasons} |")

        lines.extend([
            "",
            "---",
            "",
            "## 10. Next Recommended Action",
            "",
            "Execute Stage 08: Evidence Linker.",
            "- Create post-hoc evidence links between graph nodes/edges and evidence chunks.",
            "- Generate evidence_links.jsonl and graph_nodes_linked.jsonl / graph_edges_linked.jsonl.",
            "",
        ])

        return "\n".join(lines)
