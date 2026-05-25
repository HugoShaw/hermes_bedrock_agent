"""
Excel implementation graph builder — orchestrate mapping + API extraction,
merge nodes/edges, deduplicate, quality filter, and produce final graph.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_mapping_extractor import ExcelMappingExtractor
from hermes_bedrock_agent.v2.excel.excel_api_sequence_extractor import ExcelAPISequenceExtractor

logger = logging.getLogger(__name__)

# Allowed implementation node labels
VALID_IMPL_LABELS = {
    "System", "Module", "API", "Service", "Class", "Method",
    "Table", "Column", "SQL", "Job", "File", "ExternalSystem",
    "Config", "Message", "ErrorCode",
}

# Allowed implementation relation types
VALID_IMPL_RELATIONS = {
    "BELONGS_TO", "CONTAINS", "IMPLEMENTS", "USES", "CALLS",
    "READS", "WRITES", "MAPS_TO", "DEPENDS_ON", "TRIGGERS",
    "VALIDATES", "HAS_FIELD", "HAS_API", "HAS_METHOD", "HAS_TABLE",
    "HAS_COLUMN", "HAS_ERROR", "HAS_EVIDENCE", "MENTIONED_IN",
    "RELATED_TO",
}

# Generic names to reject
GENERIC_NAMES = {
    "", "data", "item", "value", "field", "table", "api", "column",
    "ー", "-", "—", "※", "N/A", "なし", "None", "null",
    "情報", "データ", "項目",
}


class ExcelImplementationGraphBuilder:
    """Build implementation graph from Excel evidence.

    Orchestrates:
    1. ExcelMappingExtractor for field mapping sheets
    2. ExcelAPISequenceExtractor for API/system sheets
    3. Merging, dedup, quality filtering
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
        output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.mapping_extractor = ExcelMappingExtractor(dataset=dataset, run_id=run_id)
        self.api_extractor = ExcelAPISequenceExtractor(dataset=dataset, run_id=run_id)
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.rejected: list[dict] = []
        self.low_confidence: list[dict] = []
        self._stats: dict[str, Any] = {}

    def build(self, candidate_chunks: list[dict], dry_run: bool = False) -> dict[str, Any]:
        """Build implementation graph from candidate evidence chunks.

        Parameters
        ----------
        candidate_chunks : list[dict]
            Selected implementation-relevant evidence chunks.
        dry_run : bool
            If True, only report what would be extracted without writing files.

        Returns
        -------
        dict with extraction statistics.
        """
        logger.info(f"Building implementation graph from {len(candidate_chunks)} chunks")

        # Run mapping extraction on field_mapping chunks
        mapping_chunks = [
            c for c in candidate_chunks
            if c.get("metadata", {}).get("guessed_sheet_type") == "field_mapping_sheet"
        ]
        self.mapping_extractor.extract_from_chunks(mapping_chunks)

        # Run API extraction on api_interface chunks
        api_chunks = [
            c for c in candidate_chunks
            if c.get("metadata", {}).get("guessed_sheet_type") == "api_interface_sheet"
            or c["chunk_type"] == "api"
        ]
        self.api_extractor.extract_from_chunks(api_chunks)

        # Merge nodes from both extractors
        all_nodes = self.mapping_extractor.nodes + self.api_extractor.nodes
        all_edges = self.mapping_extractor.edges + self.api_extractor.edges
        all_rejected = self.mapping_extractor.rejected + self.api_extractor.rejected
        all_low_conf = self.mapping_extractor.low_confidence + self.api_extractor.low_confidence

        # Deduplicate and merge
        self.nodes = self._deduplicate_nodes(all_nodes)
        self.edges = self._deduplicate_edges(all_edges)
        self.rejected = all_rejected
        self.low_confidence = all_low_conf

        # Quality filter
        self._quality_filter()

        # Compute stats
        self._stats = self._compute_stats(candidate_chunks)

        if not dry_run:
            self._write_outputs()

        return self._stats

    def _deduplicate_nodes(self, nodes: list[dict]) -> list[dict]:
        """Merge duplicate nodes by node_id."""
        seen: dict[str, dict] = {}
        for node in nodes:
            nid = node["node_id"]
            if nid in seen:
                # Merge evidence_chunk_ids
                existing = seen[nid]
                for eid in node.get("evidence_chunk_ids", []):
                    if eid not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(eid)
                # Merge aliases
                for alias in node.get("aliases", []):
                    if alias and alias not in existing["aliases"]:
                        existing["aliases"].append(alias)
                # Keep higher confidence
                if node["confidence"] > existing["confidence"]:
                    existing["confidence"] = node["confidence"]
            else:
                seen[nid] = node
        return list(seen.values())

    def _deduplicate_edges(self, edges: list[dict]) -> list[dict]:
        """Merge duplicate edges by edge_id."""
        seen: dict[str, dict] = {}
        for edge in edges:
            eid = edge["edge_id"]
            if eid in seen:
                existing = seen[eid]
                for chunk_id in edge.get("evidence_chunk_ids", []):
                    if chunk_id not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(chunk_id)
                if edge["confidence"] > existing["confidence"]:
                    existing["confidence"] = edge["confidence"]
            else:
                seen[eid] = edge
        return list(seen.values())

    def _quality_filter(self) -> None:
        """Remove invalid/generic nodes and edges."""
        valid_nodes = []
        valid_node_ids = set()

        for node in self.nodes:
            # Check label validity
            if node["label"] not in VALID_IMPL_LABELS:
                self.rejected.append({
                    "type": "node",
                    "item": node,
                    "reason": f"invalid_label:{node['label']}",
                })
                continue

            # Check for generic names
            display_name = node.get("display_name", "").strip()
            name = node.get("name", "").strip()
            if display_name.lower() in GENERIC_NAMES or name in GENERIC_NAMES:
                self.rejected.append({
                    "type": "node",
                    "item": node,
                    "reason": f"generic_name:{display_name}",
                })
                continue

            # Check evidence
            if not node.get("evidence_chunk_ids") and not node.get("source_ids"):
                self.rejected.append({
                    "type": "node",
                    "item": node,
                    "reason": "no_evidence",
                })
                continue

            # Validate layer
            if node["layer"] != "implementation":
                node["layer"] = "implementation"

            # Validate run_id / dataset
            node["run_id"] = self.run_id
            node["dataset"] = self.dataset

            valid_nodes.append(node)
            valid_node_ids.add(node["node_id"])

        # Filter edges — both endpoints must exist
        valid_edges = []
        for edge in self.edges:
            if edge["relation_type"] not in VALID_IMPL_RELATIONS:
                self.rejected.append({
                    "type": "edge",
                    "item": edge,
                    "reason": f"invalid_relation:{edge['relation_type']}",
                })
                continue

            if edge["source_node_id"] not in valid_node_ids:
                self.rejected.append({
                    "type": "edge",
                    "item": edge,
                    "reason": f"missing_source_node:{edge['source_node_id'][:8]}",
                })
                continue

            if edge["target_node_id"] not in valid_node_ids:
                self.rejected.append({
                    "type": "edge",
                    "item": edge,
                    "reason": f"missing_target_node:{edge['target_node_id'][:8]}",
                })
                continue

            # Check evidence
            if not edge.get("evidence_chunk_ids") and not edge.get("source_ids"):
                self.rejected.append({
                    "type": "edge",
                    "item": edge,
                    "reason": "no_evidence",
                })
                continue

            # Validate layer/run_id/dataset
            edge["layer"] = "implementation"
            edge["run_id"] = self.run_id
            edge["dataset"] = self.dataset

            valid_edges.append(edge)

        self.nodes = valid_nodes
        self.edges = valid_edges

    def _compute_stats(self, candidate_chunks: list[dict]) -> dict[str, Any]:
        """Compute extraction statistics."""
        node_labels = Counter(n["label"] for n in self.nodes)
        edge_relations = Counter(e["relation_type"] for e in self.edges)

        # Sheets processed
        sheets_processed = set()
        for c in candidate_chunks:
            sheets_processed.add(c.get("metadata", {}).get("sheet_name", ""))

        # Evidence coverage
        nodes_with_evidence = sum(
            1 for n in self.nodes if n.get("evidence_chunk_ids")
        )
        edges_with_evidence = sum(
            1 for e in self.edges if e.get("evidence_chunk_ids")
        )

        maps_to_count = edge_relations.get("MAPS_TO", 0)

        return {
            "total_candidate_chunks": len(candidate_chunks),
            "sheets_processed": sorted(sheets_processed),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "node_count_by_label": dict(node_labels),
            "edge_count_by_relation": dict(edge_relations),
            "maps_to_count": maps_to_count,
            "rejected_count": len(self.rejected),
            "low_confidence_count": len(self.low_confidence),
            "nodes_with_evidence": nodes_with_evidence,
            "edges_with_evidence": edges_with_evidence,
            "evidence_coverage_nodes": (
                nodes_with_evidence / len(self.nodes) if self.nodes else 0
            ),
            "evidence_coverage_edges": (
                edges_with_evidence / len(self.edges) if self.edges else 0
            ),
        }

    def _write_outputs(self) -> None:
        """Write graph outputs to JSONL files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Implementation nodes
        nodes_path = self.output_dir / "implementation_nodes.jsonl"
        with open(nodes_path, "w", encoding="utf-8") as f:
            for node in self.nodes:
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(self.nodes)} nodes to {nodes_path}")

        # Implementation edges
        edges_path = self.output_dir / "implementation_edges.jsonl"
        with open(edges_path, "w", encoding="utf-8") as f:
            for edge in self.edges:
                f.write(json.dumps(edge, ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(self.edges)} edges to {edges_path}")

        # Rejected items
        rejected_path = self.output_dir / "rejected_excel_implementation_graph_items.jsonl"
        with open(rejected_path, "w", encoding="utf-8") as f:
            for item in self.rejected:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        logger.info(f"Wrote {len(self.rejected)} rejected items to {rejected_path}")

        # Low confidence items
        low_conf_path = self.output_dir / "low_confidence_excel_implementation_items.jsonl"
        with open(low_conf_path, "w", encoding="utf-8") as f:
            for item in self.low_confidence:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        logger.info(f"Wrote {len(self.low_confidence)} low-confidence items to {low_conf_path}")

    def get_stats(self) -> dict[str, Any]:
        return self._stats
