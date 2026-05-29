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
    """Layer 1: Business Semantic Graph — systems, data flows, sheet relationships.

    Adapted for new graph schema:
    - Sheet.sheet_name='sheet_05' (no sheet_index property)
    - System labels are multi: ['System', 'ExternalSystem']
    - Edge types: SENDS_TO, USES_SYSTEM, SYSTEM_HAS_INTERFACE (no FLOWS_TO)
    - Many nodes lack project_id (connected via Workbook/Project relationships)
    """
    seen_nodes: set[str] = set()
    seen_edges: set[tuple] = set()
    nodes: list[dict] = []
    edges: list[dict] = []

    if not project_id:
        logger.warning("_fetch_business_graph: no project_id — graph query may return cross-project data")

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

    # Strategy A: System-level relationships (project-scoped System-System edges)
    pid_esc_a = project_id.replace("'", "''") if project_id else ""
    sys_pf = ""
    if pid_esc_a:
        sys_pf = (
            f" AND (a.project_name = '{pid_esc_a}' OR a.project_id = '{pid_esc_a}'"
            f" OR b.project_name = '{pid_esc_a}' OR b.project_id = '{pid_esc_a}')"
        )
    try:
        rows = client.execute_query(
            "MATCH (a)-[r]-(b) WHERE 'System' IN labels(a) AND 'System' IN labels(b)"
            f"{sys_pf} "
            "RETURN a, type(r) AS rel, b LIMIT 30"
        ).get("results", [])
        for row in rows:
            a_nd = _node_from_row(row.get("a", {}))
            b_nd = _node_from_row(row.get("b", {}))
            _add_node(a_nd)
            _add_node(b_nd)
            if a_nd["id"] and b_nd["id"]:
                _add_edge(a_nd["id"], b_nd["id"], row.get("rel", ""))
    except Exception as exc:
        logger.debug("Business graph Strategy A failed: %s", exc)

    # Strategy B: Sheet-level neighbourhood (using sheet_name not sheet_index)
    sheet_indices = list({c.sheet_index for c in chunks if c.sheet_index > 0})[:5]
    if sheet_indices:
        sheet_names = ", ".join(f"'sheet_{str(i).zfill(2)}'" for i in sheet_indices)
        # Project filter: Sheet nodes use project_name (not project_id)
        pid_esc = project_id.replace("'", "''") if project_id else ""
        pf = f" AND (s.project_name = '{pid_esc}' OR s.project_id = '{pid_esc}')" if pid_esc else ""
        try:
            rows = client.execute_query(
                f"MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_name IN [{sheet_names}]"
                f"{pf} "
                f"AND ('System' IN labels(n) OR 'Sheet' IN labels(n) OR "
                f"'BusinessProcess' IN labels(n) OR 'DataEntity' IN labels(n)) "
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

    # Strategy C: Entity-name search for System nodes
    chunk_texts = [c.content for c in chunks]
    if query:
        chunk_texts.append(query)
    for name in _extract_entity_names(chunk_texts)[:5]:
        safe = name.replace("'", "''")
        try:
            rows = client.execute_query(
                f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower('{safe}') "
                f"AND 'System' IN labels(n) "
                f"WITH n LIMIT 3 MATCH (n)-[r]-(m) WHERE ('System' IN labels(m) OR "
                f"'BusinessProcess' IN labels(m) OR 'DataEntity' IN labels(m)) "
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
    """Layer 2: Implementation Graph — APIs, fields, mapping rules, business rules.

    Adapted for new graph schema:
    - Sheet.sheet_name='sheet_05' (no sheet_index property)
    - Uses multi-label nodes: Interface, APIOperation, Field, MappingDefinition, etc.
    - Many nodes lack project_id (connected via relationships)
    """
    seen_nodes: set[str] = set()
    seen_edges: set[tuple] = set()
    nodes: list[dict] = []
    edges: list[dict] = []

    if not project_id:
        logger.warning("_fetch_implementation_graph: no project_id — graph query may return cross-project data")

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

    # Strategy A: Sheet→Implementation nodes (using sheet_name not sheet_index)
    sheet_indices = list({c.sheet_index for c in chunks if c.sheet_index > 0})[:5]
    if sheet_indices:
        sheet_names = ", ".join(f"'sheet_{str(i).zfill(2)}'" for i in sheet_indices)
        # Project filter: Sheet nodes use project_name (not project_id)
        pid_esc = project_id.replace("'", "''") if project_id else ""
        pf = f" AND (s.project_name = '{pid_esc}' OR s.project_id = '{pid_esc}')" if pid_esc else ""
        try:
            rows = client.execute_query(
                f"MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_name IN [{sheet_names}]"
                f"{pf} "
                f"AND ('Interface' IN labels(n) OR 'Field' IN labels(n) OR "
                f"'MappingDefinition' IN labels(n) OR 'BusinessRule' IN labels(n) OR "
                f"'TransformationRule' IN labels(n) OR 'APIOperation' IN labels(n) OR "
                f"'MappingRule' IN labels(n) OR 'SourceTable' IN labels(n) OR "
                f"'TargetTable' IN labels(n) OR 'SourceField' IN labels(n) OR "
                f"'TargetField' IN labels(n)) "
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

    # Strategy B: Entity-name search for implementation nodes
    chunk_texts = [c.content for c in chunks]
    if query:
        chunk_texts.append(query)
    for name in _extract_entity_names(chunk_texts)[:8]:
        safe = name.replace("'", "''")
        try:
            rows = client.execute_query(
                f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower('{safe}') "
                f"AND ('Interface' IN labels(n) OR 'Field' IN labels(n) OR "
                f"'MappingDefinition' IN labels(n) OR 'BusinessRule' IN labels(n) OR "
                f"'APIOperation' IN labels(n) OR 'TransformationRule' IN labels(n)) "
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

    # Strategy C: Mapping/Business rules with relationships
    if any(c.chunk_type in ("mapping_table", "data_condition", "business_rule") for c in chunks):
        try:
            rows = client.execute_query(
                "MATCH (r)-[rel]-(c) "
                "WHERE ('MappingDefinition' IN labels(r) OR 'TransformationRule' IN labels(r)) "
                "AND ('BusinessRule' IN labels(c) OR 'Field' IN labels(c)) "
                "RETURN r, type(rel) AS rel_type, c LIMIT 20"
            ).get("results", [])
            for row in rows:
                r_nd = _node_from_row(row.get("r", {}))
                c_nd = _node_from_row(row.get("c", {}))
                _add_node(r_nd)
                _add_node(c_nd)
                if r_nd["id"] and c_nd["id"]:
                    _add_edge(r_nd["id"], c_nd["id"], row.get("rel_type", ""))
        except Exception as exc:
            logger.debug("Implementation graph Strategy C failed: %s", exc)

    return GraphContext(nodes=nodes[:60], edges=edges[:80])


def fetch_dual_graph_context(
    chunks: list[RetrievedChunk],
    query: str = "",
    project_id: str = "",
) -> Optional[DualGraphContext]:
    """Retrieve two-layer graph context: business semantic + implementation.
    
    WARNING: If project_id is empty, graph queries will traverse ALL projects.
    """
    try:
        from ..clients.neptune import NeptuneClient

        client = NeptuneClient()
        if not client.is_configured:
            return None

        if not project_id:
            logger.warning(
                "fetch_dual_graph_context: no project_id — graph retrieval may return cross-project data"
            )

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
