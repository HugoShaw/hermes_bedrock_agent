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

    # Pending edge ratio in display graph
    if display_edges:
        pending_display = sum(1 for e in display_edges if e.get("review_status") == "pending")
        if pending_display > len(display_edges) * 0.5:
            issues_p2.append(
                f"Many pending edges in display graph: {pending_display}/{len(display_edges)}"
            )

    has_p0 = len(issues_p0) > 0

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
                f"MATCH (n) WHERE n.project_id = '{project_id}' RETURN count(n) AS cnt"
            )
            edge_result = client.execute_query(
                f"MATCH (a)-[r]->(b) WHERE a.project_id = '{project_id}' RETURN count(r) AS cnt"
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
