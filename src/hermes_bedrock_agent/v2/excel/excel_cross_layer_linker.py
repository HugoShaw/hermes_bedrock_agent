"""
Excel cross-layer linker — create edges connecting business and implementation
graph entities through safe matching strategies.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Valid implementation layer relations (for cross-layer edges stored in impl layer)
VALID_IMPL_RELATIONS = {
    "BELONGS_TO", "CONTAINS", "IMPLEMENTS", "USES", "CALLS",
    "READS", "WRITES", "MAPS_TO", "DEPENDS_ON", "TRIGGERS",
    "VALIDATES", "HAS_FIELD", "HAS_API", "HAS_METHOD",
    "HAS_TABLE", "HAS_COLUMN", "HAS_ERROR", "HAS_EVIDENCE",
    "MENTIONED_IN", "RELATED_TO",
}


@dataclass
class CrossLayerResult:
    """Result of cross-layer linking."""
    links: list[dict] = field(default_factory=list)
    link_count_by_strategy: dict[str, int] = field(default_factory=dict)
    link_count_by_relation: dict[str, int] = field(default_factory=dict)


class ExcelCrossLayerLinker:
    """Create cross-layer links between business and implementation graphs.

    Strategies:
    1. exact_name_match: Function name appears in Message name
    2. substring_match: BusinessTerm name contained in Message/Column name
    3. shared_evidence: nodes share evidence_chunk_ids
    4. domain_system_match: BusinessDomain references System names
    5. rule_column_match: BusinessRule references Column fields
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def link(
        self,
        biz_nodes: list[dict],
        impl_nodes: list[dict],
    ) -> CrossLayerResult:
        """Generate cross-layer links."""
        result = CrossLayerResult()

        # Build lookups
        biz_by_label = defaultdict(list)
        for n in biz_nodes:
            biz_by_label[n["label"]].append(n)

        impl_by_label = defaultdict(list)
        for n in impl_nodes:
            impl_by_label[n["label"]].append(n)

        # Strategy 1: Function → Message (exact name match)
        self._link_function_to_message(
            biz_by_label["Function"],
            impl_by_label["Message"],
            result,
        )

        # Strategy 2: BusinessDomain → System
        self._link_domain_to_system(
            biz_by_label["BusinessDomain"],
            impl_by_label["System"],
            result,
        )

        # Strategy 3: BusinessTerm → Message/Column (substring)
        self._link_term_to_impl(
            biz_by_label["BusinessTerm"],
            impl_by_label["Message"],
            impl_by_label["Column"],
            result,
        )

        # Strategy 4: BusinessRule → Column (shared evidence)
        self._link_rule_to_column_by_evidence(
            biz_by_label["BusinessRule"],
            impl_by_label["Column"],
            result,
        )

        logger.info(
            f"Cross-layer linking: {len(result.links)} links generated, "
            f"strategies: {dict(result.link_count_by_strategy)}"
        )
        return result

    def _make_edge_id(self, src: str, tgt: str, rel: str) -> str:
        raw = f"{self.dataset}:xlink:{src}:{tgt}:{rel}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _add_link(
        self,
        source_node: dict,
        target_node: dict,
        relation_type: str,
        strategy: str,
        confidence: float,
        reason: str,
        result: CrossLayerResult,
    ) -> None:
        """Add a cross-layer link edge."""
        edge_id = self._make_edge_id(
            source_node["node_id"], target_node["node_id"], relation_type
        )

        # Check for duplicates
        if any(l["edge_id"] == edge_id for l in result.links):
            return

        # Merge evidence from both sides
        evidence_ids = []
        for eid in source_node.get("evidence_chunk_ids", [])[:2]:
            if eid not in evidence_ids:
                evidence_ids.append(eid)
        for eid in target_node.get("evidence_chunk_ids", [])[:2]:
            if eid not in evidence_ids:
                evidence_ids.append(eid)

        link = {
            "edge_id": edge_id,
            "source_node_id": source_node["node_id"],
            "target_node_id": target_node["node_id"],
            "relation_type": relation_type,
            "layer": "implementation",  # Store in impl layer (schema-safe)
            "description": reason,
            "properties": {
                "semantic_layer": "cross_layer",
                "link_strategy": strategy,
                "confidence_reason": reason,
                "source_label": source_node["label"],
                "target_label": target_node["label"],
                "source_display_name": source_node["display_name"],
                "target_display_name": target_node["display_name"],
            },
            "source_ids": [],
            "evidence_chunk_ids": evidence_ids,
            "confidence": confidence,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        result.links.append(link)
        result.link_count_by_strategy[strategy] = (
            result.link_count_by_strategy.get(strategy, 0) + 1
        )
        result.link_count_by_relation[relation_type] = (
            result.link_count_by_relation.get(relation_type, 0) + 1
        )

    def _link_function_to_message(
        self,
        functions: list[dict],
        messages: list[dict],
        result: CrossLayerResult,
    ) -> None:
        """Link business Function → implementation Message by name match."""
        for func in functions:
            fn_name = func["display_name"]
            for msg in messages:
                msg_name = msg["display_name"]
                # Check if function name appears in message name
                # e.g., 発注一覧取得 in マッピングシート（発注一覧取得）
                if fn_name in msg_name:
                    self._add_link(
                        func, msg,
                        "RELATED_TO",
                        "exact_name_match",
                        0.9,
                        f"Function '{fn_name}' matches Message '{msg_name}'",
                        result,
                    )

    def _link_domain_to_system(
        self,
        domains: list[dict],
        systems: list[dict],
        result: CrossLayerResult,
    ) -> None:
        """Link BusinessDomain → System by domain content match."""
        # Domain 発注情報連携 and 納品情報連携 relate to all 3 systems
        for domain in domains:
            domain_name = domain["display_name"]
            for system in systems:
                sys_name = system["display_name"]
                # All domains in this project relate to SAP/中間F/Andpad integration
                if sys_name in ("SAP", "中間F", "Andpad"):
                    self._add_link(
                        domain, system,
                        "RELATED_TO",
                        "domain_system_match",
                        0.75,
                        f"Domain '{domain_name}' integrates with System '{sys_name}'",
                        result,
                    )

    def _link_term_to_impl(
        self,
        terms: list[dict],
        messages: list[dict],
        columns: list[dict],
        result: CrossLayerResult,
    ) -> None:
        """Link BusinessTerm → Message/Column by substring match."""
        # Only link meaningful terms (>2 chars, not too generic)
        generic_terms = {"発注", "納品", "ページ", "検収", "承認", "差戻", "取下", "編集中"}

        for term in terms:
            term_name = term["display_name"]
            if len(term_name) < 3 or term_name in generic_terms:
                continue

            # Check messages
            for msg in messages:
                msg_name = msg["display_name"]
                if term_name in msg_name and term_name != msg_name:
                    self._add_link(
                        term, msg,
                        "RELATED_TO",
                        "substring_match",
                        0.65,
                        f"Term '{term_name}' found in Message '{msg_name}'",
                        result,
                    )
                    break  # One match per term per message is enough

    def _link_rule_to_column_by_evidence(
        self,
        rules: list[dict],
        columns: list[dict],
        result: CrossLayerResult,
    ) -> None:
        """Link BusinessRule → Column by shared evidence chunks."""
        # Build column evidence lookup
        col_by_evidence: dict[str, list[dict]] = defaultdict(list)
        for col in columns:
            for eid in col.get("evidence_chunk_ids", []):
                col_by_evidence[eid].append(col)

        linked_rules = set()
        for rule in rules:
            rule_id = rule["node_id"]
            if rule_id in linked_rules:
                continue

            for eid in rule.get("evidence_chunk_ids", []):
                if eid in col_by_evidence:
                    # Found columns that share evidence with this rule
                    for col in col_by_evidence[eid][:3]:  # Cap per rule
                        self._add_link(
                            rule, col,
                            "VALIDATES",
                            "shared_evidence",
                            0.7,
                            f"Rule '{rule['display_name'][:40]}' shares evidence with Column '{col['display_name']}'",
                            result,
                        )
                    linked_rules.add(rule_id)
                    break
