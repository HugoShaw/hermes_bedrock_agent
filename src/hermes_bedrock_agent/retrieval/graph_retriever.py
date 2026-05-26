"""Graph context retrieval from Neptune Analytics.

Two-layer graph retrieval:
  1. Business Semantic Graph — high-level system architecture, data flows between
     systems, sheet-level relationships (the "what" and "why")
  2. Implementation Graph — field mappings, API calls, mapping rules, business
     rules, conditions (the "how")
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..knowledge_base.schemas import GraphContext, RetrievedChunk

logger = logging.getLogger(__name__)

_SYSTEM_KEYWORDS = [
    "SAP", "S4/HANA", "S4HANA", "S/4HANA",
    "DataSpider", "ANDPAD",
    "中間F", "中間ファイル", "NTT DATA", "NTTDATA",
]
_API_PATTERN = re.compile(r"(GET|POST|PUT|DELETE|PATCH)\s+/\S+", re.IGNORECASE)


def _extract_entity_names(texts: list[str]) -> list[str]:
    found: set[str] = set()
    combined = " ".join(texts)
    combined_lower = combined.lower()
    for kw in _SYSTEM_KEYWORDS:
        if kw.lower() in combined_lower:
            found.add(kw)
    for m in _API_PATTERN.finditer(combined):
        found.add(m.group(0).strip())
    return list(found)


def _node_from_row(node_data: dict) -> dict:
    nid = node_data.get("~id", node_data.get("node_id", ""))
    labels = node_data.get("~labels", [])
    label = labels[0] if labels else ""
    props = node_data.get("~properties", {})
    if not props:
        props = {k: v for k, v in node_data.items() if not k.startswith("~")}
    return {"id": nid, "label": label, "properties": props}


class DualGraphContext:
    """Container for two-layer graph retrieval results."""

    def __init__(self):
        self.business: GraphContext = GraphContext()
        self.implementation: GraphContext = GraphContext()

    @property
    def total_nodes(self) -> int:
        return len(self.business.nodes) + len(self.implementation.nodes)

    @property
    def total_edges(self) -> int:
        return len(self.business.edges) + len(self.implementation.edges)

    @property
    def is_empty(self) -> bool:
        return self.total_nodes == 0 and self.total_edges == 0

    def to_merged_context(self) -> GraphContext:
        """Merge both layers into a single GraphContext for backward compatibility."""
        return GraphContext(
            nodes=self.business.nodes + self.implementation.nodes,
            edges=self.business.edges + self.implementation.edges,
        )


def _fetch_business_graph(client, chunks: list[RetrievedChunk], query: str, project_id: str = "") -> GraphContext:
    """Layer 1: Business Semantic Graph — systems, data flows, sheet relationships."""
    seen_nodes: set[str] = set()
    seen_edges: set[tuple] = set()
    nodes: list[dict] = []
    edges: list[dict] = []
    pid_filter = f" AND n.project_id = '{project_id.replace(chr(39), chr(39)*2)}'" if project_id else ""
    pid_filter_a = f" AND a.project_id = '{project_id.replace(chr(39), chr(39)*2)}'" if project_id else ""

    def _add_node(nd: dict) -> None:
        nid = nd["id"]
        if nid and nid not in seen_nodes:
            seen_nodes.add(nid)
            nodes.append(nd)

    def _add_edge(from_id: str, to_id: str, rel: str, props: dict = None) -> None:
        key = (from_id, to_id, rel)
        if key not in seen_edges:
            seen_edges.add(key)
            edge = {"from": from_id, "to": to_id, "relationship": rel}
            if props:
                edge["properties"] = props
            edges.append(edge)

    # Strategy A: System-level data flows
    try:
        rows = client.execute_query(
            f"MATCH (a:System)-[r:FLOWS_TO]->(b:System) WHERE 1=1{pid_filter_a} RETURN a, type(r) AS rel, b LIMIT 30"
        ).get("results", [])
        for row in rows:
            a_nd = _node_from_row(row.get("a", {}))
            b_nd = _node_from_row(row.get("b", {}))
            _add_node(a_nd)
            _add_node(b_nd)
            if a_nd["id"] and b_nd["id"]:
                _add_edge(a_nd["id"], b_nd["id"], row.get("rel", "FLOWS_TO"))
    except Exception as exc:
        logger.debug("Business graph Strategy A failed: %s", exc)

    # Strategy B: Sheet-level neighbourhood (high-level structure)
    sheet_indices = list({c.sheet_index for c in chunks if c.sheet_index > 0})[:5]
    if sheet_indices:
        idx_list = ", ".join(str(i) for i in sheet_indices)
        pid_sheet = f" AND s.project_id = '{project_id.replace(chr(39), chr(39)*2)}'" if project_id else ""
        try:
            rows = client.execute_query(
                f"MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_index IN [{idx_list}]{pid_sheet} "
                f"AND (n:System OR n:DataFlow OR n:Sheet) "
                f"RETURN s, type(r) AS rel, n LIMIT 50"
            ).get("results", [])
            for row in rows:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                _add_node(s_nd)
                _add_node(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_edge(s_nd["id"], n_nd["id"], row.get("rel", ""))
        except Exception as exc:
            logger.debug("Business graph Strategy B failed: %s", exc)

    # Strategy C: Entity-name search (system-level only)
    chunk_texts = [c.content for c in chunks]
    if query:
        chunk_texts.append(query)
    for name in _extract_entity_names(chunk_texts)[:5]:
        safe = name.replace("'", "\\'")
        try:
            rows = client.execute_query(
                f"MATCH (n:System) WHERE toLower(n.name) CONTAINS toLower('{safe}'){pid_filter} "
                f"WITH n LIMIT 3 MATCH (n)-[r]-(m) WHERE m:System OR m:DataFlow "
                f"RETURN n, type(r) AS rel, m LIMIT 20"
            ).get("results", [])
            for row in rows:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                _add_node(n_nd)
                _add_node(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_edge(n_nd["id"], m_nd["id"], row.get("rel", ""))
        except Exception:
            continue

    return GraphContext(nodes=nodes[:60], edges=edges[:80])


def _fetch_implementation_graph(client, chunks: list[RetrievedChunk], query: str, project_id: str = "") -> GraphContext:
    """Layer 2: Implementation Graph — APIs, fields, mapping rules, business rules."""
    seen_nodes: set[str] = set()
    seen_edges: set[tuple] = set()
    nodes: list[dict] = []
    edges: list[dict] = []
    pid_filter = f" AND n.project_id = '{project_id.replace(chr(39), chr(39)*2)}'" if project_id else ""

    def _add_node(nd: dict) -> None:
        nid = nd["id"]
        if nid and nid not in seen_nodes:
            seen_nodes.add(nid)
            nodes.append(nd)

    def _add_edge(from_id: str, to_id: str, rel: str, props: dict = None) -> None:
        key = (from_id, to_id, rel)
        if key not in seen_edges:
            seen_edges.add(key)
            edge = {"from": from_id, "to": to_id, "relationship": rel}
            if props:
                edge["properties"] = props
            edges.append(edge)

    # Strategy A: Sheet→API, Sheet→Field, Sheet→Rule relationships
    sheet_indices = list({c.sheet_index for c in chunks if c.sheet_index > 0})[:5]
    if sheet_indices:
        idx_list = ", ".join(str(i) for i in sheet_indices)
        pid_sheet = f" AND s.project_id = '{project_id.replace(chr(39), chr(39)*2)}'" if project_id else ""
        try:
            rows = client.execute_query(
                f"MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_index IN [{idx_list}]{pid_sheet} "
                f"AND (n:API OR n:Field OR n:MappingRule OR n:BusinessRule) "
                f"RETURN s, type(r) AS rel, n LIMIT 60"
            ).get("results", [])
            for row in rows:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                _add_node(s_nd)
                _add_node(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_edge(s_nd["id"], n_nd["id"], row.get("rel", ""))
        except Exception as exc:
            logger.debug("Implementation graph Strategy A failed: %s", exc)

    # Strategy B: API / Field entity-name search
    chunk_texts = [c.content for c in chunks]
    if query:
        chunk_texts.append(query)
    for name in _extract_entity_names(chunk_texts)[:8]:
        safe = name.replace("'", "\\'")
        try:
            rows = client.execute_query(
                f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower('{safe}'){pid_filter} "
                f"AND (n:API OR n:Field OR n:MappingRule OR n:BusinessRule) "
                f"WITH n LIMIT 5 MATCH (n)-[r]-(m) RETURN n, type(r) AS rel, m LIMIT 30"
            ).get("results", [])
            for row in rows:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                _add_node(n_nd)
                _add_node(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_edge(n_nd["id"], m_nd["id"], row.get("rel", ""))
        except Exception:
            continue

    # Strategy C: Mapping rules with conditions
    if any(c.chunk_type in ("mapping_table", "data_condition", "business_rule") for c in chunks):
        pid_rule = f" AND r.project_id = '{project_id.replace(chr(39), chr(39)*2)}'" if project_id else ""
        try:
            rows = client.execute_query(
                f"MATCH (r:MappingRule)-[rel:HAS_CONDITION]->(c:BusinessRule) WHERE 1=1{pid_rule} "
                f"RETURN r, type(rel) AS rel_type, c LIMIT 20"
            ).get("results", [])
            for row in rows:
                r_nd = _node_from_row(row.get("r", {}))
                c_nd = _node_from_row(row.get("c", {}))
                _add_node(r_nd)
                _add_node(c_nd)
                if r_nd["id"] and c_nd["id"]:
                    _add_edge(r_nd["id"], c_nd["id"], row.get("rel_type", "HAS_CONDITION"))
        except Exception as exc:
            logger.debug("Implementation graph Strategy C failed: %s", exc)

    return GraphContext(nodes=nodes[:60], edges=edges[:80])


def fetch_dual_graph_context(
    chunks: list[RetrievedChunk],
    query: str = "",
    project_id: str = "",
) -> Optional[DualGraphContext]:
    """Retrieve two-layer graph context: business semantic + implementation."""
    try:
        from ..clients.neptune import NeptuneClient

        client = NeptuneClient()
        if not client.is_configured:
            return None

        dual = DualGraphContext()
        dual.business = _fetch_business_graph(client, chunks, query, project_id=project_id)
        dual.implementation = _fetch_implementation_graph(client, chunks, query, project_id=project_id)

        logger.info(
            "Dual graph context: business=%d nodes/%d edges, implementation=%d nodes/%d edges",
            len(dual.business.nodes), len(dual.business.edges),
            len(dual.implementation.nodes), len(dual.implementation.edges),
        )
        return dual

    except Exception as exc:
        logger.warning("Dual graph context fetch failed: %s", exc)
        return None


def fetch_graph_context(
    chunks: list[RetrievedChunk],
    query: str = "",
    project_id: str = "",
) -> Optional[GraphContext]:
    """Legacy single-layer graph retrieval — calls dual and merges."""
    dual = fetch_dual_graph_context(chunks, query, project_id=project_id)
    if dual is None:
        return None
    return dual.to_merged_context()
