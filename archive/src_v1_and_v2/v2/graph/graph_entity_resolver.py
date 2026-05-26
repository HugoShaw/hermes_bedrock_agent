"""
Graph Entity Resolver for Stage 07.

Performs entity resolution across Business and Implementation graphs:
1. Merge exact duplicate nodes within same layer+label
2. Merge exact duplicate edges
3. Detect cross-layer alias candidates
4. Generate alias records (entity_aliases.jsonl)

Design principles:
- Conservative merging: only merge when safe (exact match within same layer+label)
- Cross-layer entities are linked, not merged
- CJK / multilingual aliases are recorded as candidates but not auto-merged
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.graph_merge_utils import (
    normalize_key,
    normalize_technical_name,
    merge_nodes,
    merge_edges,
    detect_duplicate_nodes,
    detect_duplicate_edges,
    merge_string_lists,
    is_generic_name,
)


class GraphEntityResolver:
    """Resolves entities across Business and Implementation graphs."""

    def __init__(
        self,
        business_nodes: list[dict[str, Any]],
        business_edges: list[dict[str, Any]],
        implementation_nodes: list[dict[str, Any]],
        implementation_edges: list[dict[str, Any]],
    ):
        self.business_nodes = business_nodes
        self.business_edges = business_edges
        self.implementation_nodes = implementation_nodes
        self.implementation_edges = implementation_edges

        # Results
        self.resolved_nodes: list[dict[str, Any]] = []
        self.resolved_edges: list[dict[str, Any]] = []
        self.alias_records: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {}

    def resolve(self) -> dict[str, Any]:
        """Execute full entity resolution pipeline.
        
        Returns stats dict.
        """
        # Phase 1: Combine all nodes
        all_nodes = list(self.business_nodes) + list(self.implementation_nodes)
        all_edges = list(self.business_edges) + list(self.implementation_edges)

        # Phase 2: Merge exact duplicate nodes (same node_id)
        merged_nodes, node_merge_count = self._merge_duplicate_nodes(all_nodes)

        # Phase 3: Merge exact duplicate edges (same edge_id)
        merged_edges, edge_merge_count = self._merge_duplicate_edges(all_edges)

        # Phase 4: Detect within-layer name-based duplicates
        within_layer_merges, merged_nodes = self._merge_within_layer_name_duplicates(merged_nodes)

        # Phase 5: Generate alias records for cross-layer and cross-language candidates
        self.alias_records = self._generate_alias_records(merged_nodes)

        # Store results
        self.resolved_nodes = merged_nodes
        self.resolved_edges = merged_edges

        self.stats = {
            "input_business_nodes": len(self.business_nodes),
            "input_business_edges": len(self.business_edges),
            "input_implementation_nodes": len(self.implementation_nodes),
            "input_implementation_edges": len(self.implementation_edges),
            "total_input_nodes": len(all_nodes),
            "total_input_edges": len(all_edges),
            "exact_node_id_merges": node_merge_count,
            "exact_edge_id_merges": edge_merge_count,
            "within_layer_name_merges": within_layer_merges,
            "resolved_nodes": len(self.resolved_nodes),
            "resolved_edges": len(self.resolved_edges),
            "alias_records": len(self.alias_records),
            "cross_language_candidates": sum(
                1 for a in self.alias_records
                if a["alias_type"] == "cross_language_candidate"
            ),
            "technical_variant_candidates": sum(
                1 for a in self.alias_records
                if a["alias_type"] == "technical_variant"
            ),
        }
        return self.stats

    def _merge_duplicate_nodes(
        self, nodes: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Merge nodes with identical node_id."""
        id_to_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            id_to_nodes[node["node_id"]].append(node)

        merged = []
        merge_count = 0
        for nid, group in id_to_nodes.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                # Merge all into first
                result = group[0]
                for other in group[1:]:
                    result = merge_nodes(result, other)
                    merge_count += 1
                merged.append(result)
        return merged, merge_count

    def _merge_duplicate_edges(
        self, edges: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Merge edges with identical edge_id."""
        id_to_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            id_to_edges[edge["edge_id"]].append(edge)

        merged = []
        merge_count = 0
        for eid, group in id_to_edges.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                result = group[0]
                for other in group[1:]:
                    result = merge_edges(result, other)
                    merge_count += 1
                merged.append(result)
        return merged, merge_count

    def _merge_within_layer_name_duplicates(
        self, nodes: list[dict[str, Any]]
    ) -> tuple[int, list[dict[str, Any]]]:
        """Merge nodes within same layer+label that have the same normalized name.
        
        This catches cases like:
        - Same table name appearing from different SQL chunks
        - Same class/file extracted multiple times
        
        Only merges if: same layer + same label + same normalized technical name.
        """
        # Group by (layer, label, normalized_name)
        groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for i, node in enumerate(nodes):
            key = (
                node.get("layer", ""),
                node.get("label", ""),
                normalize_technical_name(node.get("name", "")),
            )
            groups[key].append(i)

        merge_count = 0
        merged_indices: set[int] = set()
        result_nodes = []

        for key, indices in groups.items():
            if len(indices) == 1:
                result_nodes.append(nodes[indices[0]])
            else:
                # Merge all into first
                base = nodes[indices[0]]
                for idx in indices[1:]:
                    base = merge_nodes(base, nodes[idx])
                    merge_count += 1
                    merged_indices.add(idx)
                result_nodes.append(base)

        return merge_count, result_nodes

    def _generate_alias_records(
        self, nodes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate alias records for cross-layer and variant detection.
        
        Types of aliases:
        - exact: Same node_id, merged
        - normalized: Same normalized name within layer
        - technical_variant: e.g. PaymentService vs payment_service
        - cross_language_candidate: Japanese/Chinese/English potential matches
        """
        records: list[dict[str, Any]] = []

        # Build index by normalized name
        name_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            nkey = normalize_key(node.get("name", ""))
            if nkey:
                name_index[nkey].append(node)

        # Detect technical variants: same normalized name, different layers
        for nkey, group in name_index.items():
            if len(group) <= 1:
                continue
            if is_generic_name(nkey):
                continue

            # Check if we have cross-layer nodes
            layers = set(n.get("layer", "") for n in group)
            if len(layers) > 1:
                canonical = group[0]
                for other in group[1:]:
                    records.append({
                        "canonical_node_id": canonical["node_id"],
                        "alias": other["name"],
                        "alias_type": "technical_variant",
                        "source_node_ids": [other["node_id"]],
                        "confidence": 0.70,
                        "reason": (
                            f"Same normalized name '{nkey}' in different layers: "
                            f"{canonical['layer']}/{canonical['label']} vs "
                            f"{other['layer']}/{other['label']}"
                        ),
                    })

        # Detect cross-language candidates based on known Murata domain terms
        cjk_mapping_candidates = self._detect_cjk_alias_candidates(nodes)
        records.extend(cjk_mapping_candidates)

        # Record existing aliases from node alias fields
        for node in nodes:
            for alias in node.get("aliases", []):
                if alias != node["name"]:
                    records.append({
                        "canonical_node_id": node["node_id"],
                        "alias": alias,
                        "alias_type": "exact",
                        "source_node_ids": [node["node_id"]],
                        "confidence": 0.95,
                        "reason": "Pre-existing alias from extraction",
                    })

        return records

    def _detect_cjk_alias_candidates(
        self, nodes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Detect potential CJK/English alias candidates.
        
        Known domain mappings for Murata project:
        - 支払 / 支払申請 / 付款申请 → payment related
        - 入金 → receiving
        - 仕訳 → journal
        - 対帳 / 対帳単 → reconciliation
        
        These are candidates only, not automatic merges.
        """
        records: list[dict[str, Any]] = []

        # Known Murata domain term mappings (JP → concepts)
        domain_mappings = {
            "payment": ["支払", "付款", "支払申請", "付款申请", "payment"],
            "receiving": ["入金", "入金処理", "receiving"],
            "journal": ["仕訳", "仕訳基礎", "journal"],
            "reconciliation": ["対帳", "対帳単", "reconciliation"],
            "resource": ["リソース", "资源", "resource"],
            "role": ["角色", "ロール", "role"],
        }

        # Index nodes by concept domain (fuzzy matching)
        for concept, keywords in domain_mappings.items():
            matching_nodes = []
            for node in nodes:
                node_name_lower = node.get("name", "").lower()
                node_display_lower = node.get("display_name", "").lower()
                for kw in keywords:
                    if kw.lower() in node_name_lower or kw.lower() in node_display_lower:
                        matching_nodes.append(node)
                        break

            if len(matching_nodes) > 1:
                # Group by layer to avoid cross-layer noise
                canonical = matching_nodes[0]
                for other in matching_nodes[1:]:
                    if other["node_id"] != canonical["node_id"]:
                        records.append({
                            "canonical_node_id": canonical["node_id"],
                            "alias": other["name"],
                            "alias_type": "cross_language_candidate",
                            "source_node_ids": [other["node_id"]],
                            "confidence": 0.50,
                            "reason": (
                                f"Potential cross-language alias for concept "
                                f"'{concept}': '{canonical['name']}' ({canonical['layer']}/{canonical['label']}) "
                                f"↔ '{other['name']}' ({other['layer']}/{other['label']})"
                            ),
                        })

        return records
