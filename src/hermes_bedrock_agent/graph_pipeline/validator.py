"""Phase 7/9: Preflight validation before loading, and post-load verification."""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)


def run_preflight_check(
    nodes: list[dict],
    edges: list[dict],
    display_nodes: list[dict],
    display_edges: list[dict],
    project_id: str,
    project_name: str,
    inventory: list[dict],
    registry: dict | None = None,
) -> tuple[str, bool]:
    """Comprehensive preflight validation. Returns (report_text, has_p0_blocking_issues)."""
    issues_p0: list[str] = []
    issues_p1: list[str] = []
    issues_p2: list[str] = []

    node_ids = {n["id"] for n in nodes}

    # Duplicate node IDs
    id_counts = Counter(n["id"] for n in nodes)
    dupes = {k: v for k, v in id_counts.items() if v > 1}
    if dupes:
        issues_p0.append(f"Duplicate node IDs: {len(dupes)} duplicates")

    # Duplicate edge IDs
    edge_id_counts = Counter(e.get("id", "") for e in edges)
    edge_dupes = {k: v for k, v in edge_id_counts.items() if v > 1 and k}
    if edge_dupes:
        issues_p1.append(f"Duplicate edge IDs: {len(edge_dupes)} duplicates")

    # Dangling edges
    dangling = sum(
        1 for e in edges
        if e.get("start_id") not in node_ids or e.get("end_id") not in node_ids
    )
    if dangling > 0:
        issues_p0.append(f"Dangling edge references: {dangling}")

    # Empty source_file
    empty_source = sum(1 for n in nodes if not n.get("source_file"))
    if empty_source > 0:
        issues_p1.append(f"Nodes with empty source_file: {empty_source}")

    # Empty evidence_text
    empty_evidence = sum(1 for n in nodes if not n.get("evidence_text"))
    if empty_evidence > 0:
        issues_p1.append(f"Nodes with empty evidence_text: {empty_evidence}")

    # Wrong project_name
    wrong_project = sum(1 for n in nodes if n.get("project_name") != project_name)
    if wrong_project > 0:
        issues_p0.append(f"Nodes with wrong project_name: {wrong_project}")

    # Evidence-node dominance in display graph
    evidence_in_display = sum(
        1 for n in display_nodes
        if n.get("entity_type") in ("Sheet", "EvidenceUnit", "MarkdownFile")
    )
    if display_nodes and evidence_in_display / len(display_nodes) > 0.20:
        issues_p1.append(
            f"Display graph has {evidence_in_display}/{len(display_nodes)} evidence nodes (>20%)"
        )

    # Isolated node ratio
    connected_ids: set[str] = set()
    for edge in edges:
        connected_ids.add(edge.get("start_id", ""))
        connected_ids.add(edge.get("end_id", ""))
    isolated_semantic = [
        n for n in nodes
        if n["id"] not in connected_ids and n.get("layer") not in ("evidence", "project")
    ]
    if isolated_semantic and len(isolated_semantic) > len(nodes) * 0.3:
        issues_p1.append(
            f"High isolated semantic node ratio: {len(isolated_semantic)}/{len(nodes)}"
        )

    # Mermaid participation
    mermaid_sheets = [f for f in inventory if f.get("has_mermaid")]
    if mermaid_sheets:
        flow_nodes = [
            n for n in nodes
            if n.get("entity_type") in ("FlowNode", "FunctionModule", "DecisionPoint")
        ]
        if not flow_nodes:
            issues_p1.append(
                f"Mermaid exists in {len(mermaid_sheets)} sheets but no FlowNode/FunctionModule extracted"
            )

    # P0: Mermaid artifacts exist in inventory but no node/edge has mermaid source_file
    mermaid_inventory = [
        f for f in inventory
        if f.get("sheet_type") == "mermaid_flowchart"
        or "mermaid" in f.get("file_path", "").lower()
        or f.get("file_name", "").endswith(".mmd")
    ]
    if mermaid_inventory:
        _mermaid_indicators = ("mermaid/", "mermaid\\", ".mmd", "mermaid_structure.json", "mermaid_parsed.md")
        mermaid_sourced_nodes = [
            n for n in nodes
            if any(ind in n.get("source_file", "") for ind in _mermaid_indicators)
        ]
        mermaid_sourced_edges = [
            e for e in edges
            if any(ind in e.get("source_file", "") for ind in _mermaid_indicators)
        ]
        if not mermaid_sourced_nodes and not mermaid_sourced_edges:
            issues_p0.append(
                f"Mermaid artifacts found in inventory ({len(mermaid_inventory)} files) "
                f"but no graph node or edge has a Mermaid source_file — "
                f"mermaid extraction was skipped or failed"
            )

    # Pending edge ratio in display graph
    if display_edges:
        pending_display = sum(1 for e in display_edges if e.get("review_status") == "pending")
        if pending_display > len(display_edges) * 0.5:
            issues_p2.append(
                f"Many pending edges in display graph: {pending_display}/{len(display_edges)}"
            )

    # ── Edge promotion gates (v4.5 fix) ──────────────────────────────────────
    # Fail if verified cache relationships are silently lost
    if registry:
        diag = registry.get("diagnostics", {})
        cache_verified = diag.get("cache_verified_edge_type_counts", {})
        promoted = diag.get("promoted_edge_type_counts", {})
        unresolved = diag.get("unresolved_endpoint_edge_type_counts", {})
        silently_dropped = diag.get("silently_dropped_edge_type_counts", {})

        # P0: If silently_dropped_edge_type_counts is non-empty, block import
        if silently_dropped:
            issues_p0.append(
                f"Silently dropped edges detected: {dict(silently_dropped)} — "
                f"indicates a pipeline bug, not a data issue"
            )

        # P0: Key verified edge types exist in cache but zero promoted AND zero unresolved
        _critical_types = {
            "HAS_FIELD", "MAPS_TO", "HAS_MAPPING_ROW", "HAS_SOURCE_FIELD",
            "HAS_TARGET_FIELD", "NEXT_STEP", "BRANCHES_TO", "CONTAINS_STEP",
            "HAS_PROCESS", "HAS_FUNCTION", "HAS_STEP", "HAS_CONDITION",
            "APPLIES_RULE",
        }
        for etype in _critical_types:
            cache_count = cache_verified.get(etype, 0)
            promoted_count = promoted.get(etype, 0)
            unresolved_count = unresolved.get(etype, 0)
            if cache_count > 0 and promoted_count == 0 and unresolved_count == 0:
                issues_p0.append(
                    f"Verified cache edge type '{etype}' has {cache_count} edges in cache "
                    f"but 0 promoted and 0 unresolved — edges silently lost"
                )

        # P1: FlowNode/DecisionPoint nodes exist with flow evidence but zero flow edges
        type_counts_pre = Counter(n.get("entity_type", "Unknown") for n in nodes)
        flow_node_count = type_counts_pre.get("FlowNode", 0) + type_counts_pre.get("DecisionPoint", 0)
        flow_edge_types = {"NEXT_STEP", "BRANCHES_TO", "CONTAINS_STEP"}
        flow_edge_count = sum(promoted.get(t, 0) for t in flow_edge_types)
        if flow_node_count > 0 and any(cache_verified.get(t, 0) > 0 for t in flow_edge_types):
            if flow_edge_count == 0:
                issues_p1.append(
                    f"FlowNode/DecisionPoint nodes exist ({flow_node_count}) and flow edge "
                    f"evidence exists in cache, but 0 flow edges promoted"
                )

        # P1: Mapping nodes exist with mapping evidence but zero mapping edges
        mapping_node_count = (
            type_counts_pre.get("MappingDefinition", 0)
            + type_counts_pre.get("FieldMapping", 0)
            + type_counts_pre.get("Field", 0)
            + type_counts_pre.get("FieldDefinition", 0)
            + type_counts_pre.get("DataEntity", 0)
        )
        mapping_edge_types = {"HAS_MAPPING_ROW", "HAS_FIELD", "MAPS_TO", "HAS_SOURCE_FIELD", "HAS_TARGET_FIELD"}
        mapping_edge_count = sum(promoted.get(t, 0) for t in mapping_edge_types)
        if mapping_node_count > 0 and any(cache_verified.get(t, 0) > 0 for t in mapping_edge_types):
            if mapping_edge_count == 0:
                issues_p1.append(
                    f"Mapping/Field nodes exist ({mapping_node_count}) and mapping edge "
                    f"evidence exists in cache, but 0 mapping edges promoted"
                )

        # Edge resolution summary for report
        total_cache = diag.get("total_cache_edges", 0)
        total_promoted = diag.get("total_promoted_edges", 0)
        total_unresolved = diag.get("total_unresolved_edges", 0)
        if total_cache > 0 and total_promoted == 0 and total_unresolved == 0:
            issues_p0.append(
                f"All {total_cache} cache edges vanished — "
                f"0 promoted and 0 unresolved. Critical pipeline failure."
            )

    # v4.2: Core entity type coverage check
    type_counts = Counter(n.get("entity_type", "Unknown") for n in nodes)
    for core_type in ("BusinessProcess", "DataEntity"):
        if type_counts.get(core_type, 0) == 0:
            issues_p2.append(f"Core entity type '{core_type}' has zero instances — extraction may be incomplete")
    if type_counts.get("System", 0) == 0 and type_counts.get("ExternalSystem", 0) == 0:
        issues_p2.append("Core entity type 'System/ExternalSystem' has zero instances — extraction may be incomplete")
    if type_counts.get("BusinessRule", 0) == 0:
        issues_p2.append("Core entity type 'BusinessRule' has zero instances — extraction may be incomplete")

    has_p0 = len(issues_p0) > 0

    # Build edge resolution diagnostics section
    edge_resolution_section = ""
    if registry:
        diag = registry.get("diagnostics", {})
        res_stats = registry.get("edge_resolution_stats", {})
        total_cache = diag.get("total_cache_edges", 0)
        total_promoted = diag.get("total_promoted_edges", 0)
        total_unresolved = diag.get("total_unresolved_edges", 0)
        cache_verified = diag.get("cache_verified_edge_type_counts", {})
        promoted_types = diag.get("promoted_edge_type_counts", {})
        unresolved_types = diag.get("unresolved_endpoint_edge_type_counts", {})

        edge_resolution_section = f"""
## Edge Promotion Diagnostics
- Cache edges (total): {total_cache}
- Cache edges (verified): {sum(cache_verified.values())}
- Promoted edges: {total_promoted}
- Unresolved edges: {total_unresolved}
- Silently dropped: 0

### Resolution Strategy Stats
{chr(10).join(f'| {k} | {v} |' for k, v in sorted(res_stats.items(), key=lambda x: -x[1]))}

### Cache Verified Edge Types
{chr(10).join(f'| {t} | {c} |' for t, c in sorted(cache_verified.items(), key=lambda x: -x[1])[:20])}

### Promoted Edge Types
{chr(10).join(f'| {t} | {c} |' for t, c in sorted(promoted_types.items(), key=lambda x: -x[1])[:20])}

### Unresolved Edge Types
{chr(10).join(f'| {t} | {c} |' for t, c in sorted(unresolved_types.items(), key=lambda x: -x[1])[:20]) if unresolved_types else '- None'}
"""

    report = f"""# Semantic Map Preflight Check
## Project: {project_name} ({project_id})

## Summary
- Total nodes: {len(nodes)}
- Total edges: {len(edges)}
- Display nodes: {len(display_nodes)}
- Display edges: {len(display_edges)}
- Isolated nodes (semantic): {len(isolated_semantic)}
- P0 issues: {len(issues_p0)}
- P1 issues: {len(issues_p1)}
- P2 issues: {len(issues_p2)}

## P0 Issues (BLOCKING)
{chr(10).join(f'- ❌ {i}' for i in issues_p0) if issues_p0 else '- ✅ None'}

## P1 Issues (WARNING)
{chr(10).join(f'- ⚠️ {i}' for i in issues_p1) if issues_p1 else '- ✅ None'}

## P2 Issues (INFO)
{chr(10).join(f'- ℹ️ {i}' for i in issues_p2) if issues_p2 else '- ✅ None'}
{edge_resolution_section}
## Node Type Distribution
{_fmt_type_dist(nodes)}

## Edge Type Distribution
{_fmt_edge_dist(edges)}

## Layer Distribution
{_fmt_layer_dist(nodes)}

## Verdict: {'❌ BLOCKED — P0 issues must be fixed' if has_p0 else '✅ PASS — safe to generate Cypher'}
"""
    return report, has_p0


def _fmt_type_dist(nodes: list[dict]) -> str:
    counts = Counter(n.get("entity_type", "Unknown") for n in nodes)
    lines = [f"| {t} | {c} |" for t, c in counts.most_common(30)]
    return "| Entity Type | Count |\n|---|---|\n" + "\n".join(lines)


def _fmt_edge_dist(edges: list[dict]) -> str:
    counts = Counter(e.get("type", "Unknown") for e in edges)
    lines = [f"| {t} | {c} |" for t, c in counts.most_common(30)]
    return "| Relationship Type | Count |\n|---|---|\n" + "\n".join(lines)


def _fmt_layer_dist(nodes: list[dict]) -> str:
    counts = Counter(n.get("layer", "unknown") for n in nodes)
    lines = [f"| {t} | {c} |" for t, c in counts.most_common()]
    return "| Layer | Count |\n|---|---|\n" + "\n".join(lines)


def post_load_verify(client: object, project_id: str, expected_nodes: int, expected_edges: int) -> dict:
    """Run basic count queries against Neptune to verify the load.

    The Neptune client returns {'results': [{'cnt': N}]}, not a bare list.
    We also retry once on transient failures since Neptune Analytics may
    have brief eventual-consistency delays after a bulk write.
    """
    import time

    def _extract_cnt(result: dict) -> int:
        """Extract count from Neptune query result dict."""
        if not result:
            return 0
        # Neptune response: {'results': [{'cnt': N}]}
        results_list = result.get("results", [])
        if results_list and isinstance(results_list, list):
            return results_list[0].get("cnt", 0)
        return 0

    for attempt in range(2):
        try:
            node_result = client.execute_query(
                "MATCH (n) WHERE n.project_id = $project_id RETURN count(n) AS cnt",
                parameters={"project_id": project_id},
            )
            edge_result = client.execute_query(
                "MATCH (a)-[r]->(b) WHERE a.project_id = $project_id RETURN count(r) AS cnt",
                parameters={"project_id": project_id},
            )
            actual_nodes = _extract_cnt(node_result)
            actual_edges = _extract_cnt(edge_result)

            if actual_nodes == 0 and expected_nodes > 0 and attempt == 0:
                # Possible eventual-consistency delay; retry after a short pause
                logger.info("Post-load verification: 0 nodes on first attempt, retrying in 3s...")
                time.sleep(3)
                continue

            logger.info(
                "Post-load verification: nodes=%d/%d, edges=%d/%d",
                actual_nodes, expected_nodes, actual_edges, expected_edges,
            )
            return {
                "expected_nodes": expected_nodes,
                "actual_nodes": actual_nodes,
                "expected_edges": expected_edges,
                "actual_edges": actual_edges,
                "nodes_ok": actual_nodes >= expected_nodes,
                "edges_ok": actual_edges >= expected_edges,
            }
        except Exception as exc:
            logger.error("Post-load verification failed (attempt %d): %s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(2)
                continue
            return {"error": str(exc)}
    return {"error": "Exhausted retries"}
