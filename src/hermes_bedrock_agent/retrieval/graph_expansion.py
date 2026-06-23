"""Graph expansion module — query Neptune, expand by intent-aware allowlist, join to LanceDB chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import lancedb

from ..clients.neptune import NeptuneClient
from ..config import Config, config as _default_config
from .entity_extractor import ExtractedEntity

logger = logging.getLogger(__name__)


def _safe_str(val: object) -> str:
    """Convert a pandas row value to a clean string, handling NaN/None/float safely."""
    if val is None:
        return ""
    if isinstance(val, float):
        # NaN from pandas
        import math
        if math.isnan(val):
            return ""
        return str(val)
    s = str(val).strip()
    if s in ("nan", "None", "null"):
        return ""
    return s

# Intent-aware relation allowlists (actual Neptune graph schema)
INTENT_RELATION_ALLOWLISTS: dict[str, list[str]] = {
    "api": ["CALLS_API", "HAS_PARAMETER", "NEXT_STEP", "EXTRACTED_OBJECT", "HAS_SHEET", "CONTAINS_STEP"],
    "mapping": ["EXTRACTED_OBJECT", "HAS_SOURCE_FIELD", "HAS_TARGET_FIELD", "HAS_FIELD", "HAS_MAPPING_ROW", "HAS_SHEET", "USES_FIELD"],
    "flowchart": ["NEXT_STEP", "BRANCHES_TO", "CALLS_API", "CONTAINS_STEP", "EXTRACTED_OBJECT", "HAS_SHEET", "APPLIES_RULE"],
    "field": ["HAS_FIELD", "HAS_SOURCE_FIELD", "HAS_TARGET_FIELD", "USES_FIELD", "EXTRACTED_OBJECT", "HAS_SHEET"],
    "rule": ["APPLIES_RULE", "BRANCHES_TO", "HAS_CONDITION", "EXTRACTED_OBJECT", "HAS_SHEET", "NEXT_STEP"],
    "overview": ["HAS_SHEET", "EXTRACTED_OBJECT", "HAS_PROCESS", "USES_SYSTEM"],
}

MAX_GRAPH_CANDIDATES = 15
MAX_HOPS = 2
INTENTS_ALLOWING_2HOP = {"mapping", "flowchart", "api"}


@dataclass
class GraphCandidate:
    """A candidate chunk derived from graph expansion."""
    chunk_id: Optional[str] = None
    content: str = ""
    score: float = 0.0
    retrieval_source: str = "graph"
    graph_node_id: str = ""
    graph_node_name: str = ""
    graph_node_type: str = ""
    graph_relation_path: str = ""
    join_method: str = ""
    join_confidence: float = 0.0
    already_in_initial: bool = False
    # Provenance from LanceDB join
    project_id: str = ""
    workbook_name: str = ""
    sheet_name: str = ""
    document_id: str = ""
    document_name: str = ""
    document_type: str = ""
    source_markdown_file: str = ""
    evidence_path: str = ""
    evidence_paths: list[str] = field(default_factory=list)
    source_file: str = ""
    source_type: str = ""
    parser_type: str = ""
    chunk_type: str = ""
    # Evidence resolution fields (must pass through to RetrievedChunk for evidence loading)
    source_pdf_s3_path: str = ""
    source_excel_s3_path: str = ""
    parsed_markdown_path: str = ""


@dataclass
class GraphExpansionResult:
    """Result of graph expansion step."""
    candidates: list[GraphCandidate] = field(default_factory=list)
    graph_nodes_matched: list[dict] = field(default_factory=list)
    graph_paths: list[str] = field(default_factory=list)
    relation_allowlist_used: list[str] = field(default_factory=list)
    expansion_hops: int = 0
    neptune_available: bool = False
    error: Optional[str] = None


def _get_allowlist(intent_label: str) -> list[str]:
    """Get relation allowlist for the given intent."""
    return INTENT_RELATION_ALLOWLISTS.get(intent_label, ["EXTRACTED_OBJECT", "HAS_SHEET"])


def _node_info_from_result(node_data: dict) -> dict:
    """Extract node info from Neptune query result.
    
    Neptune openCypher returns properties nested under ~properties.
    Project ID may be in 'source_project_key' (v45) or 'project_id' (older).
    """
    if not node_data:
        return {}
    node_id = node_data.get("~id", "")
    labels = node_data.get("~labels", [])
    # Properties are nested under ~properties in Neptune openCypher results
    props = node_data.get("~properties", {})
    # Fallback: if ~properties is empty, try top-level (for mock compat)
    if not props:
        props = {k: v for k, v in node_data.items() if not k.startswith("~")}
    name = props.get("name", "")
    # Project ID: prefer source_project_key (v45+), fallback to project_id
    project_id = props.get("source_project_key") or props.get("project_id", "")
    return {
        "id": node_id,
        "labels": labels,
        "name": name,
        "entity_type": labels[0] if labels else "",
        "project_id": project_id,
        "workbook_name": props.get("workbook_name", ""),
        "sheet_name": props.get("sheet_name", ""),
        "description": props.get("description", ""),
        "evidence_text": props.get("evidence_text", ""),
        "source_file": props.get("source_file", ""),
    }


def expand_graph(
    entities: list[ExtractedEntity],
    intent_label: str,
    project_id: str,
    initial_chunk_ids: set[str],
    cfg: Optional[Config] = None,
) -> GraphExpansionResult:
    """Query Neptune with extracted entities, expand by intent-aware allowlist."""
    result = GraphExpansionResult()
    allowlist = _get_allowlist(intent_label)
    result.relation_allowlist_used = allowlist

    hops = MAX_HOPS if intent_label in INTENTS_ALLOWING_2HOP else 1
    result.expansion_hops = hops

    try:
        client = NeptuneClient()
        if not client.is_configured:
            logger.debug("Neptune not configured — skipping graph expansion")
            result.neptune_available = False
            return result
        result.neptune_available = True
    except Exception as exc:
        logger.debug("Neptune client init failed: %s", exc)
        result.error = str(exc)
        return result

    matched_nodes: list[dict] = []
    seen_node_ids: set[str] = set()

    # Neptune may use different project IDs than LanceDB
    # Support both source_project_key and project_id in queries
    # Step 1: Find nodes matching entities
    for entity in entities[:10]:
        try:
            search_name = entity.text
            cypher = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS toLower($name)"
            )
            params: dict = {"name": search_name}
            if project_id:
                cypher += " AND (n.project_id = $pid OR n.source_project_key = $pid OR n.project_id = $pidalt)"
                params["pid"] = project_id
                # Also try the Japanese-style project name that Neptune uses
                _neptune_pid_map = {
                    "sample_20260519": "サンプル20260519",
                    "saimu_bugyo_cloud": "14_債務奉行クラウド",
                }
                params["pidalt"] = _neptune_pid_map.get(project_id, project_id)
            cypher += " RETURN n LIMIT 5"

            rows = client.execute_query(cypher, parameters=params).get("results", [])
            for row in rows:
                node_data = row.get("n", {})
                info = _node_info_from_result(node_data)
                node_id = info.get("id", "")
                if node_id and node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    matched_nodes.append(info)
        except Exception as exc:
            logger.debug("Graph expansion entity search failed for '%s': %s", entity.text, exc)

    result.graph_nodes_matched = matched_nodes

    if not matched_nodes:
        return result

    # Step 2: Expand matched nodes along allowed relations
    candidates: list[GraphCandidate] = []

    for node in matched_nodes[:10]:
        node_id = node.get("id", "")
        node_name = node.get("name", "")
        if not node_id:
            continue

        try:
            # 1-hop expansion
            hop_cypher = (
                "MATCH (n)-[r]-(m) WHERE id(n) = $nid AND type(r) IN $rels"
            )
            hop_params: dict = {"nid": node_id, "rels": allowlist}
            if project_id:
                hop_cypher += " AND (m.project_id = $pid OR m.source_project_key = $pid OR m.project_id = $pidalt)"
                hop_params["pid"] = project_id
                _neptune_pid_map2 = {
                    "sample_20260519": "サンプル20260519",
                    "saimu_bugyo_cloud": "14_債務奉行クラウド",
                }
                hop_params["pidalt"] = _neptune_pid_map2.get(project_id, project_id)
            hop_cypher += " RETURN n, type(r) AS rel, m LIMIT 10"

            rows = client.execute_query(hop_cypher, parameters=hop_params).get("results", [])
            for row in rows:
                rel_type = row.get("rel", "")
                target_data = row.get("m", {})
                target_info = _node_info_from_result(target_data)
                target_name = target_info.get("name", "")

                path_str = "{src}-{rel}->{tgt}".format(
                    src=node_name, rel=rel_type, tgt=target_name,
                )
                result.graph_paths.append(path_str)

                candidate = GraphCandidate(
                    content=target_info.get("description", "") or target_info.get("evidence_text", "") or target_name,
                    score=0.6,
                    graph_node_id=target_info.get("id", ""),
                    graph_node_name=target_name,
                    graph_node_type=target_info.get("entity_type", ""),
                    graph_relation_path=path_str,
                    project_id=target_info.get("project_id", "") or project_id,
                    workbook_name=target_info.get("workbook_name", ""),
                    sheet_name=target_info.get("sheet_name", ""),
                )
                candidates.append(candidate)

            # 2-hop expansion for allowed intents
            if hops >= 2 and len(candidates) < MAX_GRAPH_CANDIDATES:
                hop2_cypher = (
                    "MATCH (n)-[r1]-(m)-[r2]-(p) "
                    "WHERE id(n) = $nid AND type(r1) IN $rels AND type(r2) IN $rels"
                )
                hop2_params: dict = {"nid": node_id, "rels": allowlist}
                if project_id:
                    hop2_cypher += " AND (p.project_id = $pid OR p.source_project_key = $pid OR p.project_id = $pidalt)"
                    hop2_params["pid"] = project_id
                    _neptune_pid_map3 = {
                        "sample_20260519": "サンプル20260519",
                        "saimu_bugyo_cloud": "14_債務奉行クラウド",
                    }
                    hop2_params["pidalt"] = _neptune_pid_map3.get(project_id, project_id)
                hop2_cypher += " RETURN n, type(r1) AS rel1, m, type(r2) AS rel2, p LIMIT 5"

                rows2 = client.execute_query(hop2_cypher, parameters=hop2_params).get("results", [])
                for row2 in rows2:
                    rel1 = row2.get("rel1", "")
                    rel2 = row2.get("rel2", "")
                    mid_data = row2.get("m", {})
                    end_data = row2.get("p", {})
                    mid_info = _node_info_from_result(mid_data)
                    end_info = _node_info_from_result(end_data)

                    mid_name = mid_info.get("name", "")
                    end_name = end_info.get("name", "")
                    path_str = "{src}-{r1}->{mid}-{r2}->{end}".format(
                        src=node_name, r1=rel1, mid=mid_name, r2=rel2, end=end_name,
                    )
                    result.graph_paths.append(path_str)

                    candidate = GraphCandidate(
                        content=end_info.get("description", "") or end_info.get("evidence_text", "") or end_name,
                        score=0.5,
                        graph_node_id=end_info.get("id", ""),
                        graph_node_name=end_name,
                        graph_node_type=end_info.get("entity_type", ""),
                        graph_relation_path=path_str,
                        project_id=end_info.get("project_id", "") or project_id,
                        workbook_name=end_info.get("workbook_name", ""),
                        sheet_name=end_info.get("sheet_name", ""),
                    )
                    candidates.append(candidate)

        except Exception as exc:
            logger.debug("Graph expansion hop failed for node %s: %s", node_id, exc)

    # Deduplicate by graph_node_id
    seen_candidates: set[str] = set()
    unique_candidates: list[GraphCandidate] = []
    for c in candidates:
        key = c.graph_node_id or c.graph_node_name
        if key and key not in seen_candidates:
            seen_candidates.add(key)
            unique_candidates.append(c)

    result.candidates = unique_candidates[:MAX_GRAPH_CANDIDATES]
    return result


def _normalize_project_id_for_lancedb(neptune_pid: str, lancedb_project_ids: list[str]) -> str:
    """Map Neptune project_id to LanceDB project_id.
    
    Neptune uses Japanese project names (サンプル20260519, 14_債務奉行クラウド)
    while LanceDB uses normalized Latin IDs (sample_20260519, saimu_bugyo_cloud).
    Also handles cases where they match directly.
    """
    # Direct match
    if neptune_pid in lancedb_project_ids:
        return neptune_pid
    
    # Known mappings (Neptune → LanceDB)
    known_mappings = {
        "サンプル20260519": "sample_20260519",
        "14_債務奉行クラウド": "saimu_bugyo_cloud",
    }
    if neptune_pid in known_mappings:
        mapped = known_mappings[neptune_pid]
        if mapped in lancedb_project_ids:
            return mapped

    # Try substring/prefix matching
    npid_lower = neptune_pid.lower()
    for lpid in lancedb_project_ids:
        if lpid.lower() in npid_lower or npid_lower in lpid.lower():
            return lpid
    
    return neptune_pid


def resolve_graph_candidates_to_chunks(
    graph_result: GraphExpansionResult,
    project_id: str,
    initial_chunk_ids: set[str],
    cfg: Optional[Config] = None,
) -> list[GraphCandidate]:
    """Join graph nodes back to LanceDB chunks using provenance metadata.

    Join strategy (in order of preference):
    1. project_id + workbook_name + sheet_name -> query LanceDB for matching chunks
    2. project_id + workbook_name -> broader match
    3. No join possible -> skip candidate
    """
    cfg = cfg or _default_config
    db_path = cfg.lancedb_path
    coll_name = cfg.vector_collection

    resolved: list[GraphCandidate] = []

    try:
        db = lancedb.connect(db_path)
        try:
            table = db.open_table(coll_name)
        except Exception:
            logger.debug("LanceDB table '%s' not found for graph candidate resolution", coll_name)
            return resolved
    except Exception as exc:
        logger.debug("LanceDB connection failed for graph candidate resolution: %s", exc)
        return resolved

    # Collect unique workbook_names from candidates for targeted filtering
    candidate_workbooks = set()
    for c in graph_result.candidates:
        if c.workbook_name:
            candidate_workbooks.add(c.workbook_name)

    if not candidate_workbooks:
        return resolved

    # Optimized path: filtered query with column selection to avoid loading embeddings
    # Select only the columns we need (excludes embedding vector ~3x speedup)
    select_cols = [
        "id", "text", "project_id", "workbook_name", "sheet_name",
        "chunk_type", "document_id", "document_name", "document_type",
        "source_markdown_file", "evidence_path", "evidence_paths",
        "source_file", "source_type", "parser_type",
        "source_pdf_s3_path", "source_excel_s3_path",
        "parsed_markdown_path",
    ]

    try:
        # Build SQL filter: project_id + workbook_name IN (...)
        workbook_list = ", ".join(f"'{wb}'" for wb in candidate_workbooks)
        if project_id:
            # First try to get normalized project_id — read small sample
            sample_df = table.search().limit(1).to_pandas()
            available_pids = []
            if "project_id" in sample_df.columns and not sample_df.empty:
                # Do a broader scan for unique project IDs
                pid_df = table.search().select(["project_id"]).limit(10000).to_pandas()
                available_pids = pid_df["project_id"].dropna().unique().tolist()
            normalized_pid = _normalize_project_id_for_lancedb(project_id, available_pids)
            where_clause = f"project_id = '{normalized_pid}' AND workbook_name IN ({workbook_list})"
        else:
            where_clause = f"workbook_name IN ({workbook_list})"

        # Filter existing columns only (some may not exist in table schema)
        table_columns = {f.name for f in table.schema}
        valid_cols = [c for c in select_cols if c in table_columns]

        df_project = (
            table.search()
            .where(where_clause)
            .select(valid_cols)
            .limit(5000)  # Safety cap — typical workbook has ~100-500 chunks
            .to_pandas()
        )
    except Exception as exc:
        # Fallback: full table scan if filtered query fails
        logger.warning("Optimized LanceDB query failed, falling back to full scan: %s", exc)
        try:
            df = table.to_pandas()
            if "embedding" in df.columns:
                df = df.drop(columns=["embedding"])
            if "vector" in df.columns:
                df = df.drop(columns=["vector"])
            # Filter by project
            if project_id:
                available_pids = df["project_id"].unique().tolist()
                normalized_pid = _normalize_project_id_for_lancedb(project_id, available_pids)
                df_project = df[df["project_id"] == normalized_pid]
            else:
                df_project = df
        except Exception as exc2:
            logger.debug("LanceDB fallback scan also failed: %s", exc2)
            return resolved

    if df_project.empty:
        return resolved

    for candidate in graph_result.candidates:
        wb_name = candidate.workbook_name
        sh_name = candidate.sheet_name

        matched_rows = None
        join_method = ""
        join_confidence = 0.0

        if wb_name and sh_name:
            # Strategy 1: project_id + workbook_name + sheet_name
            mask = (df_project["workbook_name"] == wb_name) & (df_project["sheet_name"] == sh_name)
            matched = df_project[mask]
            if not matched.empty:
                matched_rows = matched
                join_method = "project_workbook_sheet"
                join_confidence = 1.0

        if matched_rows is None and wb_name:
            # Strategy 2: project_id + workbook_name
            mask = df_project["workbook_name"] == wb_name
            matched = df_project[mask]
            if not matched.empty:
                matched_rows = matched
                join_method = "project_workbook"
                join_confidence = 0.7

        if matched_rows is None:
            continue

        # Take best matching chunks (limit to 3 per candidate)
        for _, row in matched_rows.head(3).iterrows():
            chunk_id = str(row.get("id", ""))
            is_duplicate = chunk_id in initial_chunk_ids

            resolved_candidate = GraphCandidate(
                chunk_id=chunk_id,
                content=_safe_str(row.get("text", "")),
                score=candidate.score * join_confidence,
                retrieval_source="graph",
                graph_node_id=candidate.graph_node_id,
                graph_node_name=candidate.graph_node_name,
                graph_node_type=candidate.graph_node_type,
                graph_relation_path=candidate.graph_relation_path,
                join_method=join_method,
                join_confidence=join_confidence,
                already_in_initial=is_duplicate,
                project_id=_safe_str(row.get("project_id", "")),
                workbook_name=_safe_str(row.get("workbook_name", "")),
                sheet_name=_safe_str(row.get("sheet_name", "")),
                document_id=_safe_str(row.get("document_id", "")),
                document_name=_safe_str(row.get("document_name", "")),
                document_type=_safe_str(row.get("document_type", "")),
                source_markdown_file=_safe_str(row.get("source_markdown_file", "")),
                evidence_path=_safe_str(row.get("evidence_path", "")),
                evidence_paths=_parse_evidence_paths(row.get("evidence_paths", "")),
                source_file=_safe_str(row.get("source_file", "")),
                source_type=_safe_str(row.get("source_type", "")),
                parser_type=_safe_str(row.get("parser_type", "")),
                chunk_type=_safe_str(row.get("chunk_type", "")),
                # Evidence resolution fields — required for answer_generator evidence loading
                source_pdf_s3_path=_safe_str(row.get("source_pdf_s3_path", "")),
                source_excel_s3_path=_safe_str(row.get("source_excel_s3_path", "")),
                # parsed_markdown_path may not exist as a LanceDB column;
                # fall back to source_markdown_file which is semantically equivalent.
                parsed_markdown_path=(
                    _safe_str(row.get("parsed_markdown_path", ""))
                    or _safe_str(row.get("source_markdown_file", ""))
                ),
            )
            resolved.append(resolved_candidate)

    return resolved


def _parse_evidence_paths(raw: object) -> list[str]:
    """Parse evidence_paths from various storage formats."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        if raw.startswith("["):
            try:
                import json
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
        return [raw]
    return []
