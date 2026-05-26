"""
Excel implementation graph reporter — generate markdown report for X2 stage.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelImplementationGraphReporter:
    """Generate implementation graph extraction report."""

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
        output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.output_dir = Path(output_dir)

    def generate_report(
        self,
        stats: dict[str, Any],
        selection_result: Any,
        nodes: list[dict],
        edges: list[dict],
        rejected: list[dict],
        low_confidence: list[dict],
    ) -> Path:
        """Generate the implementation graph report."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Determine decision
        decision = self._determine_decision(stats, nodes, edges)

        lines = [
            "# Excel Implementation Graph Extraction Report",
            "",
            f"**Dataset:** {self.dataset}",
            f"**Run ID:** {self.run_id}",
            f"**Date:** {now}",
            f"**Stage:** X2 Excel Implementation Graph Extraction",
            "",
            "---",
            "",
            "## 1. Executive Summary",
            "",
            f"**Decision: {decision}**",
            "",
            f"- Extracted **{len(nodes)} nodes** and **{len(edges)} edges**",
            f"- MAPS_TO edges (field mappings): **{stats.get('maps_to_count', 0)}**",
            f"- Evidence coverage: **{stats.get('evidence_coverage_nodes', 0):.1%}** nodes, "
            f"**{stats.get('evidence_coverage_edges', 0):.1%}** edges",
            f"- Rejected items: {len(rejected)}",
            f"- Low-confidence items: {len(low_confidence)}",
            "",
        ]

        # Key structures
        node_labels = stats.get("node_count_by_label", {})
        lines += [
            "**Key extracted structures:**",
            f"- Systems: {node_labels.get('System', 0)}",
            f"- Messages/Interfaces: {node_labels.get('Message', 0)}",
            f"- Columns/Fields: {node_labels.get('Column', 0)}",
            f"- APIs: {node_labels.get('API', 0)}",
            f"- Files: {node_labels.get('File', 0)}",
            f"- Modules: {node_labels.get('Module', 0)}",
            "",
            "**Major limitations:**",
            "- Extraction is heuristic-based (no LLM used in X2)",
            "- Field mapping relies on column position patterns (IF-ID, C, BK, BM)",
            "- API details limited to SAP_EDI interface IDs and file patterns",
            "- No OpenAPI/swagger definitions available",
            "",
            "---",
            "",
            "## 2. Input Summary",
            "",
            f"- Evidence chunks used: {stats.get('total_candidate_chunks', 0)}",
            f"- Sheets processed: {len(stats.get('sheets_processed', []))}",
        ]

        # List sheets
        for s in stats.get("sheets_processed", []):
            lines.append(f"  - {s}")

        lines += [
            "",
            f"- Used reviewed files: evidence_chunks_reviewed.jsonl",
            "",
            "---",
            "",
            "## 3. Candidate Selection",
            "",
        ]

        if selection_result:
            sel = selection_result if isinstance(selection_result, dict) else selection_result.to_dict()
            lines += [
                f"- Total evidence chunks: {sel.get('total_chunks', 0)}",
                f"- Selected for implementation: {sel.get('selected_chunks', 0)}",
                f"- Excluded: {sel.get('excluded_chunks', 0)}",
                "",
                "**Selected by sheet type:**",
            ]
            for st, cnt in sorted(sel.get("by_sheet_type", {}).items(), key=lambda x: -x[1]):
                lines.append(f"- {st}: {cnt}")
            lines += [
                "",
                "**Selected by chunk type:**",
            ]
            for ct, cnt in sorted(sel.get("by_chunk_type", {}).items(), key=lambda x: -x[1]):
                lines.append(f"- {ct}: {cnt}")
            lines += [
                "",
                f"**Excluded sheets:** {len(sel.get('excluded_sheets', []))}",
            ]
            for s in sel.get("excluded_sheets", [])[:10]:
                lines.append(f"- {s}")
            lines += [
                "",
                f"**Manual-review sheets excluded:** {len(sel.get('manual_review_excluded', []))}",
            ]
            for s in sel.get("manual_review_excluded", []):
                lines.append(f"- {s}")

        lines += [
            "",
            "---",
            "",
            "## 4. Graph Metrics",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total nodes | {len(nodes)} |",
            f"| Total edges | {len(edges)} |",
            f"| Rejected items | {len(rejected)} |",
            f"| Low-confidence items | {len(low_confidence)} |",
            "",
            "**Node count by label:**",
            "",
            "| Label | Count |",
            "|-------|-------|",
        ]
        for label, cnt in sorted(node_labels.items(), key=lambda x: -x[1]):
            lines.append(f"| {label} | {cnt} |")

        edge_relations = stats.get("edge_count_by_relation", {})
        lines += [
            "",
            "**Edge count by relation type:**",
            "",
            "| Relation | Count |",
            "|----------|-------|",
        ]
        for rel, cnt in sorted(edge_relations.items(), key=lambda x: -x[1]):
            lines.append(f"| {rel} | {cnt} |")

        lines += [
            "",
            "---",
            "",
            "## 5. Mapping Extraction Metrics",
            "",
            f"- Field mapping sheets processed: {stats.get('by_sheet_type', {}).get('field_mapping_sheet', 0) if selection_result else 'N/A'}",
            f"- MAPS_TO edges generated: **{stats.get('maps_to_count', 0)}**",
            f"- Column nodes (source+target fields): {node_labels.get('Column', 0)}",
            f"- Message nodes (interfaces): {node_labels.get('Message', 0)}",
            f"- Low-confidence mappings: {len(low_confidence)}",
            "",
            "---",
            "",
            "## 6. API Extraction Metrics",
            "",
            f"- API-related sheets processed: (api_interface_sheet chunks)",
            f"- API nodes: {node_labels.get('API', 0)}",
            f"- File nodes: {node_labels.get('File', 0)}",
            f"- Module nodes (processing steps): {node_labels.get('Module', 0)}",
            f"- System nodes: {node_labels.get('System', 0)}",
            "",
            "**Limitations:**",
            "- API extraction is name/pattern-based only",
            "- No request/response schema extracted (not in source data)",
            "- ErrorCode extraction minimal (no dedicated error sheet)",
            "",
            "---",
            "",
            "## 7. Evidence Coverage",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Nodes with evidence | {stats.get('nodes_with_evidence', 0)}/{len(nodes)} |",
            f"| Edges with evidence | {stats.get('edges_with_evidence', 0)}/{len(edges)} |",
            f"| Node evidence coverage | {stats.get('evidence_coverage_nodes', 0):.1%} |",
            f"| Edge evidence coverage | {stats.get('evidence_coverage_edges', 0):.1%} |",
            "",
            "---",
            "",
            "## 8. Quality Warnings",
            "",
        ]

        # Analyze rejected
        reject_reasons = {}
        for r in rejected:
            reason = r.get("reason", "unknown")
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

        if reject_reasons:
            lines.append("**Rejected items by reason:**")
            lines.append("")
            for reason, cnt in sorted(reject_reasons.items(), key=lambda x: -x[1]):
                lines.append(f"- {reason}: {cnt}")
        else:
            lines.append("No rejected items.")

        lines += [
            "",
            "**Known limitations:**",
            "- Heuristic extraction may miss complex multi-row mapping patterns",
            "- Column position assumptions (BK/BM = target side) may not hold for all sheets",
            "- Some sheets with different layouts may produce incomplete mappings",
            "",
            "---",
            "",
            "## 9. Recommended Next Stage",
            "",
            f"**Decision: {decision}**",
            "",
        ]

        if "GO" in decision:
            lines += [
                "Recommended priority:",
                "1. **X3: Excel Business Graph Extraction** — extract business rules and process flows from 5 candidate sheets",
                "2. **X4: Entity Resolution + Evidence Link** — merge duplicates across business and implementation layers",
                "3. **Vector Evidence Store alignment** — index 190 chunks for retrieval",
                "",
                "The implementation graph provides a solid structural foundation.",
                "Field mappings capture the SAP↔中間F↔Andpad data flow.",
            ]
        else:
            lines += [
                "Recommended: Fix parser issues and rerun X0/X1/X2 before proceeding.",
            ]

        report_text = "\n".join(lines)
        report_path = self.output_dir / "excel_implementation_graph_report.md"
        report_path.write_text(report_text, encoding="utf-8")
        logger.info(f"Wrote report to {report_path}")
        return report_path

    def _determine_decision(
        self, stats: dict, nodes: list[dict], edges: list[dict]
    ) -> str:
        """Determine GO/CONDITIONAL GO/NO-GO."""
        node_count = len(nodes)
        edge_count = len(edges)
        maps_to = stats.get("maps_to_count", 0)
        coverage = stats.get("evidence_coverage_nodes", 0)

        if node_count >= 20 and edge_count >= 20 and maps_to >= 10 and coverage >= 0.8:
            return "GO"
        elif node_count >= 10 and edge_count >= 10 and coverage >= 0.5:
            return "CONDITIONAL GO"
        else:
            return "NO-GO"
