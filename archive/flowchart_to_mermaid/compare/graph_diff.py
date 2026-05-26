"""Graph diff engine for comparing normalized Mermaid graphs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import Optional

from flowchart_to_mermaid.compare.graph_normalizer import NormalizedGraph, NormalizedNode, NormalizedEdge, NormalizedGroup


@dataclass
class DiffItem:
    """A single difference found between actual and expected graphs."""
    category: str  # missing_node, extra_node, missing_edge, extra_edge, group_mismatch, branch_missing
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    description: str
    expected_value: str = ""
    actual_value: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiffResult:
    """Complete diff result between two normalized graphs."""
    missing_nodes: list[str] = field(default_factory=list)
    extra_nodes: list[str] = field(default_factory=list)
    missing_edges: list[str] = field(default_factory=list)
    extra_edges: list[str] = field(default_factory=list)
    group_diffs: list[str] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=lambda: {
        "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0
    })
    details: list[DiffItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "missing_nodes": self.missing_nodes,
            "extra_nodes": self.extra_nodes,
            "missing_edges": self.missing_edges,
            "extra_edges": self.extra_edges,
            "group_diffs": self.group_diffs,
            "severity_counts": self.severity_counts,
            "details": [d.to_dict() for d in self.details],
        }


# Critical flow patterns
CRITICAL_NODE_PATTERNS = [
    r"開始", r"終了", r"条件[：:]", r"処理フラグ",
    r"GET[：:]", r"POST[：:]", r"PUT[：:]", r"DELETE[：:]",
    r"登録", r"変更", r"削除",
]

# Branch keywords that indicate critical decision branches
CRITICAL_BRANCH_KEYWORDS = ["登録", "変更", "削除", "新規", "更新"]


class GraphDiff:
    """Engine for diffing two normalized graphs."""

    FUZZY_THRESHOLD = 0.8

    def diff(self, actual: NormalizedGraph, expected: NormalizedGraph) -> DiffResult:
        """Compute differences between actual and expected graphs."""
        result = DiffResult()

        # Build label sets for matching
        actual_labels = {n.label_normalized for n in actual.nodes}
        expected_labels = {n.label_normalized for n in expected.nodes}

        # Node matching: exact first, then fuzzy
        matched_actual: set[str] = set()
        matched_expected: set[str] = set()

        # Exact matches
        exact_matches = actual_labels & expected_labels
        matched_actual.update(exact_matches)
        matched_expected.update(exact_matches)

        # Fuzzy matches for remaining
        unmatched_actual = actual_labels - matched_actual
        unmatched_expected = expected_labels - matched_expected

        fuzzy_map: dict[str, str] = {}  # actual_label -> expected_label
        for a_label in list(unmatched_actual):
            best_ratio = 0.0
            best_match = None
            for e_label in unmatched_expected:
                ratio = SequenceMatcher(None, a_label, e_label).ratio()
                if ratio > best_ratio and ratio >= self.FUZZY_THRESHOLD:
                    best_ratio = ratio
                    best_match = e_label
            if best_match:
                fuzzy_map[a_label] = best_match
                matched_actual.add(a_label)
                matched_expected.add(best_match)
                unmatched_expected.discard(best_match)

        # Missing nodes (in expected but not in actual)
        missing_labels = expected_labels - matched_expected
        for label in sorted(missing_labels):
            result.missing_nodes.append(label)
            severity = self._get_node_severity(label, expected)
            item = DiffItem(
                category="missing_node",
                severity=severity,
                description=f"Missing node: {label}",
                expected_value=label,
                actual_value="",
            )
            result.details.append(item)
            result.severity_counts[severity] += 1

        # Extra nodes (in actual but not in expected)
        extra_labels = actual_labels - matched_actual
        for label in sorted(extra_labels):
            result.extra_nodes.append(label)
            severity = "LOW"
            item = DiffItem(
                category="extra_node",
                severity=severity,
                description=f"Extra node not in expected: {label}",
                expected_value="",
                actual_value=label,
            )
            result.details.append(item)
            result.severity_counts[severity] += 1

        # Edge comparison
        # Build a normalized label map for fuzzy matched nodes
        label_map: dict[str, str] = {}  # maps actual label to expected label (or identity)
        for label in matched_actual:
            if label in fuzzy_map:
                label_map[label] = fuzzy_map[label]
            else:
                label_map[label] = label

        actual_edges = self._edge_set(actual, label_map)
        expected_edges = self._edge_set(expected, {})  # expected uses identity

        missing_edges = expected_edges - actual_edges
        extra_edges = actual_edges - expected_edges

        for edge_repr in sorted(missing_edges):
            result.missing_edges.append(edge_repr)
            severity = self._get_edge_severity(edge_repr)
            item = DiffItem(
                category="missing_edge",
                severity=severity,
                description=f"Missing edge: {edge_repr}",
                expected_value=edge_repr,
                actual_value="",
            )
            result.details.append(item)
            result.severity_counts[severity] += 1

        for edge_repr in sorted(extra_edges):
            result.extra_edges.append(edge_repr)
            severity = "LOW"
            item = DiffItem(
                category="extra_edge",
                severity=severity,
                description=f"Extra edge not in expected: {edge_repr}",
                expected_value="",
                actual_value=edge_repr,
            )
            result.details.append(item)
            result.severity_counts[severity] += 1

        # Group comparison
        self._compare_groups(actual, expected, result)

        # Check for missing branches
        self._check_missing_branches(actual, expected, result)

        return result

    def _edge_set(self, graph: NormalizedGraph, label_map: dict[str, str]) -> set[str]:
        """Create a set of edge representations for comparison."""
        edges = set()
        for edge in graph.edges:
            src = label_map.get(edge.source_label_normalized, edge.source_label_normalized)
            tgt = label_map.get(edge.target_label_normalized, edge.target_label_normalized)
            label_part = f" |{edge.edge_label_normalized}|" if edge.edge_label_normalized else ""
            edges.add(f"{src} -->{label_part} {tgt}")
        return edges

    def _get_node_severity(self, label: str, graph: NormalizedGraph) -> str:
        """Determine severity of a missing node."""
        for pattern in CRITICAL_NODE_PATTERNS:
            if re.search(pattern, label):
                return "CRITICAL"

        # Check if the node is a decision node
        for node in graph.nodes:
            if node.label_normalized == label and node.node_type == "decision":
                return "CRITICAL"

        # API nodes are HIGH
        for node in graph.nodes:
            if node.label_normalized == label and node.node_type == "api":
                return "HIGH"

        return "MEDIUM"

    def _get_edge_severity(self, edge_repr: str) -> str:
        """Determine severity of a missing edge."""
        # Critical if it connects to critical nodes
        for pattern in CRITICAL_NODE_PATTERNS:
            if re.search(pattern, edge_repr):
                return "CRITICAL"

        # Check for branch keywords in edge labels
        for keyword in CRITICAL_BRANCH_KEYWORDS:
            if keyword in edge_repr:
                return "CRITICAL"

        return "HIGH"

    def _compare_groups(
        self, actual: NormalizedGraph, expected: NormalizedGraph, result: DiffResult
    ) -> None:
        """Compare subgraph groupings."""
        actual_groups = {g.label_normalized: set(g.node_labels) for g in actual.groups}
        expected_groups = {g.label_normalized: set(g.node_labels) for g in expected.groups}

        # Missing groups
        for group_label in expected_groups:
            if group_label not in actual_groups:
                desc = f"Missing group: {group_label}"
                result.group_diffs.append(desc)
                item = DiffItem(
                    category="group_mismatch",
                    severity="HIGH",
                    description=desc,
                    expected_value=group_label,
                    actual_value="",
                )
                result.details.append(item)
                result.severity_counts["HIGH"] += 1
            else:
                # Compare node membership
                expected_nodes = expected_groups[group_label]
                actual_nodes = actual_groups[group_label]
                missing_in_group = expected_nodes - actual_nodes
                extra_in_group = actual_nodes - expected_nodes

                if missing_in_group or extra_in_group:
                    desc = (
                        f"Group '{group_label}' membership differs: "
                        f"missing={sorted(missing_in_group)}, extra={sorted(extra_in_group)}"
                    )
                    result.group_diffs.append(desc)
                    item = DiffItem(
                        category="group_mismatch",
                        severity="HIGH",
                        description=desc,
                        expected_value=str(sorted(expected_nodes)),
                        actual_value=str(sorted(actual_nodes)),
                    )
                    result.details.append(item)
                    result.severity_counts["HIGH"] += 1

    def _check_missing_branches(
        self, actual: NormalizedGraph, expected: NormalizedGraph, result: DiffResult
    ) -> None:
        """Check for missing decision branches (登録/変更/削除 etc)."""
        # Find decision nodes in expected
        expected_decisions = [
            n for n in expected.nodes if n.node_type == "decision"
        ]

        for decision in expected_decisions:
            # Find edges from this decision in expected
            expected_branches = [
                e for e in expected.edges
                if e.source_label_normalized == decision.label_normalized
                and e.edge_label_normalized
            ]

            # Find matching edges in actual
            actual_branches = [
                e for e in actual.edges
                if e.source_label_normalized == decision.label_normalized
                and e.edge_label_normalized
            ]

            expected_branch_labels = {e.edge_label_normalized for e in expected_branches}
            actual_branch_labels = {e.edge_label_normalized for e in actual_branches}

            missing_branches = expected_branch_labels - actual_branch_labels
            for branch in sorted(missing_branches):
                # Check if this is a critical branch
                is_critical = any(kw in branch for kw in CRITICAL_BRANCH_KEYWORDS)
                severity = "CRITICAL" if is_critical else "HIGH"
                desc = f"Missing branch '{branch}' from decision '{decision.label_normalized}'"
                item = DiffItem(
                    category="branch_missing",
                    severity=severity,
                    description=desc,
                    expected_value=branch,
                    actual_value="",
                )
                result.details.append(item)
                result.severity_counts[severity] += 1
