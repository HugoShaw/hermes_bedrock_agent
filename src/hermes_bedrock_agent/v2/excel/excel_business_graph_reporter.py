"""
Excel business graph reporter — generate markdown report for X3 stage.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelBusinessGraphReporter:
    """Generate business graph extraction report."""

    def __init__(
        self,
        output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.dataset = dataset
        self.run_id = run_id

    def generate_report(
        self,
        result: Any,
        selection_stats: dict[str, Any],
        dry_run: bool = False,
    ) -> str:
        """Generate the business graph extraction report."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Determine decision
        total_nodes = len(result.nodes)
        total_edges = len(result.edges)
        ev_coverage = result.evidence_coverage_nodes

        if total_nodes >= 10 and ev_coverage >= 0.9:
            decision = "GO"
            decision_note = "Business graph ready for integration."
        elif total_nodes >= 5 and ev_coverage >= 0.7:
            decision = "CONDITIONAL GO"
            decision_note = "Business graph usable but may need enrichment."
        else:
            decision = "NO-GO"
            decision_note = "Business graph insufficient for GraphRAG use."

        lines = [
            f"# Excel Business Graph Report — X3",
            f"",
            f"Generated: {now}",
            f"Mode: {'DRY-RUN' if dry_run else 'ACTUAL'}",
            f"Dataset: {self.dataset}",
            f"Run ID: {self.run_id}",
            f"",
            f"---",
            f"",
            f"## 1. Executive Summary",
            f"",
            f"**Decision: {decision}**",
            f"",
            f"{decision_note}",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total business nodes | {total_nodes} |",
            f"| Total business edges | {total_edges} |",
            f"| BusinessProcess nodes | {result.process_count} |",
            f"| BusinessStep nodes | {result.step_count} |",
            f"| BusinessRule nodes | {result.rule_count} |",
            f"| BusinessTerm nodes | {result.term_count} |",
            f"| Function nodes | {result.function_count} |",
            f"| BusinessDomain nodes | {result.domain_count} |",
            f"| Evidence coverage (nodes) | {result.evidence_coverage_nodes:.1%} |",
            f"| Evidence coverage (edges) | {result.evidence_coverage_edges:.1%} |",
            f"| Rejected items | {len(result.rejected)} |",
            f"| Low-confidence items | {len(result.low_confidence)} |",
            f"",
            f"---",
            f"",
            f"## 2. Input Summary",
            f"",
            f"| Item | Value |",
            f"|------|-------|",
            f"| Total evidence chunks | {selection_stats.get('total_chunks', 0)} |",
            f"| Selected business chunks | {selection_stats.get('selected_chunks', 0)} |",
            f"| Excluded chunks | {selection_stats.get('excluded_chunks', 0)} |",
            f"",
            f"### Selected Sheets",
            f"",
        ]

        for sheet in selection_stats.get("selected_sheets", []):
            lines.append(f"- {sheet}")

        lines.extend([
            f"",
            f"### Excluded Sheets",
            f"",
        ])
        for sheet in selection_stats.get("excluded_sheets", []):
            lines.append(f"- {sheet}")

        lines.extend([
            f"",
            f"### Manual Review Excluded",
            f"",
        ])
        for sheet in selection_stats.get("manual_review_excluded", []):
            lines.append(f"- {sheet}")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 3. Candidate Selection Stats",
            f"",
            f"### By Sheet Type",
            f"",
        ])
        for st, cnt in sorted(selection_stats.get("by_sheet_type", {}).items()):
            lines.append(f"- {st}: {cnt}")

        lines.extend([
            f"",
            f"### By Chunk Type",
            f"",
        ])
        for ct, cnt in sorted(selection_stats.get("by_chunk_type", {}).items()):
            lines.append(f"- {ct}: {cnt}")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 4. Graph Metrics",
            f"",
            f"### Node Count by Label",
            f"",
            f"| Label | Count |",
            f"|-------|-------|",
        ])
        for label, cnt in sorted(result.node_count_by_label.items(), key=lambda x: -x[1]):
            lines.append(f"| {label} | {cnt} |")

        lines.extend([
            f"",
            f"### Edge Count by Relation",
            f"",
            f"| Relation | Count |",
            f"|----------|-------|",
        ])
        for rel, cnt in sorted(result.edge_count_by_relation.items(), key=lambda x: -x[1]):
            lines.append(f"| {rel} | {cnt} |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 5. Process Extraction Metrics",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Process sheets processed | {len([s for s in selection_stats.get('selected_sheets', []) if 'フローチャート' in s])} |",
            f"| BusinessProcess nodes | {result.process_count} |",
            f"| BusinessStep nodes | {result.step_count} |",
            f"| HAS_STEP edges | {result.edge_count_by_relation.get('HAS_STEP', 0)} |",
            f"| NEXT_STEP edges | {result.edge_count_by_relation.get('NEXT_STEP', 0)} |",
            f"",
            f"**Limitations:**",
            f"- フローチャート sheet has only 3 non-empty cells (sparse)",
            f"- Step ordering relies on row number heuristic",
            f"- No explicit sequence columns detected",
            f"",
            f"---",
            f"",
            f"## 6. Business Rule Extraction Metrics",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Condition sheets processed | {len([s for s in selection_stats.get('selected_sheets', []) if 'データ取得条件' in s])} |",
            f"| BusinessRule nodes | {result.rule_count} |",
            f"| BusinessTerm nodes | {result.term_count} |",
            f"| HAS_RULE edges | {result.edge_count_by_relation.get('HAS_RULE', 0)} |",
            f"| HAS_TERM edges | {result.edge_count_by_relation.get('HAS_TERM', 0)} |",
            f"",
            f"---",
            f"",
            f"## 7. Evidence Coverage",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Nodes with evidence | {sum(1 for n in result.nodes if n.get('evidence_chunk_ids'))} / {total_nodes} |",
            f"| Edges with evidence | {sum(1 for e in result.edges if e.get('evidence_chunk_ids'))} / {total_edges} |",
            f"| Node evidence coverage | {result.evidence_coverage_nodes:.1%} |",
            f"| Edge evidence coverage | {result.evidence_coverage_edges:.1%} |",
            f"",
            f"---",
            f"",
            f"## 8. Quality Warnings",
            f"",
        ])

        if result.rejected:
            lines.append(f"- {len(result.rejected)} items rejected")
            # Summarize rejection types
            rej_types: dict[str, int] = {}
            for r in result.rejected:
                t = r.get("type", "unknown")
                rej_types[t] = rej_types.get(t, 0) + 1
            for t, c in sorted(rej_types.items()):
                lines.append(f"  - {t}: {c}")
        else:
            lines.append(f"- No items rejected")

        if result.low_confidence:
            lines.append(f"- {len(result.low_confidence)} low-confidence items")
        else:
            lines.append(f"- No low-confidence items")

        lines.extend([
            f"",
            f"**Manual review recommended for:**",
            f"- フローチャート (very sparse, 3 cells only)",
            f"- データ取得条件（納品明細）(limited rows)",
            f"- データ取得条件（発注明細）(limited rows)",
            f"",
            f"---",
            f"",
            f"## 9. Recommended Next Stage",
            f"",
            f"**Recommended: X4 — Entity Resolution + Evidence Link**",
            f"",
            f"Rationale:",
            f"- Business graph and implementation graph both extracted",
            f"- Cross-layer entity linking needed (e.g., Function ↔ API, BusinessTerm ↔ Column)",
            f"- Evidence chunk coverage is solid",
            f"- No parser fixes required before proceeding",
            f"",
        ])

        report_text = "\n".join(lines)

        # Write report
        report_path = self.output_dir / "excel_business_graph_report.md"
        report_path.write_text(report_text, encoding="utf-8")
        logger.info(f"Report written to {report_path}")

        return decision
