"""
Excel entity resolver — resolve duplicates within each layer, generate alias records.
Does NOT merge cross-layer entities (uses cross_layer_linker instead).
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EntityResolutionResult:
    """Result of entity resolution pass."""
    merged_node_count: int = 0
    merged_edge_count: int = 0
    alias_records: list[dict] = field(default_factory=list)
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)


class ExcelEntityResolver:
    """Resolve entity duplicates within same-layer graphs.

    Safe merges (same layer + same label + same context):
    - Exact duplicate nodes (same node_id)
    - Same BusinessTerm with same display_name
    - Same BusinessRule with same display_name
    - Same Function with same display_name

    Unsafe (NOT merged, only aliased):
    - Column with same name but different Message/System context
    - Message with same base name but different sheet context
    - Cross-layer entities (BusinessTerm vs System/Column)
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def resolve(
        self,
        impl_nodes: list[dict],
        impl_edges: list[dict],
        biz_nodes: list[dict],
        biz_edges: list[dict],
    ) -> EntityResolutionResult:
        """Resolve entities within each layer."""
        result = EntityResolutionResult()

        # Resolve business layer
        biz_resolved, biz_aliases, biz_merges = self._resolve_layer(
            biz_nodes, "business"
        )
        # Resolve implementation layer
        impl_resolved, impl_aliases, impl_merges = self._resolve_layer(
            impl_nodes, "implementation"
        )

        result.nodes = impl_resolved + biz_resolved
        result.alias_records = impl_aliases + biz_aliases
        result.merged_node_count = impl_merges + biz_merges

        # Deduplicate edges
        all_edges = impl_edges + biz_edges
        deduped_edges, edge_merges = self._deduplicate_edges(all_edges)
        result.edges = deduped_edges
        result.merged_edge_count = edge_merges

        logger.info(
            f"Entity resolution: merged {result.merged_node_count} nodes, "
            f"{result.merged_edge_count} edges, "
            f"generated {len(result.alias_records)} aliases"
        )
        return result

    def _resolve_layer(
        self, nodes: list[dict], layer: str
    ) -> tuple[list[dict], list[dict], int]:
        """Resolve duplicates within a layer."""
        aliases: list[dict] = []
        merge_count = 0

        # Group by (label, name) for potential merges
        groups: dict[str, list[dict]] = defaultdict(list)
        for node in nodes:
            # For Columns, include parent context to avoid unsafe merges
            if node["label"] == "Column":
                # Columns with same name under different Systems are NOT duplicates
                ctx = node.get("properties", {}).get("sheet_name", "")
                key = f"{node['label']}:{node['name']}:{ctx}"
            elif node["label"] == "Message":
                # Messages like 中間F_IF under different sheets are context-specific
                ctx = node.get("properties", {}).get("sheet_name", "")
                key = f"{node['label']}:{node['display_name']}:{ctx}"
            else:
                key = f"{node['label']}:{node['name']}"
            groups[key].append(node)

        resolved: list[dict] = []
        for key, group in groups.items():
            if len(group) == 1:
                resolved.append(group[0])
            else:
                # Merge duplicates
                canonical = group[0]
                for other in group[1:]:
                    # Merge evidence
                    for eid in other.get("evidence_chunk_ids", []):
                        if eid not in canonical["evidence_chunk_ids"]:
                            canonical["evidence_chunk_ids"].append(eid)
                    for sid in other.get("source_ids", []):
                        if sid not in canonical["source_ids"]:
                            canonical["source_ids"].append(sid)
                    # Merge aliases
                    for alias in other.get("aliases", []):
                        if alias not in canonical.get("aliases", []):
                            canonical.setdefault("aliases", []).append(alias)
                    # Keep highest confidence
                    canonical["confidence"] = max(
                        canonical.get("confidence", 0),
                        other.get("confidence", 0),
                    )

                    # Create alias record
                    aliases.append({
                        "canonical_node_id": canonical["node_id"],
                        "alias": other.get("display_name", other.get("name", "")),
                        "alias_type": "exact",
                        "source_node_ids": [other["node_id"]],
                        "confidence": 0.95,
                        "reason": f"Same {layer} layer, same label+name, merged",
                        "run_id": self.run_id,
                        "dataset": self.dataset,
                    })
                    merge_count += 1

                resolved.append(canonical)

        return resolved, aliases, merge_count

    def _deduplicate_edges(
        self, edges: list[dict]
    ) -> tuple[list[dict], int]:
        """Deduplicate edges by edge_id."""
        seen: dict[str, dict] = {}
        merge_count = 0

        for edge in edges:
            eid = edge["edge_id"]
            if eid in seen:
                existing = seen[eid]
                for chunk_id in edge.get("evidence_chunk_ids", []):
                    if chunk_id not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(chunk_id)
                merge_count += 1
            else:
                seen[eid] = edge

        return list(seen.values()), merge_count
