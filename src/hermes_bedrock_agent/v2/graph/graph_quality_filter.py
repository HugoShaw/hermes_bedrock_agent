"""
Graph Quality Filter for Stage 07.

Filters and scores graph nodes/edges for quality:
- Schema validation (labels, relations, layers)
- Evidence coverage check
- Orphan edge detection (edges pointing to non-existent nodes)
- Generic name detection
- SQL dump artifact detection
- Confidence thresholds

Design: Conservative — prefer warning over rejection for borderline cases.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.v2.graph.schema_registry import (
    ALLOWED_LAYERS,
    BUSINESS_LABELS,
    IMPLEMENTATION_LABELS,
    EVIDENCE_LABELS,
    is_valid_label,
    is_valid_relation,
    is_valid_layer,
    normalize_label,
    normalize_relation_type,
    validate_node_schema,
    validate_edge_schema,
)
from hermes_bedrock_agent.v2.graph.graph_merge_utils import (
    is_generic_name,
    compute_degree,
)


# Confidence threshold below which items are rejected
CONFIDENCE_REJECT_THRESHOLD = 0.1
# Confidence threshold below which items are warned
CONFIDENCE_WARN_THRESHOLD = 0.3

# SQL dump indicators
SQL_DUMP_INDICATORS = {
    "insert into", "insert_dump", "data_dump", "sql_dump",
    "journal_base20180530",
}


class GraphQualityFilter:
    """Filters and scores graph nodes/edges for quality."""

    def __init__(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
    ):
        self.input_nodes = nodes
        self.input_edges = edges
        self.run_id = run_id
        self.dataset = dataset

        # Results
        self.filtered_nodes: list[dict[str, Any]] = []
        self.filtered_edges: list[dict[str, Any]] = []
        self.rejected_items: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {}

    def filter(self) -> dict[str, Any]:
        """Execute full quality filter pipeline."""
        # Phase 1: Validate and score nodes
        valid_nodes, rejected_nodes = self._filter_nodes()

        # Phase 2: Build valid node_id set
        valid_node_ids = {n["node_id"] for n in valid_nodes}

        # Phase 3: Validate and filter edges (must reference valid nodes)
        valid_edges, rejected_edges = self._filter_edges(valid_node_ids)

        # Phase 4: Compute quality annotations
        degree_map = compute_degree(valid_nodes, valid_edges)
        for node in valid_nodes:
            node.setdefault("properties", {})
            nid = node["node_id"]
            node["properties"]["degree"] = degree_map.get(nid, 0)
            node["properties"]["is_isolated"] = degree_map.get(nid, 0) == 0
            node["properties"]["is_generic_name"] = is_generic_name(node.get("name", ""))
            node["properties"]["evidence_count"] = len(node.get("evidence_chunk_ids", []))
            node["properties"]["source_count"] = len(node.get("source_ids", []))
            # Quality score
            node["properties"]["quality_score"] = self._compute_node_quality(node, degree_map)

        # Store results
        self.filtered_nodes = valid_nodes
        self.filtered_edges = valid_edges
        self.rejected_items = rejected_nodes + rejected_edges

        # Compute stats
        self.stats = self._compute_stats()
        return self.stats

    def _filter_nodes(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Filter nodes, returning (valid, rejected)."""
        valid = []
        rejected = []

        for node in self.input_nodes:
            reject_reasons = []
            warnings = []

            label = node.get("label", "")
            layer = node.get("layer", "")
            name = node.get("name", "")
            confidence = node.get("confidence", 0.0)
            source_ids = node.get("source_ids", [])
            evidence_ids = node.get("evidence_chunk_ids", [])

            # 1. Schema validation
            is_valid, err = validate_node_schema(label, layer)
            if not is_valid:
                reject_reasons.append(f"schema_invalid: {err}")

            # 2. Layer validation
            if not is_valid_layer(layer):
                reject_reasons.append(f"invalid_layer: '{layer}'")

            # 3. Evidence check
            if not source_ids and not evidence_ids:
                reject_reasons.append("no_evidence: missing source_ids and evidence_chunk_ids")

            # 4. Confidence threshold
            if confidence < CONFIDENCE_REJECT_THRESHOLD:
                reject_reasons.append(f"very_low_confidence: {confidence}")
            elif confidence < CONFIDENCE_WARN_THRESHOLD:
                warnings.append(f"low_confidence: {confidence}")

            # 5. Generic name check
            if is_generic_name(name) and not evidence_ids:
                reject_reasons.append(f"generic_name_without_evidence: '{name}'")
            elif is_generic_name(name):
                warnings.append(f"generic_name: '{name}'")

            # 6. SQL dump artifact check
            if self._is_sql_dump_artifact(node):
                reject_reasons.append("sql_dump_artifact")

            # 7. run_id and dataset validation
            if node.get("run_id") != self.run_id:
                warnings.append(f"run_id_mismatch: expected '{self.run_id}', got '{node.get('run_id')}'")
            if node.get("dataset") != self.dataset:
                warnings.append(f"dataset_mismatch: expected '{self.dataset}', got '{node.get('dataset')}'")

            if reject_reasons:
                rejected.append({
                    "item_type": "node",
                    "item_id": node.get("node_id", "unknown"),
                    "label": label,
                    "layer": layer,
                    "name": name,
                    "reasons": reject_reasons,
                    "confidence": confidence,
                })
            else:
                node.setdefault("properties", {})
                if warnings:
                    node["properties"]["quality_warnings"] = warnings
                valid.append(node)

        return valid, rejected

    def _filter_edges(
        self, valid_node_ids: set[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Filter edges, returning (valid, rejected)."""
        valid = []
        rejected = []

        for edge in self.input_edges:
            reject_reasons = []
            warnings = []

            relation_type = edge.get("relation_type", "")
            layer = edge.get("layer", "")
            source_node = edge.get("source_node_id", "")
            target_node = edge.get("target_node_id", "")
            confidence = edge.get("confidence", 0.0)
            source_ids = edge.get("source_ids", [])
            evidence_ids = edge.get("evidence_chunk_ids", [])

            # 1. Schema validation
            is_valid, err = validate_edge_schema(relation_type, layer)
            if not is_valid:
                reject_reasons.append(f"schema_invalid: {err}")

            # 2. Orphan check: source/target must exist
            if source_node not in valid_node_ids:
                reject_reasons.append(f"orphan_source: node '{source_node}' not in filtered nodes")
            if target_node not in valid_node_ids:
                reject_reasons.append(f"orphan_target: node '{target_node}' not in filtered nodes")

            # 3. Evidence check
            if not source_ids and not evidence_ids:
                reject_reasons.append("no_evidence: missing source_ids and evidence_chunk_ids")

            # 4. Confidence threshold
            if confidence < CONFIDENCE_REJECT_THRESHOLD:
                reject_reasons.append(f"very_low_confidence: {confidence}")
            elif confidence < CONFIDENCE_WARN_THRESHOLD:
                warnings.append(f"low_confidence: {confidence}")

            # 5. Meaningless generic RELATED_TO check
            if relation_type == "RELATED_TO" and confidence < 0.5:
                reject_reasons.append(
                    f"meaningless_related_to: low-confidence ({confidence}) RELATED_TO edge"
                )

            # 6. Self-loop check
            if source_node == target_node:
                reject_reasons.append("self_loop: source == target")

            # 7. run_id/dataset validation
            if edge.get("run_id") != self.run_id:
                warnings.append(f"run_id_mismatch: expected '{self.run_id}'")
            if edge.get("dataset") != self.dataset:
                warnings.append(f"dataset_mismatch: expected '{self.dataset}'")

            if reject_reasons:
                rejected.append({
                    "item_type": "edge",
                    "item_id": edge.get("edge_id", "unknown"),
                    "relation_type": relation_type,
                    "layer": layer,
                    "source_node_id": source_node,
                    "target_node_id": target_node,
                    "reasons": reject_reasons,
                    "confidence": confidence,
                })
            else:
                edge.setdefault("properties", {})
                if warnings:
                    edge["properties"]["quality_warnings"] = warnings
                valid.append(edge)

        return valid, rejected

    def _is_sql_dump_artifact(self, node: dict[str, Any]) -> bool:
        """Check if a node is an artifact from SQL dump processing."""
        name = node.get("name", "").lower()
        source_ids = node.get("source_ids", [])
        properties = node.get("properties", {})

        # Check if it's a row/value node from INSERT dumps
        for indicator in SQL_DUMP_INDICATORS:
            if indicator in name:
                return True
            for sid in source_ids:
                if indicator in sid.lower():
                    # Only flag if the node itself seems like a dump artifact
                    # Table names from DDL that happen to have evidence in dump files are OK
                    label = node.get("label", "")
                    if label not in ("Table", "Column", "SQL", "File"):
                        return True
        return False

    def _compute_node_quality(
        self, node: dict[str, Any], degree_map: dict[str, int]
    ) -> float:
        """Compute a quality score for a node (0.0 to 1.0)."""
        score = 0.0

        # Evidence presence (max 0.3)
        evidence = node.get("evidence_chunk_ids", [])
        sources = node.get("source_ids", [])
        if evidence:
            score += min(0.3, 0.1 * len(evidence))
        if sources:
            score += min(0.1, 0.05 * len(sources))

        # Confidence (max 0.3)
        score += node.get("confidence", 0.0) * 0.3

        # Connectivity (max 0.2)
        degree = degree_map.get(node["node_id"], 0)
        score += min(0.2, degree * 0.05)

        # Name quality (max 0.1)
        if not is_generic_name(node.get("name", "")):
            score += 0.1

        return min(1.0, round(score, 3))

    def _compute_stats(self) -> dict[str, Any]:
        """Compute quality filter statistics."""
        node_labels = Counter(n["label"] for n in self.filtered_nodes)
        edge_relations = Counter(e["relation_type"] for e in self.filtered_edges)
        node_layers = Counter(n["layer"] for n in self.filtered_nodes)
        edge_layers = Counter(e["layer"] for e in self.filtered_edges)

        nodes_with_evidence = sum(
            1 for n in self.filtered_nodes
            if n.get("evidence_chunk_ids") or n.get("source_ids")
        )
        edges_with_evidence = sum(
            1 for e in self.filtered_edges
            if e.get("evidence_chunk_ids") or e.get("source_ids")
        )

        isolated_nodes = sum(
            1 for n in self.filtered_nodes
            if n.get("properties", {}).get("is_isolated", False)
        )
        generic_warnings = sum(
            1 for n in self.filtered_nodes
            if n.get("properties", {}).get("is_generic_name", False)
        )

        # API node count
        api_count = node_labels.get("API", 0)

        # SQL dump contamination check
        sql_dump_in_rejected = sum(
            1 for r in self.rejected_items
            if "sql_dump_artifact" in str(r.get("reasons", []))
        )

        # JOURNAL_BASE check
        journal_base_nodes = sum(
            1 for n in self.filtered_nodes
            if "journal_base" in n.get("name", "").lower()
        )

        return {
            "input_nodes": len(self.input_nodes),
            "input_edges": len(self.input_edges),
            "filtered_nodes": len(self.filtered_nodes),
            "filtered_edges": len(self.filtered_edges),
            "rejected_items": len(self.rejected_items),
            "rejected_nodes": sum(1 for r in self.rejected_items if r.get("item_type") == "node"),
            "rejected_edges": sum(1 for r in self.rejected_items if r.get("item_type") == "edge"),
            "node_labels": dict(node_labels.most_common()),
            "edge_relations": dict(edge_relations.most_common()),
            "node_layers": dict(node_layers),
            "edge_layers": dict(edge_layers),
            "nodes_with_evidence": nodes_with_evidence,
            "edges_with_evidence": edges_with_evidence,
            "node_evidence_ratio": nodes_with_evidence / max(1, len(self.filtered_nodes)),
            "edge_evidence_ratio": edges_with_evidence / max(1, len(self.filtered_edges)),
            "isolated_nodes": isolated_nodes,
            "generic_name_warnings": generic_warnings,
            "api_node_count": api_count,
            "sql_dump_rejected": sql_dump_in_rejected,
            "journal_base_node_count": journal_base_nodes,
        }
