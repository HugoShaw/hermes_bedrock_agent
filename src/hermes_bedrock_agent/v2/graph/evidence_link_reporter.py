"""
Evidence Link Reporter for Stage 08.

Generates evidence_link_report.md with comprehensive statistics
on evidence linking quality and coverage.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


class EvidenceLinkReporter:
    """Generates Stage 08 evidence link report."""

    def __init__(
        self,
        stats: dict[str, Any],
        linked_nodes: list[dict[str, Any]],
        linked_edges: list[dict[str, Any]],
        evidence_links: list[dict[str, Any]],
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
    ):
        self.stats = stats
        self.linked_nodes = linked_nodes
        self.linked_edges = linked_edges
        self.evidence_links = evidence_links
        self.run_id = run_id
        self.dataset = dataset

    def generate_report(self) -> str:
        """Generate evidence_link_report.md content."""
        s = self.stats
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Evidence Link Report",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            f"**Generated:** {now}",
            f"**Stage:** 08 - Evidence Linker",
            "",
            "---",
            "",
            "## 1. Overall Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Input filtered nodes | {s['input_nodes']} |",
            f"| Input filtered edges | {s['input_edges']} |",
            f"| Evidence chunk count | {s['evidence_chunk_count']} |",
            f"| Output linked nodes | {s['linked_nodes']} |",
            f"| Output linked edges | {s['linked_edges']} |",
            f"| **Evidence link count** | **{s['evidence_link_count']}** |",
            "",
            "---",
            "",
            "## 2. Evidence Coverage",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Nodes with evidence | {s['nodes_with_evidence']} / {s['linked_nodes']} |",
            f"| Node evidence ratio | {s['node_evidence_ratio']:.2%} |",
            f"| Edges with evidence | {s['edges_with_evidence']} / {s['linked_edges']} |",
            f"| Edge evidence ratio | {s['edge_evidence_ratio']:.2%} |",
            f"| Avg evidence links per node | {s['avg_evidence_per_node']:.1f} |",
            f"| Avg evidence links per edge | {s['avg_evidence_per_edge']:.1f} |",
            "",
            "---",
            "",
            "## 3. Link Count by Strategy",
            "",
            "| Strategy | Count | % |",
            "|----------|-------|---|",
        ]

        total_links = s["evidence_link_count"]
        for strategy, count in sorted(
            s["link_count_by_strategy"].items(), key=lambda x: -x[1]
        ):
            pct = count / max(total_links, 1) * 100
            lines.append(f"| {strategy} | {count} | {pct:.1f}% |")
        lines.append(f"| **Total** | **{total_links}** | **100%** |")

        lines.extend([
            "",
            "---",
            "",
            "## 4. Evidence Quality Score Distribution",
            "",
            "| Score Range | Count |",
            "|-------------|-------|",
        ])
        for score_range, count in s.get("quality_score_distribution", {}).items():
            lines.append(f"| {score_range} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## 5. Evidence Warnings",
            "",
            "| Warning Type | Count |",
            "|--------------|-------|",
            f"| Nodes with no evidence links | {s['nodes_no_evidence']} |",
            f"| Edges with no evidence links | {s['edges_no_evidence']} |",
            f"| Nodes with fallback-only evidence | {s['fallback_only_nodes']} |",
            f"| Edges with fallback-only evidence | {s['fallback_only_edges']} |",
            f"| Isolated nodes with weak evidence | {s['isolated_nodes_weak']} |",
            f"| API node count (may need enrichment) | {s['api_node_count']} |",
            "",
        ])

        if s["api_node_count"] == 0:
            lines.extend([
                "⚠️ **API Node Count = 0**: No standalone API documentation was found.",
                "API nodes can be added in future iterations when API docs are available.",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## 6. SQL Dump and JOURNAL_BASE Contamination Check",
            "",
            f"- Evidence links pointing to JOURNAL_BASE dump: **{s['journal_base_links']}**",
            f"- Evidence links pointing to SQL dump artifacts: **{s['sql_dump_links']}**",
            "",
        ])
        if s["journal_base_links"] == 0 and s["sql_dump_links"] == 0:
            lines.append("✅ No SQL dump or JOURNAL_BASE contamination in evidence links.")
        else:
            lines.append("⚠️ Some evidence links reference SQL dump data — review recommended.")
        lines.append("")

        # Top 30 graph items by evidence count
        lines.extend([
            "---",
            "",
            "## 7. Top 30 Graph Items by Evidence Count",
            "",
            "| Item ID | Type | Label/Relation | Layer | Evidence Count |",
            "|---------|------|----------------|-------|----------------|",
        ])
        all_items = [
            (n["node_id"], "node", n["label"], n["layer"], n.get("properties", {}).get("evidence_count", 0))
            for n in self.linked_nodes
        ] + [
            (e["edge_id"], "edge", e["relation_type"], e["layer"], e.get("properties", {}).get("evidence_count", 0))
            for e in self.linked_edges
        ]
        all_items.sort(key=lambda x: -x[4])
        for item_id, itype, label, layer, count in all_items[:30]:
            lines.append(f"| {item_id[:30]}... | {itype} | {label} | {layer} | {count} |")

        # Top 30 most-linked evidence chunks
        lines.extend([
            "",
            "---",
            "",
            "## 8. Top 30 Evidence Chunks by Link Count",
            "",
            "| Chunk ID | Source Path | Link Count |",
            "|----------|-------------|------------|",
        ])
        chunk_link_count = Counter(l["evidence_chunk_id"] for l in self.evidence_links)
        for cid, count in chunk_link_count.most_common(30):
            sp = ""
            for l in self.evidence_links:
                if l["evidence_chunk_id"] == cid:
                    sp = l.get("source_path", "")[:50]
                    break
            lines.append(f"| {cid} | {sp} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## 9. Limitations",
            "",
            "- Strategy 3 (alias/name text matching) is not implemented in this stage to avoid noisy links.",
            "- Cross-language alias candidates (285) were not used for automatic evidence linking.",
            "- API evidence is absent due to missing API documentation in the source corpus.",
            "- Maximum evidence links per item is capped at 10.",
            "",
            "---",
            "",
            "## 10. Next Recommended Action",
            "",
            "Execute Stage 09: Neptune Export and Loader.",
            "- Generate load_neptune.cypher from filtered and linked graph data.",
            "- Support dry-run mode before actual Neptune writes.",
            "- Support layer selection (--layer business/implementation/evidence/all).",
            "",
        ])

        return "\n".join(lines)
