"""Graph validator: check quality of the flow graph."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowNode, NodeType, PageFlow,
)

logger = logging.getLogger(__name__)


class GraphValidator:
    """Validate the flow graph for completeness and correctness."""

    # Known important texts that should be found
    EXPECTED_FUNCTION_NUMBERS = [
        "機能No1", "機能No2", "機能No3", "機能No4", "機能No5",
        "機能No6", "機能No7", "機能No8", "機能No9", "機能No10",
        "機能No11", "機能No12", "機能No13", "機能No14", "機能No15",
        "機能No16", "機能No17", "機能No18", "機能No19", "機能No20",
        "機能No24", "機能No25", "機能No26", "機能No27", "機能No28",
    ]

    EXPECTED_APIS = [
        "GET", "POST", "PUT", "DELETE",
    ]

    def validate(self, doc: FlowDocument) -> dict:
        """Run all validation checks.

        Returns a dict with validation results.
        """
        results = {
            "total_text_blocks": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "total_groups": 0,
            "start_nodes": 0,
            "end_nodes": 0,
            "orphan_nodes": 0,
            "duplicate_node_ids": [],
            "invalid_edges": [],
            "uncertain_edges": 0,
            "inferred_edges": 0,
            "function_coverage": {},
            "api_coverage": {},
            "issues": [],
            "warnings": [],
        }

        for page in doc.pages:
            results["total_text_blocks"] += len(page.text_blocks)
            results["total_nodes"] += len(page.nodes)
            results["total_edges"] += len(page.edges)
            results["total_groups"] += len(page.groups)

            # Check for start/end nodes
            for node in page.nodes:
                if node.type == NodeType.TERMINATOR:
                    if any(kw in node.label for kw in ["開始", "Start"]):
                        results["start_nodes"] += 1
                    if any(kw in node.label for kw in ["終了", "End"]):
                        results["end_nodes"] += 1

            # Check for duplicate node IDs
            node_ids = [n.id for n in page.nodes]
            seen = set()
            for nid in node_ids:
                if nid in seen:
                    results["duplicate_node_ids"].append(nid)
                seen.add(nid)

            # Check edges reference valid nodes
            for edge in page.edges:
                if edge.source not in seen:
                    results["invalid_edges"].append(
                        f"Edge {edge.id}: source {edge.source} not found"
                    )
                if edge.target not in seen:
                    results["invalid_edges"].append(
                        f"Edge {edge.id}: target {edge.target} not found"
                    )
                if edge.uncertain:
                    results["uncertain_edges"] += 1
                if edge.inferred:
                    results["inferred_edges"] += 1

            # Check for orphan nodes (no incoming or outgoing edges)
            connected = set()
            for edge in page.edges:
                connected.add(edge.source)
                connected.add(edge.target)
            for node in page.nodes:
                if node.id not in connected:
                    results["orphan_nodes"] += 1

            # Function number coverage
            all_text = " ".join(n.label for n in page.nodes)
            for fn in self.EXPECTED_FUNCTION_NUMBERS:
                results["function_coverage"][fn] = fn in all_text

            # API coverage
            for api in self.EXPECTED_APIS:
                results["api_coverage"][api] = f"{api}：" in all_text or f"{api}:" in all_text

        # Generate issues/warnings
        if results["start_nodes"] == 0:
            results["issues"].append("No start node found")
        if results["end_nodes"] == 0:
            results["issues"].append("No end node found")
        if results["start_nodes"] > 1:
            results["warnings"].append(f"Multiple start nodes: {results['start_nodes']}")
        if results["end_nodes"] > 1:
            results["warnings"].append(f"Multiple end nodes: {results['end_nodes']}")
        if results["duplicate_node_ids"]:
            results["issues"].append(f"Duplicate node IDs: {results['duplicate_node_ids']}")
        if results["invalid_edges"]:
            results["issues"].append(f"Invalid edges: {len(results['invalid_edges'])}")
        if results["orphan_nodes"] > 0:
            results["warnings"].append(f"Orphan nodes: {results['orphan_nodes']}")

        # Coverage stats
        fn_found = sum(1 for v in results["function_coverage"].values() if v)
        fn_total = len(self.EXPECTED_FUNCTION_NUMBERS)
        results["function_coverage_ratio"] = fn_found / fn_total if fn_total > 0 else 0

        api_found = sum(1 for v in results["api_coverage"].values() if v)
        api_total = len(self.EXPECTED_APIS)
        results["api_coverage_ratio"] = api_found / api_total if api_total > 0 else 0

        return results
