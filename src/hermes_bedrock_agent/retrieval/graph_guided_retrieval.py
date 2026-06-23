"""Graph-guided vector retrieval — use Neptune subgraph to constrain LanceDB search."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import RetrievedChunk
from .graph_retriever import DualGraphContext, _extract_entity_names, _node_from_row, _scan_edge_confidence
from .trace import RetrievalTrace, Timer, VectorTrace

logger = logging.getLogger(__name__)


def _safe_str(val: object) -> str:
    """Convert a pandas/dict value to a clean string, handling NaN/None/float safely."""
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
        return str(val)
    s = str(val).strip()
    if s in ("nan", "None", "null"):
        return ""
    return s


# Chunk types that indicate high-level architectural content — useful as fallback
_STRUCTURAL_CHUNK_TYPES = [
    "overview", "flowchart", "cross_sheet_summary",
    "mapping_table", "data_condition", "business_rule", "api_spec",
]

# Additional query-keyword → chunk_type hints
_CHUNK_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["api", "endpoint", "http", "get ", "post ", "put ", "delete "], "api_spec"),
    (["mapping", "マッピング", "変換", "transform"], "mapping_table"),
    (["condition", "条件", "rule", "ルール", "business rule"], "business_rule"),
    (["flow", "フロー", "sequence", "シーケンス"], "flowchart"),
    (["overview", "概要", "summary", "サマリ"], "overview"),
]

# Maximum fraction of total sheets that hints can cover before being considered "weak"
_MAX_SHEET_FRACTION = 0.5
# Absolute maximum sheets before hints are considered over-broad
_MAX_HINT_SHEETS = 10


@dataclass
class GraphGuidanceHints:
    relevant_sheet_indices: list[int] = field(default_factory=list)
    relevant_systems: list[str] = field(default_factory=list)
    relevant_chunk_types: list[str] = field(default_factory=list)
    query_entities: list[str] = field(default_factory=list)
    graph_context: Optional[DualGraphContext] = None
    # Quality indicator: "strong", "weak", or "none"
    quality: str = "none"


def _infer_chunk_types_from_query(query: str) -> list[str]:
    """Heuristically infer relevant chunk types from keyword presence in the query."""
    q_lower = query.lower()
    found: list[str] = []
    for keywords, ctype in _CHUNK_TYPE_KEYWORDS:
        if any(kw in q_lower for kw in keywords):
            found.append(ctype)
    return found


def _extract_query_terms(query: str) -> list[str]:
    """Extract meaningful search terms from a query — broader than _extract_entity_names.

    Extracts:
    - Known system keywords (via _extract_entity_names)
    - UPPER_CASE identifiers (field names, table names)
    - CamelCase words (API names, class names)
    - Katakana words (Japanese system/concept names)
    - Latin words >= 3 chars that aren't common stop words
    """
    terms: list[str] = []

    # Known system keywords first
    terms.extend(_extract_entity_names([query]))

    # UPPER_CASE or UPPER_UNDERSCORE patterns (e.g. COMPANY_CODE, SAP_ID)
    for m in re.finditer(r"\b[A-Z][A-Z0-9_]{2,}\b", query):
        t = m.group(0)
        if t not in terms:
            terms.append(t)

    # CamelCase (e.g. DataSpider, PurchaseOrder)
    for m in re.finditer(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", query):
        t = m.group(0)
        if t not in terms:
            terms.append(t)

    # Katakana words (マッピング, データ, etc.) — 2+ chars
    for m in re.finditer(r"[\u30A0-\u30FF]{2,}", query):
        t = m.group(0)
        if t not in terms:
            terms.append(t)

    # Kanji compound words (仕入先, 伝票, 処理, etc.) — 2+ chars
    # These are common in Japanese enterprise documents as node names
    for m in re.finditer(r"[\u4E00-\u9FFF]{2,}", query):
        t = m.group(0)
        if t not in terms:
            terms.append(t)

    # Mixed kanji+katakana terms (e.g. 債務奉行クラウド, 仕入先データ)
    for m in re.finditer(r"[\u4E00-\u9FFF\u30A0-\u30FF]{3,}", query):
        t = m.group(0)
        if t not in terms and len(t) >= 3:
            terms.append(t)

    # Latin words 3+ chars that are not stop words
    _STOP = {"the", "and", "for", "from", "with", "that", "this", "are", "was", "how", "what", "where"}
    for m in re.finditer(r"\b[A-Za-z]{3,}\b", query):
        t = m.group(0)
        if t.lower() not in _STOP and t not in terms and t.lower() not in [x.lower() for x in terms]:
            terms.append(t)

    return terms[:12]


def _extract_sheet_index_from_name(sheet_name: str) -> Optional[int]:
    """Extract numeric index from sheet_name like 'sheet_05' → 5."""
    m = re.match(r"sheet_(\d+)", sheet_name or "")
    if m:
        return int(m.group(1))
    return None


def _build_project_filter(project_id: str) -> tuple[str, str]:
    """Build Neptune filter clause that matches both project_id and project_name.

    The new graph uses:
      - project_id (e.g. 'sample_20260519')
      - project_name (e.g. 'サンプル20260519')
    We match on both to handle the mapping.

    Returns parameterized filter clauses using $pid parameter.
    Caller must include {"pid": project_id} in the parameters dict.
    """
    if not project_id:
        return "", ""
    filter_clause = " AND (n.project_id = $pid OR n.project_name = $pid)"
    filter_clause_s = " AND (s.project_id = $pid OR s.project_name = $pid)"
    return filter_clause, filter_clause_s


def _evaluate_hint_quality(
    hints: GraphGuidanceHints,
    total_sheets: Optional[int] = None,
) -> str:
    """Evaluate graph guidance quality: 'strong', 'weak', or 'none'.

    Strong: hints return a focused sheet set (<= _MAX_HINT_SHEETS and, if
        total_sheets is known, < 50% of total)
    Weak: hints exist but cover too many sheets (over-expansion)
    None: no graph hints found at all
    """
    if not hints.relevant_sheet_indices:
        return "none"

    n_sheets = len(hints.relevant_sheet_indices)

    # Check absolute threshold
    if n_sheets > _MAX_HINT_SHEETS:
        return "weak"

    # Check fraction threshold only when total_sheets is known
    if total_sheets and total_sheets > 0 and n_sheets / total_sheets > _MAX_SHEET_FRACTION:
        return "weak"

    return "strong"


def explore_graph_for_query(query: str, project_id: str = "") -> GraphGuidanceHints:
    """Query Neptune to find relevant subgraph nodes and return retrieval hints.

    Strategy:
    A. Extract broad query terms (system keywords, identifiers, katakana, etc.)
    B. Find matching nodes in Neptune (name CONTAINS search)
    C. Expand 1-hop to find connected Sheet nodes → sheet_indices
    D. Collect connected System node names → relevant_systems
    E. Infer chunk_types from query keywords
    F. Evaluate hint quality (strong/weak/none)

    Adapts to the graph schema where:
    - Sheet nodes have sheet_name='sheet_05' (not sheet_index)
    - project_id and project_name may differ (e.g. 'sample_20260519' vs 'サンプル20260519')
    - Some nodes have no project_id (connected via Workbook/Project relationships)
    """
    hints = GraphGuidanceHints()
    hints.relevant_chunk_types = _infer_chunk_types_from_query(query)

    try:
        from ..clients.neptune import NeptuneClient
        client = NeptuneClient()
        if not client.is_configured:
            logger.debug("Neptune not configured — skipping graph exploration")
            return hints
    except Exception as exc:
        logger.debug("Neptune client init failed: %s", exc)
        return hints

    # Build project filters that match both project_id and project_name
    pid_n, pid_s = _build_project_filter(project_id)

    # Broader term extraction (system keywords + identifiers + katakana + nouns)
    query_terms = _extract_query_terms(query)
    hints.query_entities = query_terms

    if not query_terms:
        logger.debug("No query terms extracted — graph guidance hints will be minimal")
        return hints

    found_node_ids: list[str] = []

    # Step A+B: Find nodes matching query terms (project_id filter when available;
    # without filter for production graphs where many nodes lack project_id)
    for name in query_terms[:8]:
        try:
            exp_query = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_name) "
            )
            exp_params = {"search_name": name}
            if project_id:
                exp_query += "AND (n.project_id = $pid OR n.project_name = $pid) "
                exp_params["pid"] = project_id
            exp_query += "RETURN n LIMIT 10"
            rows = client.execute_query(
                exp_query, parameters=exp_params,
            ).get("results", [])
            for row in rows:
                nd = _node_from_row(row.get("n", {}))
                if nd["id"]:
                    found_node_ids.append(nd["id"])
        except Exception as exc:
            logger.debug("Graph exploration entity search failed for '%s': %s", name, exc)

    if not found_node_ids:
        logger.debug("Graph exploration found no matching nodes for query terms")
        return hints

    # Deduplicate node ids for the IN clause
    unique_ids = list(dict.fromkeys(found_node_ids))[:20]

    # Step C: Expand to connected Sheet nodes → sheet_indices
    # New graph: Sheet.sheet_name = 'sheet_05' (extract index from this)
    try:
        rows = client.execute_query(
            "MATCH (n)-[r]-(s:Sheet) WHERE id(n) IN $node_ids "
            "RETURN DISTINCT s.sheet_name AS sheet_name, s.name AS name, "
            "s.project_name AS pname, s.project_id AS pid LIMIT 30",
            parameters={"node_ids": unique_ids},
        ).get("results", [])
        for row in rows:
            if project_id:
                rpid = row.get("pid") or ""
                rpname = row.get("pname") or ""
                if project_id not in (rpid, rpname):
                    continue
            idx = _extract_sheet_index_from_name(row.get("sheet_name", ""))
            if idx is not None and idx not in hints.relevant_sheet_indices:
                hints.relevant_sheet_indices.append(idx)
    except Exception as exc:
        logger.debug("Graph exploration sheet expansion failed: %s", exc)

    # Also find sheets via Workbook path (new graph has Workbook→Sheet edges)
    if not hints.relevant_sheet_indices:
        try:
            rows = client.execute_query(
                "MATCH (n)-[*1..2]-(s:Sheet) WHERE id(n) IN $node_ids "
                "RETURN DISTINCT s.sheet_name AS sheet_name, s.name AS name, "
                "s.project_name AS pname, s.project_id AS pid LIMIT 30",
                parameters={"node_ids": unique_ids},
            ).get("results", [])
            for row in rows:
                if project_id:
                    rpid = row.get("pid") or ""
                    rpname = row.get("pname") or ""
                    if project_id not in (rpid, rpname):
                        continue
                idx = _extract_sheet_index_from_name(row.get("sheet_name", ""))
                if idx is not None and idx not in hints.relevant_sheet_indices:
                    hints.relevant_sheet_indices.append(idx)
        except Exception as exc:
            logger.debug("Graph exploration 2-hop sheet expansion failed: %s", exc)

    # Step D: Find connected System nodes → system names
    try:
        sys_exp_query = (
            "MATCH (n)-[r]-(sys) WHERE id(n) IN $node_ids "
            "AND 'System' IN labels(sys) "
        )
        sys_exp_params = {"node_ids": unique_ids}
        if project_id:
            sys_exp_query += "AND (sys.project_id = $pid OR sys.project_name = $pid) "
            sys_exp_params["pid"] = project_id
        sys_exp_query += "RETURN DISTINCT sys.name AS system_name LIMIT 10"
        rows = client.execute_query(
            sys_exp_query, parameters=sys_exp_params,
        ).get("results", [])
        for row in rows:
            sname = row.get("system_name")
            if sname and sname not in hints.relevant_systems:
                hints.relevant_systems.append(str(sname))
    except Exception as exc:
        logger.debug("Graph exploration system expansion failed: %s", exc)

    # Also include System nodes matched directly (from known keywords)
    entity_names = _extract_entity_names([query])
    for name in entity_names:
        if name not in hints.relevant_systems:
            hints.relevant_systems.append(name)

    # Step F: Evaluate hint quality
    estimated_total = max(hints.relevant_sheet_indices) if hints.relevant_sheet_indices else None
    hints.quality = _evaluate_hint_quality(hints, total_sheets=estimated_total)

    logger.info(
        "Graph exploration hints: sheets=%s systems=%s chunk_types=%s entities=%s quality=%s",
        hints.relevant_sheet_indices,
        hints.relevant_systems,
        hints.relevant_chunk_types,
        hints.query_entities,
        hints.quality,
    )
    return hints


def _build_dual_graph_from_hints(
    client,
    hints: GraphGuidanceHints,
    query: str,
    project_id: str,
) -> DualGraphContext:
    """Build a DualGraphContext from graph guidance hints.

    Adapted for new graph schema:
    - Sheets have sheet_name='sheet_05' (no sheet_index property)
    - System labels are multi: ['System', 'ExternalSystem']
    - Edge types: SENDS_TO, USES_SYSTEM, SYSTEM_HAS_INTERFACE, SHEET_DESCRIBES_MAPPING
    - Many nodes have no project_id (connected via relationships)
    """
    from ..knowledge_base.schemas import GraphContext

    dual = DualGraphContext()
    if not hints.relevant_sheet_indices and not hints.relevant_systems:
        return dual

    bus_nodes: list[dict] = []
    bus_edges: list[dict] = []
    impl_nodes: list[dict] = []
    impl_edges: list[dict] = []
    seen_b: set = set()
    seen_i: set = set()

    def _add_b(nd: dict) -> None:
        if nd["id"] and nd["id"] not in seen_b:
            seen_b.add(nd["id"])
            bus_nodes.append(nd)

    def _add_b_edge(f: str, t: str, rel: str) -> None:
        if (f, t, rel) not in seen_b:
            seen_b.add((f, t, rel))
            bus_edges.append({"from": f, "to": t, "relationship": rel})

    def _add_i(nd: dict) -> None:
        if nd["id"] and nd["id"] not in seen_i:
            seen_i.add(nd["id"])
            impl_nodes.append(nd)

    def _add_i_edge(f: str, t: str, rel: str) -> None:
        if (f, t, rel) not in seen_i:
            seen_i.add((f, t, rel))
            impl_edges.append({"from": f, "to": t, "relationship": rel})

    # Build sheet_name filter list
    sheet_name_list = [f"sheet_{str(i).zfill(2)}" for i in hints.relevant_sheet_indices[:10]]

    # Business: System-level relationships (SENDS_TO, USES_SYSTEM, SYSTEM_HAS_INTERFACE)
    try:
        sys_query = (
            "MATCH (a)-[r]-(b) "
            "WHERE 'System' IN labels(a) AND 'System' IN labels(b)"
        )
        sys_params: dict = {}
        if project_id:
            sys_query += (
                " AND (a.project_name = $pid OR a.project_id = $pid"
                " OR b.project_name = $pid OR b.project_id = $pid)"
            )
            sys_params["pid"] = project_id
        sys_query += " RETURN a, type(r) AS rel, b LIMIT 30"
        rows = client.execute_query(sys_query, parameters=sys_params or None).get("results", [])
        for row in rows:
            a_nd = _node_from_row(row.get("a", {}))
            b_nd = _node_from_row(row.get("b", {}))
            _add_b(a_nd)
            _add_b(b_nd)
            if a_nd["id"] and b_nd["id"]:
                _add_b_edge(a_nd["id"], b_nd["id"], row.get("rel", ""))
    except Exception as exc:
        logger.debug("Graph context system-system query failed: %s", exc)

    # Business: sheet neighbourhood for discovered sheets
    if sheet_name_list:
        try:
            bus_sheet_query = (
                "MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_name IN $sheet_names"
            )
            bus_sheet_params: dict = {"sheet_names": sheet_name_list}
            if project_id:
                bus_sheet_query += " AND (s.project_name = $pid OR s.project_id = $pid)"
                bus_sheet_params["pid"] = project_id
            bus_sheet_query += (
                " AND ('System' IN labels(n) OR 'Sheet' IN labels(n) OR "
                "'BusinessProcess' IN labels(n) OR 'DataEntity' IN labels(n)) "
                "RETURN s, type(r) AS rel, n LIMIT 50"
            )
            rows = client.execute_query(bus_sheet_query, parameters=bus_sheet_params).get("results", [])
            for row in rows:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                _add_b(s_nd)
                _add_b(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_b_edge(s_nd["id"], n_nd["id"], row.get("rel", ""))
        except Exception as exc:
            logger.debug("Graph context sheet neighbourhood failed: %s", exc)

    # Implementation: sheet → implementation details (API, Field, MappingRule, etc.)
    if sheet_name_list:
        try:
            impl_sheet_query = (
                "MATCH (s:Sheet)-[r]-(n) WHERE s.sheet_name IN $sheet_names"
            )
            impl_sheet_params: dict = {"sheet_names": sheet_name_list}
            if project_id:
                impl_sheet_query += " AND (s.project_name = $pid OR s.project_id = $pid)"
                impl_sheet_params["pid"] = project_id
            impl_sheet_query += (
                " AND ('Interface' IN labels(n) OR 'Field' IN labels(n) OR "
                "'MappingDefinition' IN labels(n) OR 'BusinessRule' IN labels(n) OR "
                "'TransformationRule' IN labels(n) OR 'APIOperation' IN labels(n) OR "
                "'MappingRule' IN labels(n) OR 'SourceTable' IN labels(n) OR "
                "'TargetTable' IN labels(n) OR 'SourceField' IN labels(n) OR "
                "'TargetField' IN labels(n)) "
                "RETURN s, type(r) AS rel, n LIMIT 60"
            )
            rows = client.execute_query(impl_sheet_query, parameters=impl_sheet_params).get("results", [])
            for row in rows:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                _add_i(s_nd)
                _add_i(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_i_edge(s_nd["id"], n_nd["id"], row.get("rel", ""))
        except Exception as exc:
            logger.debug("Graph context implementation sheet query failed: %s", exc)

    # Implementation: entity-name search for detailed nodes (with project_id filter)
    for name in hints.query_entities[:5]:
        try:
            impl_ent_query = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_name) "
                "AND ('Interface' IN labels(n) OR 'Field' IN labels(n) OR "
                "'MappingDefinition' IN labels(n) OR 'BusinessRule' IN labels(n) OR "
                "'APIOperation' IN labels(n) OR 'TransformationRule' IN labels(n))"
            )
            impl_ent_params: dict = {"search_name": name}
            if project_id:
                impl_ent_query += " AND n.project_id = $pid"
                impl_ent_params["pid"] = project_id
            impl_ent_query += " WITH n LIMIT 5 MATCH (n)-[r]-(m)"
            if project_id:
                impl_ent_query += " WHERE m.project_id = $pid"
            impl_ent_query += " RETURN n, type(r) AS rel, m LIMIT 20"
            rows = client.execute_query(impl_ent_query, parameters=impl_ent_params).get("results", [])
            for row in rows:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                _add_i(n_nd)
                _add_i(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_i_edge(n_nd["id"], m_nd["id"], row.get("rel", ""))
        except Exception:
            continue

    from ..knowledge_base.schemas import GraphContext
    dual.business = GraphContext(nodes=bus_nodes[:60], edges=bus_edges[:80])
    dual.implementation = GraphContext(nodes=impl_nodes[:60], edges=impl_edges[:80])
    return dual


def _rows_to_retrieved_chunks(raw_results: list[dict], fallback_project_id: str) -> list[RetrievedChunk]:
    chunks: list[RetrievedChunk] = []
    for row in raw_results:
        distance = row.get("_distance", 0.0)
        score = 1.0 / (1.0 + distance)
        # parsed_markdown_path may not exist in LanceDB; fall back to source_markdown_file
        parsed_md = _safe_str(row.get("parsed_markdown_path", "")) or _safe_str(row.get("source_markdown_file", ""))
        chunks.append(RetrievedChunk(
            chunk_id=_safe_str(row.get("id", "")),
            content=_safe_str(row.get("text", "")),
            chunk_type=_safe_str(row.get("chunk_type", "")),
            sheet_index=row.get("sheet_index", 0),
            sheet_name=_safe_str(row.get("sheet_name", "")),
            score=round(score, 4),
            source_pdf_s3_path=_safe_str(row.get("source_pdf_s3_path", "")),
            source_excel_s3_path=_safe_str(row.get("source_excel_s3_path", "")),
            project_id=_safe_str(row.get("project_id", "")) or fallback_project_id,
            parsed_markdown_path=parsed_md,
            document_id=_safe_str(row.get("document_id", "")),
            document_name=_safe_str(row.get("document_name", "")),
            document_type=_safe_str(row.get("document_type", "")),
            source_markdown_file=_safe_str(row.get("source_markdown_file", "")),
            evidence_path=_safe_str(row.get("evidence_path", "")),
            evidence_paths=_safe_str(row.get("evidence_paths", "")),
            source_file=_safe_str(row.get("source_file", "")),
            source_type=_safe_str(row.get("source_type", "")),
            parser_type=_safe_str(row.get("parser_type", "")),
        ))
    return chunks


def _row_to_chunk_from_keyword(row: dict, fallback_project_id: str) -> RetrievedChunk:
    """Convert a keyword search result row to RetrievedChunk with full provenance."""
    score = row.get("_keyword_score", 0.0)
    # parsed_markdown_path may not exist in LanceDB; fall back to source_markdown_file
    parsed_md = _safe_str(row.get("parsed_markdown_path", "")) or _safe_str(row.get("source_markdown_file", ""))
    return RetrievedChunk(
        chunk_id=_safe_str(row.get("id", "")),
        content=_safe_str(row.get("text", "")),
        chunk_type=_safe_str(row.get("chunk_type", "")),
        sheet_index=row.get("sheet_index", 0),
        sheet_name=_safe_str(row.get("sheet_name", "")),
        score=round(score, 4),
        source_pdf_s3_path=_safe_str(row.get("source_pdf_s3_path", "")),
        source_excel_s3_path=_safe_str(row.get("source_excel_s3_path", "")),
        project_id=_safe_str(row.get("project_id", "")) or fallback_project_id,
        parsed_markdown_path=parsed_md,
        document_id=_safe_str(row.get("document_id", "")),
        document_name=_safe_str(row.get("document_name", "")),
        document_type=_safe_str(row.get("document_type", "")),
        source_markdown_file=_safe_str(row.get("source_markdown_file", "")),
        evidence_path=_safe_str(row.get("evidence_path", "")),
        evidence_paths=_safe_str(row.get("evidence_paths", "")),
        source_file=_safe_str(row.get("source_file", "")),
        source_type=_safe_str(row.get("source_type", "")),
        parser_type=_safe_str(row.get("parser_type", "")),
    )


def _keyword_boost_chunks(
    chunks: list[RetrievedChunk],
    query: str,
    trace: Optional[VectorTrace] = None,
) -> list[RetrievedChunk]:
    """Apply a small score boost to chunks that contain exact query substrings.

    This helps exact-text or keyword-heavy queries surface the right chunks
    even if vector similarity doesn't perfectly rank them.
    """
    if not query or not chunks:
        return chunks

    # Extract meaningful substrings to match (3+ chars for kanji, 4+ for latin)
    keywords: list[str] = []
    # Full query as-is (for exact pasting)
    if len(query) >= 6:
        keywords.append(query)
    # Kanji sequences (2+ chars)
    for m in re.finditer(r"[\u4E00-\u9FFF]{2,}", query):
        keywords.append(m.group(0))
    # Katakana sequences (2+ chars)
    for m in re.finditer(r"[\u30A0-\u30FF]{2,}", query):
        keywords.append(m.group(0))
    # Mixed kanji+katakana (3+ chars)
    for m in re.finditer(r"[\u4E00-\u9FFF\u30A0-\u30FF]{3,}", query):
        t = m.group(0)
        if t not in keywords:
            keywords.append(t)
    # Latin identifiers (4+ chars)
    for m in re.finditer(r"\b[A-Za-z]{4,}\b", query):
        keywords.append(m.group(0))

    if not keywords:
        return chunks

    boosted: list[RetrievedChunk] = []
    for chunk in chunks:
        content_lower = chunk.content.lower()
        matches = sum(1 for kw in keywords if kw.lower() in content_lower)
        if matches > 0:
            boost = min(0.08, matches * 0.02)
            new_score = min(1.0, chunk.score + boost)
            boosted.append(chunk.model_copy(update={"score": round(new_score, 4)}))
            if trace is not None:
                matched_kws = [kw for kw in keywords if kw.lower() in content_lower]
                trace.keyword_boost_applied.append({
                    "chunk_id": chunk.chunk_id,
                    "boost": round(boost, 4),
                    "keywords_matched": matched_kws[:5],
                })
        else:
            boosted.append(chunk)

    return sorted(boosted, key=lambda c: c.score, reverse=True)


def retrieve_with_graph_guidance(
    query: str,
    top_k: int = 5,
    project_id: str = "",
    cfg: Optional[Config] = None,
    trace: Optional[RetrievalTrace] = None,
    disable_keyword_boost: bool = False,
) -> tuple[list[RetrievedChunk], Optional[DualGraphContext], str]:
    """Graph-guided retrieval pipeline.

    Returns:
        (chunks, dual_graph_context, guidance_status)

    guidance_status is one of:
        "strong" — graph hints focused, used for vector filtering
        "weak"   — graph hints over-broad, used only for context (not filtering)
        "none"   — no graph hints, pure vector retrieval
        "error"  — graph exploration failed, fell back to vector retrieval

    Pipeline:
    1. explore_graph_for_query() → GraphGuidanceHints
    2. Evaluate hint quality (strong/weak/none)
    3. If strong: sheet-filtered LanceDB query + standard query, merge & deduplicate
       If weak:  standard vector query only (graph used only for LLM context)
       If none:  standard vector query only
    4. Apply keyword boost to help exact-text queries
    5. Build DualGraphContext from hints (or from chunks if no hints)
    6. Return (merged_chunks, dual_graph_context, guidance_status)
    """
    from .graph_retriever import fetch_dual_graph_context
    from .vector_retriever import retrieve_chunks
    from .query_preprocessing import normalize_query, detect_intent, rewrite_queries
    from .keyword_retriever import keyword_search
    from ..knowledge_base.vector_store import query_vector_store

    cfg = cfg or _default_config

    # Hybrid preprocessing: normalize, detect intent, rewrite queries
    normalized = normalize_query(query)
    intent = detect_intent(normalized)
    rewritten = rewrite_queries(normalized, intent)

    if trace is not None:
        trace.hybrid.normalized_query = normalized
        trace.hybrid.intent_label = intent.label
        trace.hybrid.intent_confidence = intent.confidence
        trace.hybrid.business_query = rewritten.business_query
        trace.hybrid.technical_query = rewritten.technical_query
        trace.hybrid.keyword_query = rewritten.keyword_query

    # Step 1: Graph exploration (uses ORIGINAL query for entity matching)
    try:
        with Timer() as graph_explore_timer:
            hints = explore_graph_for_query(query, project_id=project_id)
    except Exception as exc:
        logger.warning("Graph exploration failed entirely: %s", exc)
        hints = GraphGuidanceHints()
        hints.quality = "none"
        graph_explore_timer = Timer()

    if trace is not None:
        trace.timing.graph_exploration_ms = graph_explore_timer.elapsed_ms
        trace.graph.query_terms = list(hints.query_entities)
        trace.graph.sheet_expansion = list(hints.relevant_sheet_indices)
        trace.graph.system_expansion = list(hints.relevant_systems)
        trace.graph.hint_quality = hints.quality
        if hints.quality == "weak":
            sheet_count = len(hints.relevant_sheet_indices)
            trace.graph.hint_quality_reason = "over-broad: {} sheets".format(sheet_count)
        elif hints.quality == "none":
            trace.graph.hint_quality_reason = "no graph nodes matched query terms"
        else:
            trace.graph.hint_quality_reason = "focused sheet filter"

    # Step 2: Evaluate hint quality
    guidance_status = hints.quality

    # Step 3: Vector retrieval strategy based on hint quality
    # Uses NORMALIZED query for better embedding similarity
    if guidance_status == "strong":
        logger.info(
            "Graph-guided retrieval: STRONG hints — sheets=%s systems=%s",
            hints.relevant_sheet_indices, hints.relevant_systems,
        )
        try:
            with Timer() as vec_timer:
                filtered_raw = query_vector_store(
                    query_text=normalized,
                    cfg=cfg,
                    top_k=top_k,
                    project_id=project_id,
                    sheet_filter=hints.relevant_sheet_indices,
                    trace=trace.vector if trace else None,
                )
            guided_chunks = _rows_to_retrieved_chunks(filtered_raw, project_id)
        except Exception as exc:
            logger.warning("Graph-guided filtered query failed, using standard only: %s", exc)
            guided_chunks = []
            vec_timer = Timer()

        with Timer() as std_timer:
            standard_chunks = retrieve_chunks(query=normalized, top_k=top_k, cfg=cfg, project_id=project_id)
        chunks = _merge_chunks(guided_chunks, standard_chunks, guided_boost=0.05)
        if trace is not None:
            trace.timing.vector_search_ms = vec_timer.elapsed_ms + std_timer.elapsed_ms

    elif guidance_status == "weak":
        logger.info(
            "Graph-guided retrieval: WEAK hints (over-broad %d sheets) — "
            "using standard vector retrieval, graph for context only",
            len(hints.relevant_sheet_indices),
        )
        with Timer() as vec_timer:
            chunks = retrieve_chunks(
                query=normalized, top_k=top_k, cfg=cfg, project_id=project_id,
                trace=trace.vector if trace else None,
            )
        if trace is not None:
            trace.timing.vector_search_ms = vec_timer.elapsed_ms

    else:
        logger.info("No graph hints available — using standard vector retrieval")
        with Timer() as vec_timer:
            chunks = retrieve_chunks(
                query=normalized, top_k=top_k, cfg=cfg, project_id=project_id,
                trace=trace.vector if trace else None,
            )
        if trace is not None:
            trace.timing.vector_search_ms = vec_timer.elapsed_ms

    # Step 3b: Keyword retrieval and merge
    with Timer() as kw_timer:
        keyword_raw = keyword_search(
            query=rewritten.keyword_query,
            top_k=top_k * 2,
            project_id=project_id,
            cfg=cfg,
        )
        keyword_chunks = [
            _row_to_chunk_from_keyword(row, project_id)
            for row in keyword_raw
        ]

    if trace is not None:
        trace.hybrid.keyword_hits_count = len(keyword_chunks)

    # Merge keyword results into vector results
    if keyword_chunks:
        seen_ids = {c.chunk_id for c in chunks}
        dedup_removed = 0
        for kw_chunk in keyword_chunks:
            kw_score = kw_chunk.score * 0.9
            if kw_chunk.chunk_id in seen_ids:
                dedup_removed += 1
                existing = next((c for c in chunks if c.chunk_id == kw_chunk.chunk_id), None)
                if existing and kw_score > existing.score:
                    chunks = [
                        kw_chunk.model_copy(update={"score": round(kw_score, 4)})
                        if c.chunk_id == kw_chunk.chunk_id else c
                        for c in chunks
                    ]
            else:
                chunks.append(kw_chunk.model_copy(update={"score": round(kw_score, 4)}))
                seen_ids.add(kw_chunk.chunk_id)
        chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        if trace is not None:
            trace.hybrid.dedup_removed = dedup_removed

    # Step 4: Keyword boost — helps exact-text and keyword-heavy queries
    with Timer() as boost_timer:
        if not disable_keyword_boost:
            chunks = _keyword_boost_chunks(chunks, query, trace=trace.vector if trace else None)
        elif trace is not None:
            trace.vector.keyword_boost_skipped = True
    if trace is not None:
        trace.timing.merge_boost_ms = boost_timer.elapsed_ms + kw_timer.elapsed_ms

    # Step 4a: Graph expansion — entity extraction + Neptune expansion + LanceDB join
    from .entity_extractor import extract_entities
    from .graph_expansion import expand_graph, resolve_graph_candidates_to_chunks

    graph_exp_trace = trace.graph_expansion if trace else None
    if graph_exp_trace:
        graph_exp_trace.enabled = True
        graph_exp_trace.candidates_before_graph = len(chunks)

    try:
        entities = extract_entities(
            original_query=query,
            rewritten_queries=[rewritten.business_query, rewritten.technical_query, rewritten.keyword_query],
            top_chunks=chunks[:5],
        )

        if graph_exp_trace:
            graph_exp_trace.entities_extracted = [
                {"text": e.text, "type": e.entity_type, "source": e.source, "confidence": e.confidence}
                for e in entities
            ]

        initial_chunk_ids = {c.chunk_id for c in chunks}

        graph_expansion_result = expand_graph(
            entities=entities,
            intent_label=intent.label,
            project_id=project_id,
            initial_chunk_ids=initial_chunk_ids,
            cfg=cfg,
        )

        if graph_exp_trace:
            graph_exp_trace.neptune_available = graph_expansion_result.neptune_available
            graph_exp_trace.relation_allowlist = graph_expansion_result.relation_allowlist_used
            graph_exp_trace.expansion_hops = graph_expansion_result.expansion_hops
            graph_exp_trace.graph_nodes_matched = len(graph_expansion_result.graph_nodes_matched)
            graph_exp_trace.graph_paths = graph_expansion_result.graph_paths
            graph_exp_trace.graph_candidates_count = len(graph_expansion_result.candidates)
            if graph_expansion_result.error:
                graph_exp_trace.error = graph_expansion_result.error

        if graph_expansion_result.neptune_available and graph_expansion_result.candidates:
            resolved = resolve_graph_candidates_to_chunks(
                graph_result=graph_expansion_result,
                project_id=project_id,
                initial_chunk_ids=initial_chunk_ids,
                cfg=cfg,
            )

            new_count = 0
            dup_count = 0
            join_methods: dict[str, int] = {}
            for gc in resolved:
                jm = gc.join_method
                join_methods[jm] = join_methods.get(jm, 0) + 1
                if gc.chunk_id and gc.chunk_id not in initial_chunk_ids:
                    if not gc.already_in_initial:
                        chunk = RetrievedChunk(
                            chunk_id=gc.chunk_id,
                            content=gc.content,
                            score=gc.score,
                            chunk_type=gc.chunk_type,
                            sheet_index=0,
                            sheet_name=gc.sheet_name,
                            project_id=gc.project_id,
                            document_id=gc.document_id,
                            document_name=gc.document_name,
                            document_type=gc.document_type,
                            source_markdown_file=gc.source_markdown_file,
                            evidence_path=gc.evidence_path,
                            evidence_paths=str(gc.evidence_paths) if gc.evidence_paths else "",
                            source_file=gc.source_file,
                            source_type=gc.source_type,
                            parser_type=gc.parser_type,
                            # Evidence resolution fields from LanceDB (required for load_evidence_images)
                            source_pdf_s3_path=gc.source_pdf_s3_path,
                            source_excel_s3_path=gc.source_excel_s3_path,
                            parsed_markdown_path=gc.parsed_markdown_path,
                        )
                        chunks.append(chunk)
                        initial_chunk_ids.add(gc.chunk_id)
                        new_count += 1
                    else:
                        dup_count += 1
                else:
                    dup_count += 1

            if graph_exp_trace:
                graph_exp_trace.graph_candidates_resolved = len(resolved)
                graph_exp_trace.graph_candidates_new = new_count
                graph_exp_trace.graph_candidates_duplicate = dup_count
                graph_exp_trace.join_methods_used = join_methods
                graph_exp_trace.candidates = [
                    {
                        "chunk_id": gc.chunk_id or "",
                        "graph_node_name": gc.graph_node_name,
                        "graph_node_type": gc.graph_node_type,
                        "join_method": gc.join_method,
                        "join_confidence": gc.join_confidence,
                        "already_in_initial": gc.already_in_initial,
                        "document_name": gc.document_name,
                    }
                    for gc in resolved
                ]

            chunks = sorted(chunks, key=lambda c: c.score, reverse=True)

    except Exception as exc:
        logger.warning("Graph expansion failed (non-fatal): %s", exc)
        if graph_exp_trace:
            graph_exp_trace.error = str(exc)

    if graph_exp_trace:
        graph_exp_trace.candidates_after_graph = len(chunks)

    # Step 4b: Optional reranking (after keyword boost, before graph context build)
    from .reranker import load_rerank_config, rerank_chunks
    from .trace import RerankTrace, Timer as _Timer
    rerank_cfg = load_rerank_config()
    if rerank_cfg.enabled and chunks:
        chunks_before_rerank = list(chunks)
        with _Timer() as rerank_timer:
            rerank_result = rerank_chunks(
                query=query, chunks=chunks, rerank_cfg=rerank_cfg, cfg=cfg,
            )
        chunks = rerank_result.chunks
        if trace is not None:
            trace.rerank.enabled = True
            trace.rerank.model_id = rerank_cfg.model_id
            trace.rerank.candidate_count = len(chunks_before_rerank)
            trace.rerank.final_count = len(rerank_result.chunks)
            trace.rerank.reranked = rerank_result.reranked
            trace.rerank.error = rerank_result.error
            trace.rerank.latency_ms = rerank_timer.elapsed_ms
            pre_order = {cid: rank for rank, cid in enumerate(rerank_result.original_order, 1)}
            for post_rank, chunk in enumerate(rerank_result.chunks, 1):
                trace.rerank.rank_comparison.append({
                    "chunk_id": chunk.chunk_id,
                    "document_name": chunk.document_name,
                    "chunk_type": chunk.chunk_type,
                    "hybrid_rank": pre_order.get(chunk.chunk_id, 0),
                    "rerank_rank": post_rank,
                    "hybrid_score": round(chunks_before_rerank[pre_order.get(chunk.chunk_id, 1) - 1].score, 4) if pre_order.get(chunk.chunk_id) else 0.0,
                    "rerank_score": rerank_result.rerank_scores.get(chunk.chunk_id, 0.0),
                })

    # Track graph candidates that survived reranking
    if trace and trace.graph_expansion.graph_candidates_new > 0 and rerank_cfg.enabled:
        graph_chunk_ids = {
            c["chunk_id"] for c in trace.graph_expansion.candidates
            if not c["already_in_initial"] and c["chunk_id"]
        }
        survived = sum(1 for c in chunks if c.chunk_id in graph_chunk_ids)
        trace.graph_expansion.graph_candidates_survived_rerank = survived

    if not chunks:
        return [], None, guidance_status

    # Step 5: Build graph context (for LLM, even when hints are weak)
    dual_graph: Optional[DualGraphContext] = None
    with Timer() as ctx_timer:
        if hints.graph_context is not None:
            dual_graph = hints.graph_context
        elif hints.relevant_sheet_indices or hints.relevant_systems:
            try:
                from ..clients.neptune import NeptuneClient
                client = NeptuneClient()
                if client.is_configured:
                    dual_graph = _build_dual_graph_from_hints(client, hints, query, project_id)
            except Exception as exc:
                logger.debug("Graph context build from hints failed: %s", exc)

        if dual_graph is None or dual_graph.is_empty:
            dual_graph = fetch_dual_graph_context(
                chunks, query=query, project_id=project_id,
                trace=trace.graph if trace else None,
                isolation_trace=trace.isolation if trace else None,
            )
        elif dual_graph.business.nodes == [] and dual_graph.business.edges == []:
            fallback = fetch_dual_graph_context(
                chunks, query=query, project_id=project_id,
                trace=trace.graph if trace else None,
                isolation_trace=trace.isolation if trace else None,
            )
            if fallback and fallback.business.nodes:
                dual_graph.business = fallback.business

    if trace is not None:
        trace.timing.graph_context_build_ms = ctx_timer.elapsed_ms
        if dual_graph:
            trace.graph.business_nodes = len(dual_graph.business.nodes)
            trace.graph.business_edges = len(dual_graph.business.edges)
            trace.graph.implementation_nodes = len(dual_graph.implementation.nodes)
            trace.graph.implementation_edges = len(dual_graph.implementation.edges)
            all_edges = dual_graph.business.edges + dual_graph.implementation.edges
            summary, low = _scan_edge_confidence(all_edges)
            trace.graph.edge_confidence_summary = summary
            trace.graph.low_confidence_edges = low
        total = (trace.timing.graph_exploration_ms + trace.timing.vector_search_ms
                 + trace.timing.merge_boost_ms + trace.timing.graph_context_build_ms)
        trace.timing.total_ms = total

    return chunks[:top_k], dual_graph, guidance_status


def _merge_chunks(
    guided: list[RetrievedChunk],
    standard: list[RetrievedChunk],
    guided_boost: float = 0.05,
) -> list[RetrievedChunk]:
    """Merge guided and standard chunks, deduplicate by chunk_id.

    Only boost guided chunks that are NOT already in the standard set —
    chunks appearing in both sets get no boost (the graph didn't help find them).
    """
    standard_ids = {c.chunk_id for c in standard}
    seen: dict[str, RetrievedChunk] = {}

    for chunk in guided:
        if chunk.chunk_id not in standard_ids:
            boosted = min(1.0, chunk.score + guided_boost)
            seen[chunk.chunk_id] = chunk.model_copy(update={"score": round(boosted, 4)})
        else:
            seen[chunk.chunk_id] = chunk

    for chunk in standard:
        if chunk.chunk_id not in seen:
            seen[chunk.chunk_id] = chunk

    return sorted(seen.values(), key=lambda c: c.score, reverse=True)
