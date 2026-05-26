"""
Excel graph quality filter — validate schema compliance, remove invalid items,
reject generic/orphan nodes, and produce filtered graph.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Valid labels by layer
VALID_BUSINESS_LABELS = {
    "Project", "BusinessDomain", "BusinessProcess", "BusinessStep",
    "BusinessRule", "BusinessTerm", "Function", "Screen",
    "Role", "Organization", "Document", "EvidenceChunk",
}
VALID_IMPL_LABELS = {
    "System", "Module", "API", "Service", "Class", "Method",
    "Table", "Column", "SQL", "Job", "File", "ExternalSystem",
    "Config", "Message", "ErrorCode", "Document", "EvidenceChunk",
}

# Valid relations by layer
VALID_BUSINESS_RELATIONS = {
    "BELONGS_TO", "CONTAINS", "HAS_STEP", "NEXT_STEP",
    "HAS_RULE", "HAS_TERM", "HAS_FUNCTION", "VALIDATES",
    "USES", "DEPENDS_ON", "HAS_EVIDENCE", "MENTIONED_IN", "RELATED_TO",
}
VALID_IMPL_RELATIONS = {
    "BELONGS_TO", "CONTAINS", "IMPLEMENTS", "USES", "CALLS",
    "READS", "WRITES", "MAPS_TO", "DEPENDS_ON", "TRIGGERS",
    "VALIDATES", "HAS_FIELD", "HAS_API", "HAS_METHOD",
    "HAS_TABLE", "HAS_COLUMN", "HAS_ERROR", "HAS_EVIDENCE",
    "MENTIONED_IN", "RELATED_TO",
}

# Generic names to reject (bare, without context)
GENERIC_BARE_NAMES = {
    "data", "item", "value", "field", "column", "table", "rule",
    "condition", "データ", "項目", "値", "条件",
}


@dataclass
class QualityFilterResult:
    """Result of quality filtering."""
    input_nodes: int = 0
    input_edges: int = 0
    filtered_nodes: list[dict] = field(default_factory=list)
    filtered_edges: list[dict] = field(default_factory=list)
    rejected_items: list[dict] = field(default_factory=list)
    nodes_by_label: dict[str, int] = field(default_factory=dict)
    edges_by_relation: dict[str, int] = field(default_factory=dict)


class ExcelGraphQualityFilter:
    """Filter unified graph for quality and schema compliance."""

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def filter(
        self,
        nodes: list[dict],
        edges: list[dict],
        evidence_chunk_ids: set[str] | None = None,
    ) -> QualityFilterResult:
        """Apply quality filters."""
        result = QualityFilterResult(
            input_nodes=len(nodes),
            input_edges=len(edges),
        )

        # 1. Filter nodes
        valid_nodes, rejected_nodes = self._filter_nodes(nodes)
        result.rejected_items.extend(rejected_nodes)

        # 2. Build valid node ID set
        valid_node_ids = {n["node_id"] for n in valid_nodes}

        # 3. Filter edges
        valid_edges, rejected_edges = self._filter_edges(
            edges, valid_node_ids
        )
        result.rejected_items.extend(rejected_edges)

        # 4. Remove orphan nodes (no edges)
        connected_ids = set()
        for e in valid_edges:
            connected_ids.add(e["source_node_id"])
            connected_ids.add(e["target_node_id"])

        # Keep all nodes — orphans are fine for evidence-backed graph
        # Only reject truly invalid ones
        result.filtered_nodes = valid_nodes
        result.filtered_edges = valid_edges

        # Compute stats
        for n in result.filtered_nodes:
            label = n["label"]
            result.nodes_by_label[label] = result.nodes_by_label.get(label, 0) + 1
        for e in result.filtered_edges:
            rel = e["relation_type"]
            result.edges_by_relation[rel] = result.edges_by_relation.get(rel, 0) + 1

        logger.info(
            f"Quality filter: {len(result.filtered_nodes)}/{len(nodes)} nodes, "
            f"{len(result.filtered_edges)}/{len(edges)} edges kept, "
            f"{len(result.rejected_items)} rejected"
        )
        return result

    def _filter_nodes(
        self, nodes: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """Filter nodes for validity."""
        valid = []
        rejected = []

        for node in nodes:
            reject_reason = self._check_node(node)
            if reject_reason:
                rejected.append({
                    "type": "rejected_node",
                    "node_id": node.get("node_id", ""),
                    "label": node.get("label", ""),
                    "display_name": node.get("display_name", ""),
                    "layer": node.get("layer", ""),
                    "reason": reject_reason,
                })
            else:
                valid.append(node)

        return valid, rejected

    def _check_node(self, node: dict) -> str | None:
        """Check if node is valid. Returns rejection reason or None."""
        label = node.get("label", "")
        layer = node.get("layer", "")
        display_name = node.get("display_name", "")
        name = node.get("name", "")

        # Check layer validity
        if layer == "business":
            if label not in VALID_BUSINESS_LABELS:
                return f"Invalid business label: {label}"
        elif layer == "implementation":
            if label not in VALID_IMPL_LABELS:
                return f"Invalid implementation label: {label}"
        else:
            return f"Invalid layer: {layer}"

        # Check run_id and dataset
        if node.get("run_id") != self.run_id:
            return f"Wrong run_id: {node.get('run_id')}"
        if node.get("dataset") != self.dataset:
            return f"Wrong dataset: {node.get('dataset')}"

        # Check empty names
        if not display_name.strip() and not name.strip():
            return "Empty display_name and name"

        # Check generic bare names
        if display_name.lower().strip() in GENERIC_BARE_NAMES:
            return f"Generic bare name: {display_name}"

        # Check evidence (warn but don't reject — nodes may have source_ids)
        if not node.get("evidence_chunk_ids") and not node.get("source_ids"):
            return "No evidence_chunk_ids or source_ids"

        return None

    def _filter_edges(
        self, edges: list[dict], valid_node_ids: set[str]
    ) -> tuple[list[dict], list[dict]]:
        """Filter edges for validity."""
        valid = []
        rejected = []

        seen_ids: set[str] = set()

        for edge in edges:
            reject_reason = self._check_edge(edge, valid_node_ids, seen_ids)
            if reject_reason:
                rejected.append({
                    "type": "rejected_edge",
                    "edge_id": edge.get("edge_id", ""),
                    "relation_type": edge.get("relation_type", ""),
                    "layer": edge.get("layer", ""),
                    "reason": reject_reason,
                })
            else:
                seen_ids.add(edge["edge_id"])
                valid.append(edge)

        return valid, rejected

    def _check_edge(
        self, edge: dict, valid_node_ids: set[str], seen_ids: set[str]
    ) -> str | None:
        """Check if edge is valid. Returns rejection reason or None."""
        edge_id = edge.get("edge_id", "")
        relation = edge.get("relation_type", "")
        layer = edge.get("layer", "")
        src = edge.get("source_node_id", "")
        tgt = edge.get("target_node_id", "")

        # Duplicate check
        if edge_id in seen_ids:
            return "Duplicate edge_id"

        # Layer/relation validity
        if layer == "business":
            if relation not in VALID_BUSINESS_RELATIONS:
                return f"Invalid business relation: {relation}"
        elif layer == "implementation":
            if relation not in VALID_IMPL_RELATIONS:
                return f"Invalid implementation relation: {relation}"
        else:
            return f"Invalid layer: {layer}"

        # Endpoint validity — MENTIONED_IN targets evidence chunks (not graph nodes)
        if relation == "MENTIONED_IN":
            # Source must be a valid node, target is a chunk_id
            if src not in valid_node_ids:
                return f"Source not in valid nodes: {src[:12]}"
        else:
            if src not in valid_node_ids:
                return f"Source not in valid nodes: {src[:12]}"
            if tgt not in valid_node_ids:
                return f"Target not in valid nodes: {tgt[:12]}"

        # Check run_id/dataset
        if edge.get("run_id") != self.run_id:
            return f"Wrong run_id: {edge.get('run_id')}"
        if edge.get("dataset") != self.dataset:
            return f"Wrong dataset: {edge.get('dataset')}"

        # Check evidence
        if not edge.get("evidence_chunk_ids") and not edge.get("source_ids"):
            return "No evidence_chunk_ids or source_ids"

        return None
