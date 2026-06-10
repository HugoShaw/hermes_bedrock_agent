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
from .trace import GraphTrace, IsolationTrace

logger = logging.getLogger(__name__)

_SYSTEM_KEYWORDS = [
    "SAP", "S4/HANA", "S4HANA", "S/4HANA",
    "DataSpider", "ANDPAD",
    "中間F", "中間ファイル", "NTT DATA", "NTTDATA",
]
_API_PATTERN = re.compile(r"(GET|POST|PUT|DELETE|PATCH)\s+/\S+", re.IGNORECASE)

# Labels for "business-level" graph (high-level entities, processes, data flows)
_BUSINESS_LABELS = [
    "DataEntity", "BusinessProcess", "BusinessObject", "FieldGroup",
    "System", "ExternalSystem", "Middleware", "IntegrationTool",
    "FileObject", "ImplementationSpec", "Sheet",
]
# Labels for "implementation-level" graph (fields, rules, API operations)
_IMPLEMENTATION_LABELS = [
    "FieldDefinition", "Field", "BusinessRule", "EnumValue",
    "DefaultValueRule", "Parameter", "APIOperation", "APIEndpoint",
    "TransformationRule", "MappingDefinition", "MappingRule",
    "Interface", "SourceTable", "TargetTable", "SourceField", "TargetField",
    "Condition", "StatusField", "StatusValue", "Script",
]


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


def _extract_query_keywords(query: str) -> list[str]:
    """Extract meaningful Japanese/English keywords from a query for graph node name search.

    Extracts:
    - Backtick-quoted terms (e.g. `支払状況`)
    - Kanji compounds (2+ chars)
    - Mixed kanji+katakana (3+ chars)
    - Latin identifiers (4+ chars, excluding stop words)
    """
    keywords: list[str] = []

    # Backtick-quoted terms (highest priority — user explicitly marked them)
    for m in re.finditer(r"`([^`]+)`", query):
        t = m.group(1).strip()
        if t and t not in keywords:
            keywords.append(t)

    # Kanji compounds (2+ chars)
    for m in re.finditer(r"[\u4E00-\u9FFF]{2,}", query):
        t = m.group(0)
        if t not in keywords:
            keywords.append(t)

    # Mixed kanji+katakana (3+ chars)
    for m in re.finditer(r"[\u4E00-\u9FFF\u30A0-\u30FF]{3,}", query):
        t = m.group(0)
        if t not in keywords and len(t) >= 3:
            keywords.append(t)

    # Latin identifiers (4+ chars excluding stop words)
    _STOP = {"the", "and", "for", "from", "with", "that", "this", "are", "was",
             "how", "what", "where", "also", "which", "about", "into"}
    for m in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_.]{3,}\b", query):
        t = m.group(0)
        if t.lower() not in _STOP and t not in keywords:
            keywords.append(t)

    return keywords[:10]


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
    sys_query = (
        "MATCH (a)-[r]-(b) WHERE 'System' IN labels(a) AND 'System' IN labels(b)"
    )
    sys_params: dict = {}
    if project_id:
        sys_query += (
            " AND (a.project_name = $pid OR a.project_id = $pid"
            " OR b.project_name = $pid OR b.project_id = $pid)"
        )
        sys_params["pid"] = project_id
    sys_query += " RETURN a, type(r) AS rel, b LIMIT 30"
    try:
        rows = client.execute_query(sys_query, parameters=sys_params or None).get("results", [])
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
        sheet_name_list = [f"sheet_{str(i).zfill(2)}" for i in sheet_indices]
        b_params: dict = {"sheet_names": sheet_name_list}
        b_query = (
            "MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_name IN $sheet_names"
        )
        if project_id:
            b_query += " AND (s.project_name = $pid OR s.project_id = $pid)"
            b_params["pid"] = project_id
        b_query += (
            " AND ('System' IN labels(n) OR 'Sheet' IN labels(n) OR "
            "'BusinessProcess' IN labels(n) OR 'DataEntity' IN labels(n)) "
            "RETURN s, type(r) AS rel, n LIMIT 50"
        )
        try:
            rows = client.execute_query(b_query, parameters=b_params).get("results", [])
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
        try:
            c_query = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_name) "
                "AND 'System' IN labels(n) "
            )
            c_params = {"search_name": name}
            if project_id:
                c_query += "AND (n.project_id = $pid OR n.project_name = $pid) "
                c_params["pid"] = project_id
            c_query += (
                "WITH n LIMIT 3 MATCH (n)-[r]-(m) WHERE ('System' IN labels(m) OR "
                "'BusinessProcess' IN labels(m) OR 'DataEntity' IN labels(m)) "
                "RETURN n, type(r) AS rel, m LIMIT 20"
            )
            rows = client.execute_query(c_query, parameters=c_params).get("results", [])
            for row in rows:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                _add_node(n_nd)
                _add_node(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_edge(n_nd["id"], m_nd["id"], row.get("rel", ""))
        except Exception:
            continue

    # Strategy D: Query-keyword search for business-level nodes (DataEntity, BusinessProcess, etc.)
    # This handles experiment graphs that have no Sheet/System-to-System structure
    # but DO have DataEntity, BusinessProcess, FieldGroup, etc. as top-level "business" nodes.
    if not nodes:  # Only if strategies A-C found nothing
        bus_label_filter = " OR ".join(f"'{lbl}' IN labels(n)" for lbl in _BUSINESS_LABELS)
        keywords = _extract_query_keywords(query)
        for name in keywords[:6]:
            try:
                d_query = (
                    f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_name) "
                    f"AND ({bus_label_filter})"
                )
                d_params: dict = {"search_name": name}
                if project_id:
                    d_query += " AND n.project_id = $pid"
                    d_params["pid"] = project_id
                d_query += " WITH n LIMIT 5 MATCH (n)-[r]-(m) WHERE m.project_id = n.project_id RETURN n, type(r) AS rel, m LIMIT 20"
                rows = client.execute_query(d_query, parameters=d_params).get("results", [])
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
        sheet_name_list = [f"sheet_{str(i).zfill(2)}" for i in sheet_indices]
        ia_params: dict = {"sheet_names": sheet_name_list}
        ia_query = (
            "MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_name IN $sheet_names"
        )
        if project_id:
            ia_query += " AND (s.project_name = $pid OR s.project_id = $pid)"
            ia_params["pid"] = project_id
        ia_query += (
            " AND ('Interface' IN labels(n) OR 'Field' IN labels(n) OR "
            "'MappingDefinition' IN labels(n) OR 'BusinessRule' IN labels(n) OR "
            "'TransformationRule' IN labels(n) OR 'APIOperation' IN labels(n) OR "
            "'MappingRule' IN labels(n) OR 'SourceTable' IN labels(n) OR "
            "'TargetTable' IN labels(n) OR 'SourceField' IN labels(n) OR "
            "'TargetField' IN labels(n)) "
            "RETURN s, type(r) AS rel, n LIMIT 60"
        )
        try:
            rows = client.execute_query(ia_query, parameters=ia_params).get("results", [])
            for row in rows:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                _add_node(s_nd)
                _add_node(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_edge(s_nd["id"], n_nd["id"], row.get("rel", ""))
        except Exception as exc:
            logger.debug("Implementation graph Strategy A failed: %s", exc)

    # Strategy B: Entity-name search for implementation nodes (with project_id filter)
    chunk_texts = [c.content for c in chunks]
    if query:
        chunk_texts.append(query)
    impl_label_filter = (
        "('Interface' IN labels(n) OR 'Field' IN labels(n) OR "
        "'MappingDefinition' IN labels(n) OR 'BusinessRule' IN labels(n) OR "
        "'APIOperation' IN labels(n) OR 'TransformationRule' IN labels(n))"
    )
    for name in _extract_entity_names(chunk_texts)[:8]:
        try:
            ib_query = (
                f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_name) "
                f"AND {impl_label_filter}"
            )
            ib_params: dict = {"search_name": name}
            if project_id:
                ib_query += " AND n.project_id = $pid"
                ib_params["pid"] = project_id
            ib_query += " WITH n LIMIT 5 MATCH (n)-[r]-(m)"
            if project_id:
                ib_query += " WHERE m.project_id = $pid"
            ib_query += " RETURN n, type(r) AS rel, m LIMIT 30"
            rows = client.execute_query(ib_query, parameters=ib_params).get("results", [])
            for row in rows:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                _add_node(n_nd)
                _add_node(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_edge(n_nd["id"], m_nd["id"], row.get("rel", ""))
        except Exception:
            continue

    # Strategy C: Mapping/Business rules with relationships (with project_id filter)
    if any(c.chunk_type in ("mapping_table", "data_condition", "business_rule") for c in chunks):
        try:
            ic_query = (
                "MATCH (r)-[rel]-(c) "
                "WHERE ('MappingDefinition' IN labels(r) OR 'TransformationRule' IN labels(r)) "
                "AND ('BusinessRule' IN labels(c) OR 'Field' IN labels(c))"
            )
            ic_params: dict = {}
            if project_id:
                ic_query += " AND r.project_id = $pid AND c.project_id = $pid"
                ic_params["pid"] = project_id
            ic_query += " RETURN r, type(rel) AS rel_type, c LIMIT 20"
            rows = client.execute_query(ic_query, parameters=ic_params or None).get("results", [])
            for row in rows:
                r_nd = _node_from_row(row.get("r", {}))
                c_nd = _node_from_row(row.get("c", {}))
                _add_node(r_nd)
                _add_node(c_nd)
                if r_nd["id"] and c_nd["id"]:
                    _add_edge(r_nd["id"], c_nd["id"], row.get("rel_type", ""))
        except Exception as exc:
            logger.debug("Implementation graph Strategy C failed: %s", exc)

    # Strategy D: Query-keyword search for implementation-level nodes
    # Handles experiment graphs where Sheet nodes don't exist and system keywords
    # don't appear, but FieldDefinition/Field/BusinessRule/EnumValue nodes do.
    if not nodes:  # Only if strategies A-C found nothing
        impl_d_label_filter = " OR ".join(f"'{lbl}' IN labels(n)" for lbl in _IMPLEMENTATION_LABELS)
        keywords = _extract_query_keywords(query)
        for name in keywords[:6]:
            try:
                id_query = (
                    f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_name) "
                    f"AND ({impl_d_label_filter})"
                )
                id_params: dict = {"search_name": name}
                if project_id:
                    id_query += " AND n.project_id = $pid"
                    id_params["pid"] = project_id
                id_query += " WITH n LIMIT 5 MATCH (n)-[r]-(m)"
                if project_id:
                    id_query += " WHERE m.project_id = $pid"
                id_query += " RETURN n, type(r) AS rel, m LIMIT 20"
                rows = client.execute_query(id_query, parameters=id_params).get("results", [])
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


def _scan_edge_confidence(edges: list[dict]) -> tuple[dict, list[dict]]:
    """Scan edges for confidence/status properties.

    Returns (summary_dict, low_confidence_list).
    """
    summary = {"confirmed": 0, "candidate": 0, "possibly_related": 0,
               "needs_review": 0, "no_status": 0}
    low_confidence: list[dict] = []
    for edge in edges:
        props = edge.get("properties", {})
        status = props.get("status", props.get("confidence_status", "")).lower()
        if status in ("confirmed", "validated"):
            summary["confirmed"] += 1
        elif status == "candidate":
            summary["candidate"] += 1
            low_confidence.append(edge)
        elif status in ("possibly_related", "possible"):
            summary["possibly_related"] += 1
            low_confidence.append(edge)
        elif status in ("needs_review", "review"):
            summary["needs_review"] += 1
            low_confidence.append(edge)
        else:
            summary["no_status"] += 1
    return summary, low_confidence


def _check_isolation(
    dual: DualGraphContext,
    project_id: str,
    isolation_trace: Optional[IsolationTrace] = None,
) -> None:
    """Check nodes for project isolation violations."""
    if not project_id or isolation_trace is None:
        return
    isolation_trace.project_id = project_id
    all_nodes = dual.business.nodes + dual.implementation.nodes
    for node in all_nodes:
        props = node.get("properties", {})
        node_pid = props.get("project_id", "")
        node_pname = props.get("project_name", "")
        if not node_pid and not node_pname:
            isolation_trace.graph_nodes_without_project_id.append(
                {"id": node.get("id", ""), "label": node.get("label", "")}
            )
        elif node_pid and node_pid != project_id and node_pname != project_id:
            isolation_trace.cross_project_nodes.append(
                {"id": node.get("id", ""), "label": node.get("label", ""),
                 "project_id": node_pid}
            )
    isolation_trace.violations_count = len(isolation_trace.cross_project_nodes)


def fetch_dual_graph_context(
    chunks: list[RetrievedChunk],
    query: str = "",
    project_id: str = "",
    trace: Optional[GraphTrace] = None,
    isolation_trace: Optional[IsolationTrace] = None,
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

        if trace is not None:
            trace.business_nodes = len(dual.business.nodes)
            trace.business_edges = len(dual.business.edges)
            trace.implementation_nodes = len(dual.implementation.nodes)
            trace.implementation_edges = len(dual.implementation.edges)
            all_edges = dual.business.edges + dual.implementation.edges
            summary, low = _scan_edge_confidence(all_edges)
            trace.edge_confidence_summary = summary
            trace.low_confidence_edges = low

        if isolation_trace is not None:
            _check_isolation(dual, project_id, isolation_trace)

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
