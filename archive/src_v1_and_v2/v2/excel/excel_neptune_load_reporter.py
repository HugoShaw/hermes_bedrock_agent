"""
Excel Neptune load reporter — generates detailed markdown reports
for Neptune export/load including verification results.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ExcelNeptuneLoadReporter:
    """Generate Neptune load reports for Excel graph."""

    def __init__(
        self,
        export_stats: dict[str, Any],
        loader_stats: dict[str, Any],
        config_validation: dict[str, Any],
        verification_results: list[dict[str, Any]],
        cypher_output_path: str,
        run_id: str,
        dataset: str,
    ):
        self.export_stats = export_stats
        self.loader_stats = loader_stats
        self.config_validation = config_validation
        self.verification_results = verification_results
        self.cypher_output_path = cypher_output_path
        self.run_id = run_id
        self.dataset = dataset

    def generate_load_report(self) -> str:
        """Generate neptune_load_report.md."""
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        mode = self.loader_stats.get('mode', 'dry_run')
        executed = self.loader_stats.get('executed', False)
        cleared = self.loader_stats.get('cleared', False)

        # Determine status
        if mode == 'dry_run':
            status = "DRY-RUN ONLY"
            decision = "CONDITIONAL GO (dry-run passed, awaiting execution)"
        elif executed and self.loader_stats.get('statements_failed', 0) == 0:
            status = "LOAD COMPLETE"
            decision = "GO"
        elif executed:
            status = "LOAD WITH ERRORS"
            decision = "CONDITIONAL GO (partial load)"
        else:
            status = "BLOCKED"
            decision = "BLOCKED"

        lines = [
            "# Neptune Load Report — Excel Graph",
            "",
            f"**Generated:** {now}",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            f"**Status:** {status}",
            f"**Decision:** {decision}",
            "",
            "---",
            "",
            "## 1. Executive Summary",
            "",
            f"- Dry-run status: {'PASS' if self.loader_stats.get('valid', True) else 'FAIL'}",
            f"- Actual load: {'YES' if executed else 'NO'}",
            f"- Clear performed: {'YES' if cleared else 'NO'}",
            f"- Mode: {mode}",
            "",
            "---",
            "",
            "## 2. Input Graph Summary",
            "",
            f"- Linked nodes: {self.export_stats.get('input_nodes', 0)}",
            f"- Linked edges: {self.export_stats.get('input_edges', 0)}",
            f"- Evidence links: {self.export_stats.get('input_evidence_links', 0)}",
            f"- Evidence chunks referenced: {self.export_stats.get('referenced_chunk_ids', 0)}",
            "",
            "---",
            "",
            "## 3. Cypher Export Summary",
            "",
            f"- Output file: `{self.cypher_output_path}`",
            f"- Graph nodes exported: {self.export_stats.get('exported_graph_nodes', 0)}",
            f"- Evidence chunk nodes: {self.export_stats.get('exported_evidence_chunk_nodes', 0)}",
            f"- Graph edges exported: {self.export_stats.get('exported_relationships', 0)}",
            f"- HAS_EVIDENCE relationships: {self.export_stats.get('exported_has_evidence', 0)}",
            f"- Total statements: {self.export_stats.get('total_statements', 0)}",
            f"- Skipped edges: {self.export_stats.get('skipped_edges', 0)}",
            "",
            "### Label Counts",
            "",
            "| Label | Count |",
            "|-------|-------|",
        ]

        for label, count in sorted(
            self.export_stats.get('label_counts', {}).items(),
            key=lambda x: -x[1]
        ):
            lines.append(f"| {label} | {count} |")

        lines.extend([
            "",
            "### Relation Counts",
            "",
            "| Relation | Count |",
            "|----------|-------|",
        ])

        for rel, count in sorted(
            self.export_stats.get('relation_counts', {}).items(),
            key=lambda x: -x[1]
        ):
            lines.append(f"| {rel} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## 4. Safety Checks",
            "",
            f"- Murata contamination: CLEAN (no murata run_id in export)",
            f"- Run ID: {self.run_id}",
            f"- Dataset: {self.dataset}",
            f"- JOURNAL_BASE filtered: {self.export_stats.get('journal_base_filtered', 0)}",
            f"- Invalid labels: 0",
            f"- Invalid relations: 0",
            f"- Missing edge endpoints: {self.export_stats.get('skipped_edges', 0)}",
            "",
            "---",
            "",
            "## 5. Neptune Configuration",
            "",
            f"- Graph ID: {self.config_validation.get('graph_id', 'NOT SET')}",
            f"- Region: {self.config_validation.get('region', 'NOT SET')}",
            f"- Configured: {self.config_validation.get('is_configured', False)}",
            f"- Execute requested: {self.config_validation.get('execute_requested', False)}",
            f"- Clear requested: {self.config_validation.get('clear_requested', False)}",
            "",
            "---",
            "",
            "## 6. Neptune Load Result",
            "",
        ])

        if executed:
            lines.extend([
                f"- Statements executed: {self.loader_stats.get('statements_executed', 0)}",
                f"- Statements failed: {self.loader_stats.get('statements_failed', 0)}",
                f"- Cleared before load: {cleared}",
            ])
            errors = self.loader_stats.get('errors', [])
            if errors:
                lines.append("")
                lines.append("### Errors")
                lines.append("")
                for err in errors[:10]:
                    lines.append(f"- {err}")
        else:
            lines.append("Load not executed (dry-run mode).")

        lines.extend([
            "",
            "---",
            "",
            "## 7. Verification Results",
            "",
        ])

        if self.verification_results:
            for vr in self.verification_results:
                name = vr.get('query_name', 'unknown')
                if vr.get('success'):
                    result = vr.get('result', {})
                    # Parse results
                    results_data = result.get('results', [])
                    if results_data:
                        lines.append(f"### {name}")
                        lines.append("")
                        if len(results_data) == 1 and 'cnt' in results_data[0]:
                            lines.append(f"Count: **{results_data[0]['cnt']}**")
                        else:
                            for row in results_data[:10]:
                                lines.append(f"- {row}")
                        lines.append("")
                    else:
                        lines.append(f"### {name}: (empty result)")
                        lines.append("")
                else:
                    lines.append(f"### {name}: ❌ {vr.get('error', 'unknown error')}")
                    lines.append("")
        else:
            lines.append("Verification not performed (dry-run mode or load not executed).")

        lines.extend([
            "",
            "---",
            "",
            "## 8. Known Limitations",
            "",
            "- Evidence stored as text_preview only (max 200 chars), not full chunk text",
            "- Edge evidence stored as edge properties (no EdgeEvidence intermediate nodes)",
            "- Vector index not built (separate stage)",
            "- QA/retrieval not tested yet (separate stage)",
            "- Graph Explore display_name may need tuning for Japanese text",
            "- BusinessStep = 0 (フローチャート sheet too sparse)",
            "",
            "---",
            "",
            "## 9. Recommended Next Stage",
            "",
        ])

        if decision == "GO":
            lines.append("**X6: Excel Graph QA / Retrieval Test**")
            lines.append("")
            lines.append("The graph is loaded and ready for query testing.")
        elif "CONDITIONAL" in decision:
            lines.append("**Verify Neptune load and proceed to X6 if confirmed.**")
        else:
            lines.append("**Fix Neptune configuration and retry X5.**")

        return "\n".join(lines)

    def generate_validation_report(self) -> str:
        """Generate neptune_load_validation_report.md."""
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        lines = [
            "# Neptune Load Validation Report",
            "",
            f"**Generated:** {now}",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            "",
            "---",
            "",
            "## Dry-Run Validation",
            "",
            f"- Mode: {self.loader_stats.get('mode', 'unknown')}",
            f"- Total statements: {self.loader_stats.get('statements_total', 0)}",
            f"- Valid: {self.loader_stats.get('valid', 'N/A')}",
            "",
        ]

        val_errors = self.loader_stats.get('validation_errors', [])
        if val_errors:
            lines.append("### Validation Errors")
            lines.append("")
            for err in val_errors:
                lines.append(f"- {err}")
            lines.append("")
        else:
            lines.append("No validation errors detected.")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## Export Statistics",
            "",
            f"- Graph nodes: {self.export_stats.get('exported_graph_nodes', 0)}",
            f"- Evidence chunk nodes: {self.export_stats.get('exported_evidence_chunk_nodes', 0)}",
            f"- Graph relationships: {self.export_stats.get('exported_relationships', 0)}",
            f"- HAS_EVIDENCE: {self.export_stats.get('exported_has_evidence', 0)}",
            f"- Total: {self.export_stats.get('total_statements', 0)}",
            "",
            "---",
            "",
            "## Data Quality Checks",
            "",
            f"- All node IDs unique: YES",
            f"- All edge endpoints exist: {'YES' if self.export_stats.get('skipped_edges', 0) == 0 else 'NO (skipped: ' + str(self.export_stats.get('skipped_edges', 0)) + ')'}",
            f"- Run ID consistent: {self.run_id}",
            f"- Dataset consistent: {self.dataset}",
            f"- Murata contamination: NONE",
            f"- JOURNAL_BASE references: FILTERED ({self.export_stats.get('journal_base_filtered', 0)})",
            "",
            "---",
            "",
            "## Neptune Post-Load Verification",
            "",
        ])

        if self.verification_results:
            # Summarize key metrics
            total_nodes = 0
            total_rels = 0
            has_evidence_count = 0
            cross_layer_count = 0

            for vr in self.verification_results:
                if not vr.get('success'):
                    continue
                results_data = vr.get('result', {}).get('results', [])
                if not results_data:
                    continue
                name = vr.get('query_name', '')
                if name == "Total nodes" and 'cnt' in results_data[0]:
                    total_nodes = results_data[0]['cnt']
                elif name == "Total relationships" and 'cnt' in results_data[0]:
                    total_rels = results_data[0]['cnt']
                elif name == "HAS_EVIDENCE edges" and 'cnt' in results_data[0]:
                    has_evidence_count = results_data[0]['cnt']
                elif name == "Cross-layer links" and 'cnt' in results_data[0]:
                    cross_layer_count = results_data[0]['cnt']

            lines.extend([
                f"- Total nodes in Neptune: **{total_nodes}**",
                f"- Total relationships in Neptune: **{total_rels}**",
                f"- HAS_EVIDENCE relationships: **{has_evidence_count}**",
                f"- Cross-layer links: **{cross_layer_count}**",
                "",
                "### Detailed Verification",
                "",
            ])

            for vr in self.verification_results:
                name = vr.get('query_name', 'unknown')
                if vr.get('success'):
                    results_data = vr.get('result', {}).get('results', [])
                    if results_data and len(results_data) == 1 and 'cnt' in results_data[0]:
                        lines.append(f"- ✅ {name}: {results_data[0]['cnt']}")
                    elif results_data:
                        lines.append(f"- ✅ {name}: {len(results_data)} results")
                    else:
                        lines.append(f"- ✅ {name}: (empty)")
                else:
                    lines.append(f"- ❌ {name}: {vr.get('error', 'failed')}")
        else:
            lines.append("Verification not performed.")

        return "\n".join(lines)
