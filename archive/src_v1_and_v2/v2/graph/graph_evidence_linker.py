"""
Graph Evidence Linker for Stage 08.

Creates explicit post-hoc evidence links between filtered graph nodes/edges
and evidence chunks using multiple strategies:
1. Existing evidence_chunk_ids (primary)
2. Source ID matching
3. Alias / name match (conservative)
4. Edge endpoint evidence propagation
5. Section/document fallback

Outputs:
- evidence_links.jsonl (normalized link records)
- graph_nodes_linked.jsonl (enriched nodes)
- graph_edges_linked.jsonl (enriched edges)
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any


# Maximum evidence links per graph item
MAX_EVIDENCE_LINKS_PER_NODE = 10
MAX_EVIDENCE_LINKS_PER_EDGE = 10


def _generate_link_id(graph_item_id: str, evidence_chunk_id: str, strategy: str) -> str:
    """Generate deterministic link_id from graph_item_id + evidence_chunk_id + strategy."""
    raw = f"{graph_item_id}|{evidence_chunk_id}|{strategy}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_text(text: str) -> str:
    """Normalize text for matching: lowercase, strip, NFKC."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_journal_base_dump(chunk: dict) -> bool:
    """Check if a chunk is from JOURNAL_BASE20180530.SQL INSERT dump."""
    sp = (chunk.get("source_path") or "").lower()
    did = (chunk.get("document_id") or "").lower()
    ct = chunk.get("chunk_type", "")
    # The actual dump file
    if "journal_base20180530" in sp or "journal_base20180530" in did:
        if ct == "sql" or "insert" in (chunk.get("title") or "").lower():
            return True
    return False


class GraphEvidenceLinker:
    """Links graph nodes/edges to evidence chunks."""

    def __init__(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        documents: list[dict[str, Any]] | None = None,
        sections: list[dict[str, Any]] | None = None,
        aliases: list[dict[str, Any]] | None = None,
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
    ):
        self.nodes = nodes
        self.edges = edges
        self.chunks = chunks
        self.documents = documents or []
        self.sections = sections or []
        self.aliases = aliases or []
        self.run_id = run_id
        self.dataset = dataset

        # Outputs
        self.evidence_links: list[dict[str, Any]] = []
        self.linked_nodes: list[dict[str, Any]] = []
        self.linked_edges: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {}

        # Indexes (built during link())
        self._chunk_by_id: dict[str, dict] = {}
        self._chunks_by_doc_id: dict[str, list[str]] = defaultdict(list)
        self._chunks_by_source_path: dict[str, list[str]] = defaultdict(list)
        self._chunks_by_section_id: dict[str, list[str]] = defaultdict(list)
        self._doc_summary_chunks: dict[str, list[str]] = defaultdict(list)
        self._section_summary_chunks: dict[str, list[str]] = defaultdict(list)
        self._node_by_id: dict[str, dict] = {}

    def _build_indexes(self) -> None:
        """Build lookup indexes for efficient evidence matching."""
        # Chunk indexes
        for c in self.chunks:
            cid = c.get("chunk_id", "")
            self._chunk_by_id[cid] = c

            doc_id = c.get("document_id", "")
            if doc_id:
                self._chunks_by_doc_id[doc_id].append(cid)

            sp = c.get("source_path", "")
            if sp:
                self._chunks_by_source_path[sp].append(cid)

            sec_id = c.get("section_id")
            if sec_id:
                self._chunks_by_section_id[sec_id].append(cid)

            # Track summary-type chunks for fallback
            ct = c.get("chunk_type", "")
            if ct == "summary" and doc_id:
                self._doc_summary_chunks[doc_id].append(cid)
            elif ct == "section" and sec_id:
                self._section_summary_chunks[sec_id].append(cid)

        # Node index
        for n in self.nodes:
            self._node_by_id[n["node_id"]] = n

    def _create_link(
        self,
        graph_item_id: str,
        graph_item_type: str,
        graph_layer: str,
        graph_label_or_relation: str,
        evidence_chunk_id: str,
        strategy: str,
        confidence: float,
        reason: str,
    ) -> dict[str, Any]:
        """Create a single evidence link record."""
        chunk = self._chunk_by_id.get(evidence_chunk_id, {})
        return {
            "link_id": _generate_link_id(graph_item_id, evidence_chunk_id, strategy),
            "graph_item_id": graph_item_id,
            "graph_item_type": graph_item_type,
            "graph_layer": graph_layer,
            "graph_label_or_relation": graph_label_or_relation,
            "evidence_chunk_id": evidence_chunk_id,
            "document_id": chunk.get("document_id", ""),
            "section_id": chunk.get("section_id", ""),
            "source_path": chunk.get("source_path", ""),
            "link_strategy": strategy,
            "confidence": confidence,
            "reason": reason,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }

    def _link_by_existing(
        self, item_id: str, item_type: str, layer: str, label_or_rel: str,
        evidence_chunk_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Strategy 1: Link using existing evidence_chunk_ids."""
        links = []
        for eid in evidence_chunk_ids:
            if eid in self._chunk_by_id:
                # Skip JOURNAL_BASE dump chunks
                if _is_journal_base_dump(self._chunk_by_id[eid]):
                    continue
                links.append(self._create_link(
                    item_id, item_type, layer, label_or_rel, eid,
                    strategy="existing",
                    confidence=1.0,
                    reason="Pre-existing evidence_chunk_id from extraction",
                ))
        return links

    def _link_by_source_match(
        self, item_id: str, item_type: str, layer: str, label_or_rel: str,
        source_ids: list[str], existing_eids: set[str],
    ) -> list[dict[str, Any]]:
        """Strategy 2: Link using source_ids to find matching chunks."""
        links = []
        for sid in source_ids:
            # Try as document_id
            for cid in self._chunks_by_doc_id.get(sid, []):
                if cid in existing_eids:
                    continue
                chunk = self._chunk_by_id.get(cid, {})
                if _is_journal_base_dump(chunk):
                    continue
                # Prefer summary chunks from source matching
                ct = chunk.get("chunk_type", "")
                if ct == "summary":
                    links.append(self._create_link(
                        item_id, item_type, layer, label_or_rel, cid,
                        strategy="source_match",
                        confidence=0.9,
                        reason=f"source_id={sid} matched document_id, chunk_type=summary",
                    ))
            # Try as source_path
            for cid in self._chunks_by_source_path.get(sid, []):
                if cid in existing_eids:
                    continue
                chunk = self._chunk_by_id.get(cid, {})
                if _is_journal_base_dump(chunk):
                    continue
                ct = chunk.get("chunk_type", "")
                if ct == "summary":
                    links.append(self._create_link(
                        item_id, item_type, layer, label_or_rel, cid,
                        strategy="source_match",
                        confidence=0.9,
                        reason=f"source_id={sid} matched source_path, chunk_type=summary",
                    ))
        return links

    def _link_by_endpoint_propagation(
        self, edge: dict[str, Any], existing_eids: set[str],
    ) -> list[dict[str, Any]]:
        """Strategy 4: Edge endpoint evidence propagation."""
        links = []
        src_node = self._node_by_id.get(edge.get("source_node_id", ""), {})
        tgt_node = self._node_by_id.get(edge.get("target_node_id", ""), {})

        src_evidence = set(src_node.get("evidence_chunk_ids", []))
        tgt_evidence = set(tgt_node.get("evidence_chunk_ids", []))

        # Find overlapping evidence
        overlap = src_evidence & tgt_evidence - existing_eids
        for cid in list(overlap)[:3]:
            chunk = self._chunk_by_id.get(cid, {})
            if _is_journal_base_dump(chunk):
                continue
            links.append(self._create_link(
                edge["edge_id"], "edge", edge["layer"], edge["relation_type"], cid,
                strategy="endpoint_propagation",
                confidence=0.5,
                reason="Shared evidence between source and target nodes",
            ))

        # If no overlap, take top from source node
        if not overlap:
            for cid in list(src_evidence - existing_eids)[:2]:
                chunk = self._chunk_by_id.get(cid, {})
                if _is_journal_base_dump(chunk):
                    continue
                links.append(self._create_link(
                    edge["edge_id"], "edge", edge["layer"], edge["relation_type"], cid,
                    strategy="endpoint_propagation",
                    confidence=0.4,
                    reason="Propagated from source node evidence",
                ))

        return links

    def _link_by_document_fallback(
        self, item_id: str, item_type: str, layer: str, label_or_rel: str,
        source_ids: list[str], existing_eids: set[str],
    ) -> list[dict[str, Any]]:
        """Strategy 5: Section/document summary fallback."""
        links = []
        for sid in source_ids:
            # Try document summary chunks
            for cid in self._doc_summary_chunks.get(sid, []):
                if cid in existing_eids:
                    continue
                chunk = self._chunk_by_id.get(cid, {})
                if _is_journal_base_dump(chunk):
                    continue
                links.append(self._create_link(
                    item_id, item_type, layer, label_or_rel, cid,
                    strategy="document_fallback",
                    confidence=0.4,
                    reason=f"Document summary fallback from source_id={sid}",
                ))
                break  # One per source
        return links

    def _compute_evidence_quality(self, links: list[dict[str, Any]]) -> float:
        """Compute evidence quality score from links."""
        if not links:
            return 0.0
        # Take the highest confidence link as the quality score
        return max(l["confidence"] for l in links)

    def _compute_warnings(self, links: list[dict[str, Any]], item: dict) -> list[str]:
        """Compute evidence warnings for a graph item."""
        warnings = []
        if not links:
            warnings.append("no_evidence_links")
            return warnings

        strategies = {l["link_strategy"] for l in links}
        if strategies == {"document_fallback"} or strategies == {"section_fallback"}:
            warnings.append("fallback_only_evidence")
        if strategies == {"endpoint_propagation"}:
            warnings.append("propagation_only_evidence")

        # Check if isolated and weak evidence
        if item.get("properties", {}).get("is_isolated") and max(l["confidence"] for l in links) < 0.7:
            warnings.append("isolated_node_weak_evidence")

        return warnings

    def link(self) -> dict[str, Any]:
        """Execute full evidence linking pipeline."""
        self._build_indexes()

        all_links: list[dict[str, Any]] = []
        strategy_counter = Counter()
        nodes_no_evidence = 0
        edges_no_evidence = 0

        # ======================================================================
        # Link nodes
        # ======================================================================
        self.linked_nodes = []
        for node in self.nodes:
            node_id = node["node_id"]
            layer = node["layer"]
            label = node["label"]
            evidence_ids = node.get("evidence_chunk_ids", [])
            source_ids = node.get("source_ids", [])

            node_links: list[dict[str, Any]] = []

            # Strategy 1: existing evidence
            s1_links = self._link_by_existing(node_id, "node", layer, label, evidence_ids)
            node_links.extend(s1_links)

            existing_eids = {l["evidence_chunk_id"] for l in node_links}

            # Strategy 2: source match (if we have room)
            if len(node_links) < MAX_EVIDENCE_LINKS_PER_NODE:
                s2_links = self._link_by_source_match(
                    node_id, "node", layer, label, source_ids, existing_eids
                )
                node_links.extend(s2_links[:MAX_EVIDENCE_LINKS_PER_NODE - len(node_links)])

            existing_eids = {l["evidence_chunk_id"] for l in node_links}

            # Strategy 5: document fallback (only if no links yet)
            if not node_links:
                s5_links = self._link_by_document_fallback(
                    node_id, "node", layer, label, source_ids, existing_eids
                )
                node_links.extend(s5_links[:MAX_EVIDENCE_LINKS_PER_NODE])

            # Cap at max
            node_links = node_links[:MAX_EVIDENCE_LINKS_PER_NODE]

            # Update strategy counter
            for l in node_links:
                strategy_counter[l["link_strategy"]] += 1

            # Enrich node
            enriched = dict(node)
            link_ids = [l["link_id"] for l in node_links]
            enriched_eids = list(dict.fromkeys(
                l["evidence_chunk_id"] for l in node_links
            ))
            enriched["properties"] = dict(enriched.get("properties", {}))
            enriched["evidence_chunk_ids"] = enriched_eids
            enriched["properties"]["evidence_link_ids"] = link_ids
            enriched["properties"]["evidence_count"] = len(node_links)
            enriched["properties"]["evidence_link_strategies"] = sorted(set(
                l["link_strategy"] for l in node_links
            ))
            enriched["properties"]["primary_evidence_chunk_id"] = (
                enriched_eids[0] if enriched_eids else None
            )
            enriched["properties"]["evidence_quality_score"] = self._compute_evidence_quality(node_links)
            warnings = self._compute_warnings(node_links, node)
            if warnings:
                enriched["properties"]["evidence_warnings"] = warnings

            self.linked_nodes.append(enriched)
            all_links.extend(node_links)

            if not node_links:
                nodes_no_evidence += 1

        # ======================================================================
        # Link edges
        # ======================================================================
        self.linked_edges = []
        for edge in self.edges:
            edge_id = edge["edge_id"]
            layer = edge["layer"]
            rel_type = edge["relation_type"]
            evidence_ids = edge.get("evidence_chunk_ids", [])
            source_ids = edge.get("source_ids", [])

            edge_links: list[dict[str, Any]] = []

            # Strategy 1: existing evidence
            s1_links = self._link_by_existing(edge_id, "edge", layer, rel_type, evidence_ids)
            edge_links.extend(s1_links)

            existing_eids = {l["evidence_chunk_id"] for l in edge_links}

            # Strategy 2: source match
            if len(edge_links) < MAX_EVIDENCE_LINKS_PER_EDGE:
                s2_links = self._link_by_source_match(
                    edge_id, "edge", layer, rel_type, source_ids, existing_eids
                )
                edge_links.extend(s2_links[:MAX_EVIDENCE_LINKS_PER_EDGE - len(edge_links)])

            existing_eids = {l["evidence_chunk_id"] for l in edge_links}

            # Strategy 4: endpoint propagation (if we have room and weak evidence)
            if len(edge_links) < MAX_EVIDENCE_LINKS_PER_EDGE:
                s4_links = self._link_by_endpoint_propagation(edge, existing_eids)
                edge_links.extend(s4_links[:MAX_EVIDENCE_LINKS_PER_EDGE - len(edge_links)])

            # Strategy 5: document fallback (only if no links yet)
            if not edge_links:
                s5_links = self._link_by_document_fallback(
                    edge_id, "edge", layer, rel_type, source_ids, existing_eids
                )
                edge_links.extend(s5_links[:MAX_EVIDENCE_LINKS_PER_EDGE])

            # Cap at max
            edge_links = edge_links[:MAX_EVIDENCE_LINKS_PER_EDGE]

            # Update strategy counter
            for l in edge_links:
                strategy_counter[l["link_strategy"]] += 1

            # Enrich edge
            enriched = dict(edge)
            link_ids = [l["link_id"] for l in edge_links]
            enriched_eids = list(dict.fromkeys(
                l["evidence_chunk_id"] for l in edge_links
            ))
            enriched["properties"] = dict(enriched.get("properties", {}))
            enriched["evidence_chunk_ids"] = enriched_eids
            enriched["properties"]["evidence_link_ids"] = link_ids
            enriched["properties"]["evidence_count"] = len(edge_links)
            enriched["properties"]["evidence_link_strategies"] = sorted(set(
                l["link_strategy"] for l in edge_links
            ))
            enriched["properties"]["primary_evidence_chunk_id"] = (
                enriched_eids[0] if enriched_eids else None
            )
            enriched["properties"]["evidence_quality_score"] = self._compute_evidence_quality(edge_links)
            warnings = self._compute_warnings(edge_links, edge)
            if warnings:
                enriched["properties"]["evidence_warnings"] = warnings

            self.linked_edges.append(enriched)
            all_links.extend(edge_links)

            if not edge_links:
                edges_no_evidence += 1

        # Deduplicate links (same link_id = same link)
        seen_link_ids = set()
        deduped_links = []
        for l in all_links:
            if l["link_id"] not in seen_link_ids:
                seen_link_ids.add(l["link_id"])
                deduped_links.append(l)

        self.evidence_links = deduped_links

        # Compute stats
        self.stats = {
            "input_nodes": len(self.nodes),
            "input_edges": len(self.edges),
            "evidence_chunk_count": len(self.chunks),
            "linked_nodes": len(self.linked_nodes),
            "linked_edges": len(self.linked_edges),
            "evidence_link_count": len(self.evidence_links),
            "link_count_by_strategy": dict(strategy_counter.most_common()),
            "nodes_with_evidence": len(self.linked_nodes) - nodes_no_evidence,
            "edges_with_evidence": len(self.linked_edges) - edges_no_evidence,
            "nodes_no_evidence": nodes_no_evidence,
            "edges_no_evidence": edges_no_evidence,
            "node_evidence_ratio": (len(self.linked_nodes) - nodes_no_evidence) / max(len(self.linked_nodes), 1),
            "edge_evidence_ratio": (len(self.linked_edges) - edges_no_evidence) / max(len(self.linked_edges), 1),
            "avg_evidence_per_node": sum(
                n.get("properties", {}).get("evidence_count", 0) for n in self.linked_nodes
            ) / max(len(self.linked_nodes), 1),
            "avg_evidence_per_edge": sum(
                e.get("properties", {}).get("evidence_count", 0) for e in self.linked_edges
            ) / max(len(self.linked_edges), 1),
            "quality_score_distribution": self._compute_quality_distribution(),
            "journal_base_links": sum(
                1 for l in self.evidence_links
                if "journal_base20180530" in (l.get("source_path") or "").lower()
            ),
            "sql_dump_links": sum(
                1 for l in self.evidence_links
                if _is_journal_base_dump(self._chunk_by_id.get(l["evidence_chunk_id"], {}))
            ),
            "api_node_count": sum(
                1 for n in self.linked_nodes if n.get("label") == "API"
            ),
            "isolated_nodes_weak": sum(
                1 for n in self.linked_nodes
                if "isolated_node_weak_evidence" in n.get("properties", {}).get("evidence_warnings", [])
            ),
            "fallback_only_nodes": sum(
                1 for n in self.linked_nodes
                if "fallback_only_evidence" in n.get("properties", {}).get("evidence_warnings", [])
            ),
            "fallback_only_edges": sum(
                1 for e in self.linked_edges
                if "fallback_only_evidence" in e.get("properties", {}).get("evidence_warnings", [])
            ),
        }

        return self.stats

    def _compute_quality_distribution(self) -> dict[str, int]:
        """Compute evidence quality score distribution."""
        dist = Counter()
        for n in self.linked_nodes:
            score = n.get("properties", {}).get("evidence_quality_score", 0.0)
            if score >= 1.0:
                dist["1.0 (direct)"] += 1
            elif score >= 0.9:
                dist["0.9 (source_match)"] += 1
            elif score >= 0.7:
                dist["0.7-0.8 (alias)"] += 1
            elif score >= 0.5:
                dist["0.5-0.6 (propagation)"] += 1
            elif score >= 0.3:
                dist["0.3-0.4 (fallback)"] += 1
            else:
                dist["0.0 (none)"] += 1
        for e in self.linked_edges:
            score = e.get("properties", {}).get("evidence_quality_score", 0.0)
            if score >= 1.0:
                dist["1.0 (direct)"] += 1
            elif score >= 0.9:
                dist["0.9 (source_match)"] += 1
            elif score >= 0.7:
                dist["0.7-0.8 (alias)"] += 1
            elif score >= 0.5:
                dist["0.5-0.6 (propagation)"] += 1
            elif score >= 0.3:
                dist["0.3-0.4 (fallback)"] += 1
            else:
                dist["0.0 (none)"] += 1
        return dict(dist.most_common())
