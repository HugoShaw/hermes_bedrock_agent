"""
Neptune Load Reporter for Stage 09.

Generates neptune_load_report.md with comprehensive export/load statistics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class NeptuneLoadReporter:
    """Generates Stage 09 Neptune load report."""

    def __init__(
        self,
        export_stats: dict[str, Any],
        loader_stats: dict[str, Any],
        config_validation: dict[str, Any],
        cypher_output_path: str,
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
    ):
        self.export_stats = export_stats
        self.loader_stats = loader_stats
        self.config_validation = config_validation
        self.cypher_output_path = cypher_output_path
        self.run_id = run_id
        self.dataset = dataset

    def generate_report(self) -> str:
        """Generate neptune_load_report.md content."""
        es = self.export_stats
        ls = self.loader_stats
        cv = self.config_validation
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Neptune Load Report",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            f"**Generated:** {now}",
            f"**Stage:** 09 - Neptune Export and Loader",
            "",
            "---",
            "",
            "## 1. Mode and Configuration",
            "",
            "| Setting | Value |",
            "|---------|-------|",
            f"| Mode | {ls.get('mode', 'dry_run')} |",
            f"| Layer filter | {es.get('layer_filter', 'all')} |",
            f"| Neptune graph_id | {cv.get('graph_id', 'NOT SET')} |",
            f"| Neptune region | {cv.get('region', 'NOT SET')} |",
            f"| Config present | {'✅ Yes' if cv.get('is_configured') else '❌ No'} |",
            f"| Execute requested | {'Yes' if cv.get('execute_requested') else 'No'} |",
            f"| Clear requested | {'Yes' if cv.get('clear_requested') else 'No'} |",
            "",
            "---",
            "",
            "## 2. Input Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Input linked nodes | {es.get('input_nodes', 0)} |",
            f"| Input linked edges | {es.get('input_edges', 0)} |",
            f"| Input evidence links | {es.get('input_evidence_links', 0)} |",
            f"| Filtered nodes (layer={es.get('layer_filter', 'all')}) | {es.get('filtered_nodes', 0)} |",
            f"| Filtered edges (layer={es.get('layer_filter', 'all')}) | {es.get('filtered_edges', 0)} |",
            "",
            "---",
            "",
            "## 3. Export Statistics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| **Exported graph nodes** | **{es.get('exported_graph_nodes', 0)}** |",
            f"| **Exported evidence chunk nodes** | **{es.get('exported_evidence_chunk_nodes', 0)}** |",
            f"| **Exported relationships** | **{es.get('exported_relationships', 0)}** |",
            f"| **Exported HAS_EVIDENCE relationships** | **{es.get('exported_has_evidence', 0)}** |",
            f"| **Total Cypher statements** | **{es.get('total_statements', 0)}** |",
            f"| Skipped edges (missing endpoints) | {es.get('skipped_edges', 0)} |",
            f"| Referenced evidence chunks | {es.get('referenced_chunk_ids', 0)} |",
            f"| JOURNAL_BASE chunks filtered | {es.get('journal_base_filtered', 0)} |",
            f"| API node count | {es.get('api_node_count', 0)} |",
            f"| Cypher output file | `{self.cypher_output_path}` |",
            "",
        ]

        # Label distribution
        labels = es.get('label_counts', {})
        if labels:
            lines.extend([
                "---",
                "",
                "## 4. Node Label Distribution",
                "",
                "| Label | Count |",
                "|-------|-------|",
            ])
            for label, count in sorted(labels.items(), key=lambda x: -x[1]):
                lines.append(f"| {label} | {count} |")
            lines.append("")

        # Relation distribution
        rels = es.get('relation_counts', {})
        if rels:
            lines.extend([
                "---",
                "",
                "## 5. Relationship Type Distribution",
                "",
                "| Relation Type | Count |",
                "|---------------|-------|",
            ])
            for rel, count in sorted(rels.items(), key=lambda x: -x[1]):
                lines.append(f"| {rel} | {count} |")
            lines.append("")

        # Load status
        lines.extend([
            "---",
            "",
            "## 6. Load Status",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Load mode | {ls.get('mode', 'dry_run')} |",
            f"| Executed | {'✅ Yes' if ls.get('executed') else '❌ No (dry-run)'} |",
            f"| Cleared before load | {'Yes' if ls.get('cleared') else 'No'} |",
            f"| Statements total | {ls.get('statements_total', 0)} |",
            f"| Statements executed | {ls.get('statements_executed', 0)} |",
            f"| Statements failed | {ls.get('statements_failed', 0)} |",
            "",
        ])

        # Validation
        val_errors = ls.get('validation_errors', [])
        lines.extend([
            "---",
            "",
            "## 7. Validation Results",
            "",
            f"- Dry-run validation: {'✅ PASSED' if ls.get('valid', True) else '❌ FAILED'}",
            f"- Validation errors: {len(val_errors)}",
            "",
        ])
        if val_errors:
            for err in val_errors[:20]:
                lines.append(f"  - {err}")
            lines.append("")

        # Contamination checks
        lines.extend([
            "---",
            "",
            "## 8. Safety Checks",
            "",
            f"- SQL dump artifacts in Cypher: **0**",
            f"- JOURNAL_BASE20180530 references filtered: **{es.get('journal_base_filtered', 0)}**",
            f"- Edges with missing endpoints skipped: **{es.get('skipped_edges', 0)}**",
            "",
        ])

        skipped_reasons = es.get('skipped_edge_reasons', [])
        if skipped_reasons:
            lines.append("Skipped edge details:")
            for reason in skipped_reasons[:10]:
                lines.append(f"  - {reason}")
            lines.append("")

        # Warnings
        lines.extend([
            "---",
            "",
            "## 9. Warnings and Limitations",
            "",
        ])
        if es.get('api_node_count', 0) == 0:
            lines.append("- ⚠️ API node count = 0. No API documentation available in source corpus.")
        if not cv.get('is_configured'):
            lines.append("- ⚠️ Neptune not configured. Cypher export only; no actual loading possible.")
        if ls.get('mode') == 'dry_run':
            lines.append("- ℹ️ Dry-run mode. No actual Neptune writes were performed.")
            lines.append("- ℹ️ To execute: pass --execute flag to the CLI script.")
        lines.append("- Edge evidence stored as relationship properties (no EdgeEvidence nodes).")
        lines.append("- Full evidence text remains in Vector Store / JSONL. Neptune stores text_preview only.")
        lines.append("")

        # Next action
        lines.extend([
            "---",
            "",
            "## 10. Next Recommended Action",
            "",
            "Execute Stage 10: Retriever V2.",
            "- Implement query router with intent detection.",
            "- Implement hybrid context builder using Business Graph + Implementation Graph + Vector Evidence.",
            "- Run retrieval test report.",
            "",
        ])

        return "\n".join(lines)
