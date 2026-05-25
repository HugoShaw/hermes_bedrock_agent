"""Comparison reporter - generates markdown reports and JSON artifacts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from flowchart_to_mermaid.compare.graph_diff import DiffResult, DiffItem
from flowchart_to_mermaid.compare.graph_normalizer import NormalizedGraph


class ComparisonReporter:
    """Generates comparison reports and saves artifacts."""

    def generate_report(
        self,
        actual_path: str,
        expected_path: str,
        diff_result: DiffResult,
        actual_normalized: NormalizedGraph,
        expected_normalized: NormalizedGraph,
    ) -> str:
        """Generate a markdown comparison report."""
        lines: list[str] = []

        # Header
        lines.append("# Mermaid Graph Comparison Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Actual:** `{actual_path}`")
        lines.append(f"**Expected:** `{expected_path}`")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"| Metric | Count |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Actual Nodes | {len(actual_normalized.nodes)} |")
        lines.append(f"| Expected Nodes | {len(expected_normalized.nodes)} |")
        lines.append(f"| Actual Edges | {len(actual_normalized.edges)} |")
        lines.append(f"| Expected Edges | {len(expected_normalized.edges)} |")
        lines.append(f"| Missing Nodes | {len(diff_result.missing_nodes)} |")
        lines.append(f"| Extra Nodes | {len(diff_result.extra_nodes)} |")
        lines.append(f"| Missing Edges | {len(diff_result.missing_edges)} |")
        lines.append(f"| Extra Edges | {len(diff_result.extra_edges)} |")
        lines.append(f"| Group Differences | {len(diff_result.group_diffs)} |")
        lines.append("")

        # Severity summary
        lines.append("### Severity Breakdown")
        lines.append("")
        lines.append(f"| Severity | Count |")
        lines.append(f"|----------|-------|")
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = diff_result.severity_counts.get(sev, 0)
            marker = " ⚠️" if count > 0 and sev in ("CRITICAL", "HIGH") else ""
            lines.append(f"| {sev} | {count}{marker} |")
        lines.append("")

        # Missing Critical Nodes
        critical_nodes = [
            d for d in diff_result.details
            if d.category == "missing_node" and d.severity == "CRITICAL"
        ]
        if critical_nodes:
            lines.append("## Missing Critical Nodes")
            lines.append("")
            for item in critical_nodes:
                lines.append(f"- **{item.expected_value}**")
            lines.append("")

        # Extra Suspicious Nodes
        if diff_result.extra_nodes:
            lines.append("## Extra Suspicious Nodes")
            lines.append("")
            lines.append("These nodes exist in actual but not in expected:")
            lines.append("")
            for node in diff_result.extra_nodes:
                lines.append(f"- `{node}`")
            lines.append("")

        # Missing Critical Edges
        critical_edges = [
            d for d in diff_result.details
            if d.category == "missing_edge" and d.severity in ("CRITICAL", "HIGH")
        ]
        if critical_edges:
            lines.append("## Missing Critical Edges")
            lines.append("")
            for item in critical_edges:
                lines.append(f"- [{item.severity}] `{item.expected_value}`")
            lines.append("")

        # Wrong Branches
        branch_items = [
            d for d in diff_result.details if d.category == "branch_missing"
        ]
        if branch_items:
            lines.append("## Wrong Branches")
            lines.append("")
            for item in branch_items:
                lines.append(f"- [{item.severity}] {item.description}")
            lines.append("")

        # Group Differences
        if diff_result.group_diffs:
            lines.append("## Group Differences")
            lines.append("")
            for gdiff in diff_result.group_diffs:
                lines.append(f"- {gdiff}")
            lines.append("")

        # API Coverage
        lines.append("## API Coverage")
        lines.append("")
        expected_apis = [
            n for n in expected_normalized.nodes if n.node_type == "api"
        ]
        actual_apis = [
            n for n in actual_normalized.nodes if n.node_type == "api"
        ]
        expected_api_labels = {n.label_normalized for n in expected_apis}
        actual_api_labels = {n.label_normalized for n in actual_apis}

        if expected_api_labels:
            covered = expected_api_labels & actual_api_labels
            missing = expected_api_labels - actual_api_labels
            coverage_pct = (len(covered) / len(expected_api_labels) * 100) if expected_api_labels else 100

            lines.append(f"**Coverage:** {len(covered)}/{len(expected_api_labels)} ({coverage_pct:.0f}%)")
            lines.append("")
            if missing:
                lines.append("**Missing APIs:**")
                for api in sorted(missing):
                    lines.append(f"- `{api}`")
                lines.append("")
        else:
            lines.append("No API nodes found in expected graph.")
            lines.append("")

        # Root Cause Hypothesis
        lines.append("## Root Cause Hypothesis")
        lines.append("")
        hypotheses = self._generate_hypotheses(diff_result, actual_normalized, expected_normalized)
        if hypotheses:
            for h in hypotheses:
                lines.append(f"- {h}")
        else:
            lines.append("- No significant differences detected.")
        lines.append("")

        # Fix Plan
        lines.append("## Fix Plan")
        lines.append("")
        fixes = self._generate_fix_plan(diff_result, actual_normalized, expected_normalized)
        if fixes:
            for idx, fix in enumerate(fixes, 1):
                lines.append(f"{idx}. {fix}")
        else:
            lines.append("No fixes needed - graphs match.")
        lines.append("")

        return "\n".join(lines)

    def save_all(
        self,
        output_dir: str,
        actual_path: str,
        expected_path: str,
        diff_result: DiffResult,
        actual_normalized: NormalizedGraph,
        expected_normalized: NormalizedGraph,
    ) -> dict[str, str]:
        """Save all comparison artifacts to output directory.

        Returns dict of artifact_name -> file_path.
        """
        os.makedirs(output_dir, exist_ok=True)
        saved_files: dict[str, str] = {}

        # Save actual normalized
        actual_norm_path = os.path.join(output_dir, "actual.normalized.json")
        with open(actual_norm_path, "w", encoding="utf-8") as f:
            json.dump(actual_normalized.to_dict(), f, ensure_ascii=False, indent=2)
        saved_files["actual_normalized"] = actual_norm_path

        # Save expected normalized
        expected_norm_path = os.path.join(output_dir, "expected.normalized.json")
        with open(expected_norm_path, "w", encoding="utf-8") as f:
            json.dump(expected_normalized.to_dict(), f, ensure_ascii=False, indent=2)
        saved_files["expected_normalized"] = expected_norm_path

        # Save diff
        diff_path = os.path.join(output_dir, "graph_diff.json")
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diff_result.to_dict(), f, ensure_ascii=False, indent=2)
        saved_files["graph_diff"] = diff_path

        # Generate and save report
        report = self.generate_report(
            actual_path, expected_path, diff_result,
            actual_normalized, expected_normalized
        )
        report_path = os.path.join(output_dir, "comparison_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        saved_files["comparison_report"] = report_path

        return saved_files

    def _generate_hypotheses(
        self,
        diff_result: DiffResult,
        actual: NormalizedGraph,
        expected: NormalizedGraph,
    ) -> list[str]:
        """Generate root cause hypotheses based on diff patterns."""
        hypotheses = []

        # Check if many nodes are missing -> possibly incomplete generation
        if len(diff_result.missing_nodes) > 5:
            hypotheses.append(
                f"Large number of missing nodes ({len(diff_result.missing_nodes)}) suggests "
                "the LLM generation may have been truncated or the prompt was insufficient."
            )

        # Check for missing branches
        branch_diffs = [d for d in diff_result.details if d.category == "branch_missing"]
        if branch_diffs:
            hypotheses.append(
                f"Missing {len(branch_diffs)} decision branches suggests the LLM "
                "did not fully expand conditional logic from the source flowchart."
            )

        # Check for group mismatches
        if diff_result.group_diffs:
            hypotheses.append(
                "Subgraph grouping differences suggest the LLM may have organized "
                "the flow differently from the expected structure."
            )

        # Check API coverage
        expected_apis = {n.label_normalized for n in expected.nodes if n.node_type == "api"}
        actual_apis = {n.label_normalized for n in actual.nodes if n.node_type == "api"}
        missing_apis = expected_apis - actual_apis
        if missing_apis:
            hypotheses.append(
                f"Missing {len(missing_apis)} API nodes indicates the LLM may not have "
                "identified all API calls in the source flowchart."
            )

        # Extra nodes could indicate hallucination
        if len(diff_result.extra_nodes) > 3:
            hypotheses.append(
                f"Presence of {len(diff_result.extra_nodes)} extra nodes not in expected "
                "may indicate LLM hallucination or over-interpretation of the flowchart."
            )

        return hypotheses

    def _generate_fix_plan(
        self,
        diff_result: DiffResult,
        actual: NormalizedGraph,
        expected: NormalizedGraph,
    ) -> list[str]:
        """Generate prioritized fix suggestions."""
        fixes = []

        # Critical items first
        critical_items = [d for d in diff_result.details if d.severity == "CRITICAL"]
        if critical_items:
            # Group by category
            missing_crit_nodes = [d for d in critical_items if d.category == "missing_node"]
            missing_crit_edges = [d for d in critical_items if d.category == "missing_edge"]
            missing_branches = [d for d in critical_items if d.category == "branch_missing"]

            if missing_crit_nodes:
                node_labels = [d.expected_value for d in missing_crit_nodes]
                fixes.append(
                    f"Add missing critical nodes: {', '.join(node_labels[:5])}"
                    + (f" (+{len(node_labels)-5} more)" if len(node_labels) > 5 else "")
                )

            if missing_branches:
                fixes.append(
                    f"Add missing decision branches: "
                    + ", ".join(d.expected_value for d in missing_branches[:3])
                )

            if missing_crit_edges:
                fixes.append(
                    f"Restore {len(missing_crit_edges)} critical edge connections"
                )

        # High items
        high_items = [d for d in diff_result.details if d.severity == "HIGH"]
        if high_items:
            group_issues = [d for d in high_items if d.category == "group_mismatch"]
            if group_issues:
                fixes.append(
                    f"Fix {len(group_issues)} subgraph grouping issues"
                )

            edge_issues = [d for d in high_items if d.category in ("missing_edge", "extra_edge")]
            if edge_issues:
                fixes.append(
                    f"Review {len(edge_issues)} edge connection differences"
                )

        # General recommendations
        if diff_result.extra_nodes:
            fixes.append(
                f"Review {len(diff_result.extra_nodes)} extra nodes for potential removal"
            )

        if not fixes:
            fixes.append("No significant fixes needed")

        return fixes
