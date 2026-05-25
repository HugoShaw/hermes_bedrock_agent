"""
Excel evidence linker — normalize evidence links for final unified graph,
validate evidence_chunk_ids, and enrich nodes/edges with evidence metadata.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvidenceLinkResult:
    """Result of evidence linking."""
    linked_nodes: list[dict] = field(default_factory=list)
    linked_edges: list[dict] = field(default_factory=list)
    evidence_links: list[dict] = field(default_factory=list)
    nodes_with_evidence: int = 0
    edges_with_evidence: int = 0
    total_links: int = 0
    invalid_evidence_refs: int = 0
    link_count_by_strategy: dict[str, int] = field(default_factory=dict)


class ExcelEvidenceLinker:
    """Normalize and validate evidence links for unified graph."""

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def link(
        self,
        nodes: list[dict],
        edges: list[dict],
        chunks: list[dict],
    ) -> EvidenceLinkResult:
        """Normalize evidence links.

        Parameters
        ----------
        nodes : filtered graph nodes
        edges : filtered graph edges
        chunks : evidence chunks with metadata
        """
        result = EvidenceLinkResult()

        # Build chunk lookup
        chunk_map = {c["chunk_id"]: c for c in chunks}
        valid_chunk_ids = set(chunk_map.keys())

        # Process nodes
        for node in nodes:
            linked_node, node_links = self._link_node(
                node, chunk_map, valid_chunk_ids
            )
            result.linked_nodes.append(linked_node)
            result.evidence_links.extend(node_links)
            if linked_node.get("evidence_chunk_ids"):
                result.nodes_with_evidence += 1

        # Process edges
        # Build node lookup for endpoint propagation
        node_evidence: dict[str, list[str]] = {}
        for n in result.linked_nodes:
            node_evidence[n["node_id"]] = n.get("evidence_chunk_ids", [])

        for edge in edges:
            linked_edge, edge_links = self._link_edge(
                edge, chunk_map, valid_chunk_ids, node_evidence
            )
            result.linked_edges.append(linked_edge)
            result.evidence_links.extend(edge_links)
            if linked_edge.get("evidence_chunk_ids"):
                result.edges_with_evidence += 1

        result.total_links = len(result.evidence_links)

        # Count by strategy
        for link in result.evidence_links:
            strategy = link.get("link_strategy", "unknown")
            result.link_count_by_strategy[strategy] = (
                result.link_count_by_strategy.get(strategy, 0) + 1
            )

        logger.info(
            f"Evidence linking: {result.nodes_with_evidence}/{len(nodes)} nodes, "
            f"{result.edges_with_evidence}/{len(edges)} edges linked, "
            f"{result.total_links} total links"
        )
        return result

    def _link_node(
        self,
        node: dict,
        chunk_map: dict[str, dict],
        valid_ids: set[str],
    ) -> tuple[dict, list[dict]]:
        """Link a node to evidence."""
        links: list[dict] = []
        linked = dict(node)

        # Validate existing evidence_chunk_ids
        valid_evidence = [
            eid for eid in node.get("evidence_chunk_ids", [])
            if eid in valid_ids
        ]
        invalid_count = len(node.get("evidence_chunk_ids", [])) - len(valid_evidence)
        if invalid_count > 0:
            logger.debug(
                f"Node {node['node_id'][:8]} has {invalid_count} invalid evidence refs"
            )

        linked["evidence_chunk_ids"] = valid_evidence

        # Add evidence metadata
        if valid_evidence:
            primary = valid_evidence[0]
            linked["properties"] = dict(linked.get("properties", {}))
            linked["properties"]["evidence_count"] = len(valid_evidence)
            linked["properties"]["primary_evidence_chunk_id"] = primary

            # Add quality score from chunk if available
            chunk = chunk_map.get(primary, {})
            meta = chunk.get("metadata", {})
            if meta.get("quality_score"):
                linked["properties"]["evidence_quality_score"] = meta["quality_score"]

        # Create evidence link records
        for eid in valid_evidence:
            chunk = chunk_map.get(eid, {})
            meta = chunk.get("metadata", {})
            link_record = {
                "link_id": hashlib.sha256(
                    f"{node['node_id']}:{eid}:node".encode()
                ).hexdigest()[:16],
                "graph_item_id": node["node_id"],
                "graph_item_type": "node",
                "graph_layer": node.get("layer", ""),
                "graph_label_or_relation": node.get("label", ""),
                "evidence_chunk_id": eid,
                "document_id": chunk.get("document_id", ""),
                "section_id": chunk.get("section_id", ""),
                "source_path": meta.get("s3_uri", meta.get("source_path", "")),
                "sheet_name": meta.get("sheet_name", ""),
                "cell_range": meta.get("cell_range", ""),
                "link_strategy": "existing",
                "confidence": node.get("confidence", 0.8),
                "reason": "Pre-existing evidence reference from extraction",
                "run_id": self.run_id,
                "dataset": self.dataset,
            }
            links.append(link_record)

        return linked, links

    def _link_edge(
        self,
        edge: dict,
        chunk_map: dict[str, dict],
        valid_ids: set[str],
        node_evidence: dict[str, list[str]],
    ) -> tuple[dict, list[dict]]:
        """Link an edge to evidence."""
        links: list[dict] = []
        linked = dict(edge)

        # Validate existing evidence_chunk_ids
        valid_evidence = [
            eid for eid in edge.get("evidence_chunk_ids", [])
            if eid in valid_ids
        ]

        # If no valid evidence, propagate from endpoints
        if not valid_evidence:
            src_ev = node_evidence.get(edge.get("source_node_id", ""), [])
            tgt_ev = node_evidence.get(edge.get("target_node_id", ""), [])

            # Prefer shared evidence
            shared = set(src_ev) & set(tgt_ev)
            if shared:
                valid_evidence = list(shared)[:2]
                strategy = "shared_evidence"
            elif src_ev:
                valid_evidence = src_ev[:1]
                strategy = "endpoint_propagation"
            elif tgt_ev:
                valid_evidence = tgt_ev[:1]
                strategy = "endpoint_propagation"
            else:
                strategy = "none"
        else:
            strategy = "existing"

        linked["evidence_chunk_ids"] = valid_evidence

        # Add evidence metadata
        if valid_evidence:
            linked["properties"] = dict(linked.get("properties", {}))
            linked["properties"]["evidence_count"] = len(valid_evidence)
            linked["properties"]["primary_evidence_chunk_id"] = valid_evidence[0]

        # Create evidence link records
        for eid in valid_evidence:
            chunk = chunk_map.get(eid, {})
            meta = chunk.get("metadata", {})
            link_record = {
                "link_id": hashlib.sha256(
                    f"{edge['edge_id']}:{eid}:edge".encode()
                ).hexdigest()[:16],
                "graph_item_id": edge["edge_id"],
                "graph_item_type": "edge",
                "graph_layer": edge.get("layer", ""),
                "graph_label_or_relation": edge.get("relation_type", ""),
                "evidence_chunk_id": eid,
                "document_id": chunk.get("document_id", ""),
                "section_id": chunk.get("section_id", ""),
                "source_path": meta.get("s3_uri", meta.get("source_path", "")),
                "sheet_name": meta.get("sheet_name", ""),
                "cell_range": meta.get("cell_range", ""),
                "link_strategy": strategy,
                "confidence": edge.get("confidence", 0.7),
                "reason": f"Evidence linked via {strategy}",
                "run_id": self.run_id,
                "dataset": self.dataset,
            }
            links.append(link_record)

        return linked, links
