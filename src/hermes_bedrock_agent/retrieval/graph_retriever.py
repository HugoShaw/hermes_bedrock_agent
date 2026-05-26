"""Graph context retrieval from Neptune Analytics."""

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


def fetch_graph_context(
    chunks: list[RetrievedChunk],
    query: str = "",
) -> Optional[GraphContext]:
    """Multi-strategy Neptune traversal: sheet expansion, entity search, data flows."""
    try:
        from ..clients.neptune import NeptuneClient

        client = NeptuneClient()
        if not client.is_configured:
            return None

        seen_nodes: set[str] = set()
        seen_edges: set[tuple] = set()
        nodes: list[dict] = []
        edges: list[dict] = []

        def _add_node(nd: dict) -> None:
            nid = nd["id"]
            if nid and nid not in seen_nodes:
                seen_nodes.add(nid)
                nodes.append(nd)

        def _add_edge(from_id: str, to_id: str, rel: str) -> None:
            key = (from_id, to_id, rel)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"from": from_id, "to": to_id, "relationship": rel})

        # Strategy A: Sheet-level neighbourhood
        sheet_indices = list({c.sheet_index for c in chunks if c.sheet_index > 0})[:5]
        if sheet_indices:
            idx_list = ", ".join(str(i) for i in sheet_indices)
            rows_a = client.execute_query(
                f"MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_index IN [{idx_list}] "
                f"RETURN s, type(r) AS rel, n LIMIT 80"
            ).get("results", [])
            for row in rows_a:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                rel = row.get("rel", "")
                _add_node(s_nd)
                _add_node(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_edge(s_nd["id"], n_nd["id"], rel)

        # Strategy B: Entity-name search
        chunk_texts = [c.content for c in chunks]
        if query:
            chunk_texts.append(query)
        for name in _extract_entity_names(chunk_texts)[:8]:
            safe = name.replace("'", "\\'")
            try:
                rows_b = client.execute_query(
                    f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower('{safe}') "
                    f"WITH n LIMIT 5 MATCH (n)-[r]-(m) RETURN n, type(r) AS rel, m LIMIT 30"
                ).get("results", [])
            except Exception:
                continue
            for row in rows_b:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                rel = row.get("rel", "")
                _add_node(n_nd)
                _add_node(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_edge(n_nd["id"], m_nd["id"], rel)

        # Strategy C: System data-flow paths
        try:
            rows_c = client.execute_query(
                "MATCH (a:System)-[r:FLOWS_TO]->(b:System) RETURN a, type(r) AS rel, b LIMIT 20"
            ).get("results", [])
        except Exception:
            rows_c = []
        for row in rows_c:
            a_nd = _node_from_row(row.get("a", {}))
            b_nd = _node_from_row(row.get("b", {}))
            rel = row.get("rel", "")
            _add_node(a_nd)
            _add_node(b_nd)
            if a_nd["id"] and b_nd["id"]:
                _add_edge(a_nd["id"], b_nd["id"], rel)

        return GraphContext(nodes=nodes[:100], edges=edges[:150])

    except Exception as exc:
        logger.warning("Graph context fetch failed: %s", exc)
        return None
