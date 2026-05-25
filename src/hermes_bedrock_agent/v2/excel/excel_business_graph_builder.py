"""
Excel business graph builder — orchestrate flowchart + rule extraction,
merge nodes/edges, deduplicate, quality filter, and produce final business graph.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_flowchart_extractor import (
    ExcelFlowchartExtractor,
)
from hermes_bedrock_agent.v2.excel.excel_business_rule_extractor import (
    ExcelBusinessRuleExtractor,
)

logger = logging.getLogger(__name__)

# Valid business labels from schema_registry
VALID_BUSINESS_LABELS = {
    "Project", "BusinessDomain", "BusinessProcess", "BusinessStep",
    "BusinessRule", "BusinessTerm", "Function", "Screen",
    "Role", "Organization", "Document", "EvidenceChunk",
}

VALID_BUSINESS_RELATIONS = {
    "BELONGS_TO", "CONTAINS", "HAS_STEP", "NEXT_STEP",
    "HAS_RULE", "HAS_TERM", "HAS_FUNCTION", "VALIDATES",
    "USES", "DEPENDS_ON", "HAS_EVIDENCE", "MENTIONED_IN", "RELATED_TO",
}

# Generic terms to reject unless qualified
GENERIC_NAMES = {"データ", "処理", "条件", "項目", "情報", "値", "フラグ"}


@dataclass
class BusinessGraphResult:
    """Result of business graph extraction."""
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    low_confidence: list[dict] = field(default_factory=list)
    node_count_by_label: dict[str, int] = field(default_factory=dict)
    edge_count_by_relation: dict[str, int] = field(default_factory=dict)
    process_count: int = 0
    step_count: int = 0
    rule_count: int = 0
    term_count: int = 0
    function_count: int = 0
    domain_count: int = 0
    evidence_coverage_nodes: float = 0.0
    evidence_coverage_edges: float = 0.0


class ExcelBusinessGraphBuilder:
    """Build business semantic graph from Excel evidence."""

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
        output_dir: str | Path = "data/outputs/sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.rejected: list[dict] = []
        self.low_confidence: list[dict] = []
        self._node_id_map: dict[str, dict] = {}

    def build(
        self,
        chunks: list[dict],
        rows: list[dict] | None = None,
    ) -> BusinessGraphResult:
        """Build business graph from selected evidence.

        Parameters
        ----------
        chunks : business candidate evidence chunks
        rows : normalized rows (optional, for row-level extraction)
        """
        logger.info(f"Building business graph from {len(chunks)} chunks")

        # Separate chunks by type
        process_chunks = [
            c for c in chunks
            if c.get("metadata", {}).get("guessed_sheet_type") == "business_process_sheet"
        ]
        rule_chunks = [
            c for c in chunks
            if c.get("metadata", {}).get("guessed_sheet_type") == "business_rule_sheet"
            or "データ取得条件" in c.get("metadata", {}).get("sheet_name", "")
        ]

        # 1. Extract flowchart / process nodes
        flowchart_ext = ExcelFlowchartExtractor(self.dataset, self.run_id)
        flowchart_ext.extract_from_chunks(process_chunks, rows)

        # 2. Extract business rules and terms
        rule_ext = ExcelBusinessRuleExtractor(self.dataset, self.run_id)
        rule_ext.extract_from_chunks(rule_chunks, rows)

        # 3. Merge all nodes and edges
        all_nodes = flowchart_ext.nodes + rule_ext.nodes
        all_edges = flowchart_ext.edges + rule_ext.edges
        all_rejected = flowchart_ext.rejected + rule_ext.rejected
        all_low = flowchart_ext.low_confidence + rule_ext.low_confidence

        # 4. Add project and domain nodes
        self._add_project_and_domains(all_nodes, all_edges, chunks)

        # 5. Add MENTIONED_IN edges for evidence traceability
        self._add_evidence_edges(all_nodes, all_edges, chunks)

        # 6. Deduplicate
        all_nodes = self._deduplicate_nodes(all_nodes)
        all_edges = self._deduplicate_edges(all_edges)

        # 7. Quality filter
        all_nodes, rejected_nodes = self._filter_nodes(all_nodes)
        all_edges, rejected_edges = self._filter_edges(all_edges, all_nodes)

        all_rejected.extend(rejected_nodes)
        all_rejected.extend(rejected_edges)

        # 8. Validate schema compliance
        all_nodes = self._validate_nodes(all_nodes)
        all_edges = self._validate_edges(all_edges)

        self.nodes = all_nodes
        self.edges = all_edges
        self.rejected = all_rejected
        self.low_confidence = all_low

        # Build result
        result = self._build_result()
        return result

    def _add_project_and_domains(
        self,
        nodes: list[dict],
        edges: list[dict],
        chunks: list[dict],
    ) -> None:
        """Add Project node and BusinessDomain nodes."""
        chunk_ids = [c["chunk_id"] for c in chunks[:3]]

        # Project node
        project_id = hashlib.sha256(
            f"{self.dataset}:biz:Project:sample_20260519".encode()
        ).hexdigest()[:16]
        project_node = {
            "node_id": project_id,
            "label": "Project",
            "name": "sample_20260519",
            "display_name": "sample_20260519",
            "layer": "business",
            "aliases": [],
            "description": "SAP-Andpad integration project (sample 2026-05-19)",
            "properties": {"extraction_method": "project_level"},
            "source_ids": [],
            "evidence_chunk_ids": chunk_ids,
            "confidence": 1.0,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        nodes.append(project_node)

        # Infer domains from sheet content
        domains = {
            "発注情報連携": "発注関連データ取得・連携",
            "納品情報連携": "納品関連データ取得・連携",
        }

        for domain_name, domain_desc in domains.items():
            domain_id = hashlib.sha256(
                f"{self.dataset}:biz:BusinessDomain:{domain_name}".encode()
            ).hexdigest()[:16]
            domain_node = {
                "node_id": domain_id,
                "label": "BusinessDomain",
                "name": domain_name.lower(),
                "display_name": domain_name,
                "layer": "business",
                "aliases": [],
                "description": domain_desc,
                "properties": {"extraction_method": "sheet_grouping"},
                "source_ids": [],
                "evidence_chunk_ids": chunk_ids[:1],
                "confidence": 0.75,
                "run_id": self.run_id,
                "dataset": self.dataset,
            }
            nodes.append(domain_node)

            # Project CONTAINS BusinessDomain
            edge_id = hashlib.sha256(
                f"{self.dataset}:biz:{project_id}:{domain_id}:CONTAINS".encode()
            ).hexdigest()[:16]
            edges.append({
                "edge_id": edge_id,
                "source_node_id": project_id,
                "target_node_id": domain_id,
                "relation_type": "CONTAINS",
                "layer": "business",
                "description": f"Project contains domain {domain_name}",
                "properties": {},
                "source_ids": [],
                "evidence_chunk_ids": chunk_ids[:1],
                "confidence": 0.75,
                "run_id": self.run_id,
                "dataset": self.dataset,
            })

        # Link functions to domains
        for node in nodes:
            if node["label"] == "Function":
                fn_name = node["display_name"]
                # Determine domain
                if "発注" in fn_name:
                    target_domain = "発注情報連携"
                elif "納品" in fn_name:
                    target_domain = "納品情報連携"
                else:
                    continue

                # Find domain node
                for dn in nodes:
                    if dn["label"] == "BusinessDomain" and dn["display_name"] == target_domain:
                        edge_id = hashlib.sha256(
                            f"{self.dataset}:biz:{dn['node_id']}:{node['node_id']}:HAS_FUNCTION".encode()
                        ).hexdigest()[:16]
                        edges.append({
                            "edge_id": edge_id,
                            "source_node_id": dn["node_id"],
                            "target_node_id": node["node_id"],
                            "relation_type": "HAS_FUNCTION",
                            "layer": "business",
                            "description": f"{target_domain} has function {fn_name}",
                            "properties": {},
                            "source_ids": [],
                            "evidence_chunk_ids": node["evidence_chunk_ids"][:1],
                            "confidence": 0.7,
                            "run_id": self.run_id,
                            "dataset": self.dataset,
                        })
                        break

    def _add_evidence_edges(
        self,
        nodes: list[dict],
        edges: list[dict],
        chunks: list[dict],
    ) -> None:
        """Add MENTIONED_IN edges linking nodes to evidence chunks."""
        # Build chunk lookup
        chunk_map = {c["chunk_id"]: c for c in chunks}

        for node in nodes:
            if node["label"] in ("Project", "EvidenceChunk"):
                continue
            for chunk_id in node.get("evidence_chunk_ids", [])[:2]:
                if chunk_id in chunk_map:
                    edge_id = hashlib.sha256(
                        f"{self.dataset}:biz:{node['node_id']}:{chunk_id}:MENTIONED_IN".encode()
                    ).hexdigest()[:16]
                    # Avoid duplicates
                    if not any(e["edge_id"] == edge_id for e in edges):
                        edges.append({
                            "edge_id": edge_id,
                            "source_node_id": node["node_id"],
                            "target_node_id": chunk_id,
                            "relation_type": "MENTIONED_IN",
                            "layer": "business",
                            "description": f"{node['display_name']} mentioned in evidence",
                            "properties": {},
                            "source_ids": [],
                            "evidence_chunk_ids": [chunk_id],
                            "confidence": 0.9,
                            "run_id": self.run_id,
                            "dataset": self.dataset,
                        })

    def _deduplicate_nodes(self, nodes: list[dict]) -> list[dict]:
        """Remove duplicate nodes."""
        seen = {}
        deduped = []
        for node in nodes:
            key = f"{node['label']}:{node['name']}"
            if key in seen:
                existing = seen[key]
                for eid in node.get("evidence_chunk_ids", []):
                    if eid not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(eid)
            else:
                seen[key] = node
                deduped.append(node)
        return deduped

    def _deduplicate_edges(self, edges: list[dict]) -> list[dict]:
        """Remove duplicate edges."""
        seen = {}
        deduped = []
        for edge in edges:
            key = edge["edge_id"]
            if key in seen:
                existing = seen[key]
                for eid in edge.get("evidence_chunk_ids", []):
                    if eid not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(eid)
            else:
                seen[key] = edge
                deduped.append(edge)
        return deduped

    def _filter_nodes(self, nodes: list[dict]) -> tuple[list[dict], list[dict]]:
        """Filter out generic/low-quality nodes."""
        kept = []
        rejected = []
        for node in nodes:
            name = node.get("display_name", "")
            # Reject bare generic terms
            if name in GENERIC_NAMES:
                rejected.append({
                    "type": "generic_node_rejected",
                    "node_id": node["node_id"],
                    "label": node["label"],
                    "display_name": name,
                    "reason": "Bare generic term without context",
                })
                continue
            # Reject empty display names
            if not name.strip():
                rejected.append({
                    "type": "empty_name_rejected",
                    "node_id": node["node_id"],
                    "label": node["label"],
                })
                continue
            kept.append(node)
        return kept, rejected

    def _filter_edges(
        self, edges: list[dict], valid_nodes: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """Filter edges with invalid endpoints."""
        valid_ids = {n["node_id"] for n in valid_nodes}
        # Also allow evidence chunk IDs as valid targets for MENTIONED_IN
        valid_ids_extended = set(valid_ids)

        kept = []
        rejected = []
        for edge in edges:
            src = edge["source_node_id"]
            tgt = edge["target_node_id"]
            rel = edge["relation_type"]

            # For MENTIONED_IN, target is a chunk_id — always valid
            if rel == "MENTIONED_IN":
                if src in valid_ids:
                    kept.append(edge)
                else:
                    rejected.append({
                        "type": "orphan_edge_rejected",
                        "edge_id": edge["edge_id"],
                        "relation": rel,
                        "reason": f"source {src} not in valid nodes",
                    })
            else:
                if src in valid_ids and tgt in valid_ids:
                    kept.append(edge)
                else:
                    rejected.append({
                        "type": "orphan_edge_rejected",
                        "edge_id": edge["edge_id"],
                        "relation": rel,
                        "reason": f"endpoint not in valid nodes",
                    })
        return kept, rejected

    def _validate_nodes(self, nodes: list[dict]) -> list[dict]:
        """Ensure schema compliance."""
        valid = []
        for node in nodes:
            node["layer"] = "business"
            node["run_id"] = self.run_id
            node["dataset"] = self.dataset
            if node["label"] not in VALID_BUSINESS_LABELS:
                logger.warning(f"Invalid label {node['label']}, skipping")
                continue
            if not node.get("evidence_chunk_ids") and not node.get("source_ids"):
                node["confidence"] = min(node.get("confidence", 0.5), 0.3)
            valid.append(node)
        return valid

    def _validate_edges(self, edges: list[dict]) -> list[dict]:
        """Ensure schema compliance."""
        valid = []
        for edge in edges:
            edge["layer"] = "business"
            edge["run_id"] = self.run_id
            edge["dataset"] = self.dataset
            if edge["relation_type"] not in VALID_BUSINESS_RELATIONS:
                logger.warning(f"Invalid relation {edge['relation_type']}, skipping")
                continue
            valid.append(edge)
        return valid

    def _build_result(self) -> BusinessGraphResult:
        """Compute result metrics."""
        result = BusinessGraphResult(
            nodes=self.nodes,
            edges=self.edges,
            rejected=self.rejected,
            low_confidence=self.low_confidence,
        )

        # Count by label
        for node in self.nodes:
            label = node["label"]
            result.node_count_by_label[label] = result.node_count_by_label.get(label, 0) + 1

        # Count by relation
        for edge in self.edges:
            rel = edge["relation_type"]
            result.edge_count_by_relation[rel] = result.edge_count_by_relation.get(rel, 0) + 1

        # Key counts
        result.process_count = result.node_count_by_label.get("BusinessProcess", 0)
        result.step_count = result.node_count_by_label.get("BusinessStep", 0)
        result.rule_count = result.node_count_by_label.get("BusinessRule", 0)
        result.term_count = result.node_count_by_label.get("BusinessTerm", 0)
        result.function_count = result.node_count_by_label.get("Function", 0)
        result.domain_count = result.node_count_by_label.get("BusinessDomain", 0)

        # Evidence coverage
        nodes_with_evidence = sum(
            1 for n in self.nodes if n.get("evidence_chunk_ids")
        )
        edges_with_evidence = sum(
            1 for e in self.edges if e.get("evidence_chunk_ids")
        )
        result.evidence_coverage_nodes = (
            nodes_with_evidence / len(self.nodes) if self.nodes else 0.0
        )
        result.evidence_coverage_edges = (
            edges_with_evidence / len(self.edges) if self.edges else 0.0
        )

        return result

    def write_outputs(self) -> dict[str, str]:
        """Write all output files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        files = {}

        # Nodes
        nodes_path = self.output_dir / "business_nodes.jsonl"
        with open(nodes_path, "w", encoding="utf-8") as f:
            for node in self.nodes:
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
        files["business_nodes"] = str(nodes_path)

        # Edges
        edges_path = self.output_dir / "business_edges.jsonl"
        with open(edges_path, "w", encoding="utf-8") as f:
            for edge in self.edges:
                f.write(json.dumps(edge, ensure_ascii=False) + "\n")
        files["business_edges"] = str(edges_path)

        # Rejected
        rejected_path = self.output_dir / "rejected_excel_business_graph_items.jsonl"
        with open(rejected_path, "w", encoding="utf-8") as f:
            for item in self.rejected:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        files["rejected"] = str(rejected_path)

        # Low confidence
        low_path = self.output_dir / "low_confidence_excel_business_items.jsonl"
        with open(low_path, "w", encoding="utf-8") as f:
            for item in self.low_confidence:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        files["low_confidence"] = str(low_path)

        logger.info(
            f"Wrote {len(self.nodes)} nodes, {len(self.edges)} edges, "
            f"{len(self.rejected)} rejected, {len(self.low_confidence)} low-confidence"
        )
        return files
