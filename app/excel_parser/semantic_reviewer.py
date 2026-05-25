"""Semantic reviewer - validates flow_spec against structural and textual evidence.

Since VLM/multimodal may not be available, this performs text-based structural review:
- Checks node classification consistency
- Validates edge connectivity
- Checks for orphan nodes
- Validates decision branch completeness
- Cross-references with reference signals
"""
import re
import logging
from .flow_spec_models import (
    FlowSpec, FlowNode, FlowEdge, NodeType, NodeRole, EdgeType, ReviewStatus
)

logger = logging.getLogger(__name__)


def review_flow_spec(flow_spec: FlowSpec, reference_signals: dict = None) -> dict:
    """Perform structural semantic review of a flow_spec.
    
    Returns:
        dict with review results per the spec format
    """
    review = {
        "region_id": flow_spec.region_id,
        "region_title": flow_spec.region_title,
        "pass": True,
        "score": 100,
        "node_issues": [],
        "edge_issues": [],
        "missing_nodes": [],
        "wrong_nodes": [],
        "missing_edges": [],
        "wrong_edges": [],
        "layout_issues": [],
        "final_action": "accept",
        "review_mode": "text-only",
    }
    
    deductions = 0
    
    # 1. Check for orphan nodes (no edges at all)
    connected_nodes = set()
    for edge in flow_spec.edges:
        connected_nodes.add(edge.from_node_id)
        connected_nodes.add(edge.to_node_id)
    
    for node in flow_spec.nodes:
        if node.role in (NodeRole.ANNOTATION, NodeRole.CONTAINER, NodeRole.EDGE_LABEL):
            continue
        if node.node_id not in connected_nodes:
            review["node_issues"].append({
                "issue": f"Orphan node: '{node.text}' has no connections",
                "related_node_id": node.node_id,
                "suggested_fix": "Check if connectors were missed or if this is annotation"
            })
            deductions += 2
    
    # 2. Check decision nodes have branches
    decision_nodes = [n for n in flow_spec.nodes if n.node_type == NodeType.DECISION]
    for dnode in decision_nodes:
        outgoing = [e for e in flow_spec.edges if e.from_node_id == dnode.node_id]
        if len(outgoing) < 2:
            review["edge_issues"].append({
                "issue": f"Decision '{dnode.text}' has only {len(outgoing)} outgoing edge(s), expected 2+",
                "related_edge_id": "",
                "suggested_fix": "Check for missing branch connectors"
            })
            deductions += 5
        
        # Check if branches have labels
        unlabeled = [e for e in outgoing if not e.label]
        if unlabeled and len(outgoing) > 1:
            review["edge_issues"].append({
                "issue": f"Decision '{dnode.text}' has {len(unlabeled)} unlabeled branch(es)",
                "related_edge_id": unlabeled[0].edge_id if unlabeled else "",
                "suggested_fix": "Find nearby edge label shapes to attach"
            })
            deductions += 3
    
    # 3. Check for start/end nodes
    start_nodes = [n for n in flow_spec.nodes if n.node_type == NodeType.START]
    end_nodes = [n for n in flow_spec.nodes if n.node_type == NodeType.END]
    
    if not start_nodes:
        review["missing_nodes"].append({
            "text": "開始",
            "evidence": "No start node found in flow",
            "suggested_node_type": "start"
        })
        deductions += 5
    
    if not end_nodes:
        review["missing_nodes"].append({
            "text": "終了",
            "evidence": "No end node found in flow",
            "suggested_node_type": "end"
        })
        deductions += 3
    
    # 4. Check edge label nodes that slipped through
    for node in flow_spec.nodes:
        text = (node.text or "").strip()
        if node.role == NodeRole.BUSINESS_STEP and text.endswith("の場合"):
            review["wrong_nodes"].append({
                "node_id": node.node_id,
                "reason": f"Node text '{text}' looks like an edge label, not a process step"
            })
            deductions += 3
    
    # 5. Check for very low confidence edges
    low_conf_edges = [e for e in flow_spec.edges if e.confidence < 0.5]
    if low_conf_edges:
        review["edge_issues"].append({
            "issue": f"{len(low_conf_edges)} edges with confidence < 0.5",
            "related_edge_id": low_conf_edges[0].edge_id,
            "suggested_fix": "Mark as needs_human_review"
        })
        deductions += len(low_conf_edges)
    
    # 6. Check reference signals if provided
    if reference_signals:
        _check_reference_coverage(flow_spec, reference_signals, review)
        # Additional deductions based on missing coverage
        missing_terms = len(review.get("missing_nodes", []))
        deductions += missing_terms * 2
    
    # 7. Check connectivity (is there a path from start to end?)
    if start_nodes and end_nodes:
        reachable = _find_reachable(start_nodes[0].node_id, flow_spec.edges)
        end_reachable = any(n.node_id in reachable for n in end_nodes)
        if not end_reachable:
            review["layout_issues"].append({
                "issue": "No path from START to END - flow is disconnected",
                "suggested_fix": "Check for missing cross-region connectors"
            })
            deductions += 10
    
    # Compute final score
    review["score"] = max(0, 100 - deductions)
    review["pass"] = review["score"] >= 50
    
    if review["score"] < 50:
        review["final_action"] = "revise_flow_spec"
    elif review["score"] < 70:
        review["final_action"] = "needs_human_review"
    else:
        review["final_action"] = "accept"
    
    return review


def _check_reference_coverage(flow_spec: FlowSpec, ref_signals: dict, review: dict):
    """Check coverage against reference signals."""
    ref_terms = set(ref_signals.get("business_terms", []))
    ref_nodes = set(ref_signals.get("possible_node_texts", []))
    
    # Get current flow spec texts
    current_texts = set()
    for node in flow_spec.nodes:
        if node.text:
            current_texts.add(node.text.strip())
            # Also add normalized version
            current_texts.add(node.text.replace("\n", " ").strip())
    
    # Check for missing important terms
    for term in ref_terms:
        found = any(term in t for t in current_texts)
        if not found:
            review["missing_nodes"].append({
                "text": term,
                "evidence": "Present in reference but not in flow_spec",
                "suggested_node_type": "process"
            })


def _find_reachable(start_id: str, edges: list[FlowEdge]) -> set:
    """BFS to find all reachable nodes from start."""
    visited = set()
    queue = [start_id]
    
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        
        for edge in edges:
            if edge.from_node_id == current and edge.to_node_id not in visited:
                queue.append(edge.to_node_id)
    
    return visited


def generate_review_summary(reviews: list[dict]) -> str:
    """Generate markdown summary of all region reviews."""
    lines = ["# Semantic Review Summary", ""]
    lines.append(f"Review Mode: text-only")
    lines.append("Visual semantic review skipped because no multimodal model/tool is available.")
    lines.append("")
    
    # Summary table
    lines.append("| Region | Title | Score | Pass | Main Issues |")
    lines.append("|--------|-------|------:|------|-------------|")
    
    for r in reviews:
        issues_summary = []
        if r["node_issues"]:
            issues_summary.append(f"{len(r['node_issues'])} node issues")
        if r["edge_issues"]:
            issues_summary.append(f"{len(r['edge_issues'])} edge issues")
        if r["missing_nodes"]:
            issues_summary.append(f"{len(r['missing_nodes'])} missing nodes")
        if r["wrong_nodes"]:
            issues_summary.append(f"{len(r['wrong_nodes'])} wrong nodes")
        
        issues_str = "; ".join(issues_summary) if issues_summary else "None"
        pass_str = "✅" if r["pass"] else "❌"
        
        lines.append(
            f"| {r['region_id']} | {r['region_title'][:30]} | {r['score']} | "
            f"{pass_str} | {issues_str} |"
        )
    
    lines.append("")
    
    # Detailed issues
    for r in reviews:
        if not r["pass"] or r["node_issues"] or r["edge_issues"]:
            lines.append(f"## {r['region_id']}: {r['region_title']}")
            lines.append("")
            
            if r["node_issues"]:
                lines.append("### Node Issues")
                for issue in r["node_issues"]:
                    lines.append(f"- {issue['issue']}")
                lines.append("")
            
            if r["edge_issues"]:
                lines.append("### Edge Issues")
                for issue in r["edge_issues"]:
                    lines.append(f"- {issue['issue']}")
                lines.append("")
            
            if r["missing_nodes"]:
                lines.append("### Missing Nodes")
                for mn in r["missing_nodes"]:
                    lines.append(f"- `{mn['text']}` ({mn['evidence']})")
                lines.append("")
            
            if r["wrong_nodes"]:
                lines.append("### Wrong Nodes (likely edge labels)")
                for wn in r["wrong_nodes"]:
                    lines.append(f"- `{wn['node_id']}`: {wn['reason']}")
                lines.append("")
    
    return "\n".join(lines)
