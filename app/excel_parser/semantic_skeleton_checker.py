"""Semantic skeleton checker for flow_spec validation.

Validates flow_spec against a reference skeleton YAML that defines
required_edges and forbidden_edges.
"""
import re
from pathlib import Path
from typing import Optional
import yaml


def load_skeleton(skeleton_path: str) -> dict:
    """Load skeleton YAML."""
    with open(skeleton_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _text_matches(node_text: str, pattern_text: str, match_mode: str = "exact") -> bool:
    """Check if node text matches a pattern text."""
    node_clean = (node_text or "").strip().replace("\n", "")
    pattern_clean = (pattern_text or "").strip().replace("\n", "")
    
    # Normalize full-width/half-width parentheses for comparison
    fw_to_hw = str.maketrans("（）", "()")
    node_norm = node_clean.translate(fw_to_hw)
    pattern_norm = pattern_clean.translate(fw_to_hw)
    
    if match_mode == "contains":
        return pattern_norm in node_norm or node_norm in pattern_norm
    else:
        return node_norm == pattern_norm


def _find_nodes_by_text(nodes: list[dict], text: str, match_mode: str = "exact") -> list[str]:
    """Find ALL node IDs by text content (handles duplicate texts)."""
    results = []
    for n in nodes:
        node_text = (n.get("text") or "").strip().replace("\n", "")
        if _text_matches(node_text, text, match_mode):
            results.append(n["node_id"])
    return results


def _find_node_by_text(nodes: list[dict], text: str, match_mode: str = "exact") -> Optional[str]:
    """Find first node ID by its text content."""
    results = _find_nodes_by_text(nodes, text, match_mode)
    return results[0] if results else None


def check_skeleton(flow_spec: dict, skeleton: dict) -> dict:
    """Check flow_spec against skeleton.
    
    Returns a report dict with:
        required_edges: list of check results
        forbidden_edges: list of check results
        summary: pass/fail counts
    """
    nodes = flow_spec.get("nodes", [])
    edges = flow_spec.get("edges", [])
    
    required_results = []
    forbidden_results = []
    
    # Check required edges
    for req in skeleton.get("required_edges", []):
        from_text = req["from_text"]
        to_text = req["to_text"]
        label = req.get("label")
        match_mode = req.get("match_mode", "exact")
        
        # Find ALL matching nodes (handles duplicate texts like 条件：発注書テンプレート)
        from_node_ids = _find_nodes_by_text(nodes, from_text, match_mode)
        to_node_ids = _find_nodes_by_text(nodes, to_text, match_mode)
        
        found = False
        actual_edge = None
        
        # Check all combinations of from/to nodes
        for from_node_id in from_node_ids:
            for to_node_id in to_node_ids:
                for e in edges:
                    if e["from_node_id"] == from_node_id and e["to_node_id"] == to_node_id:
                        if label is None:
                            found = True
                            actual_edge = e
                            break
                        else:
                            edge_label = (e.get("label") or "").strip()
                            if _text_matches(edge_label, label, "contains"):
                                found = True
                                actual_edge = e
                                break
                if found:
                    break
            if found:
                break
        
        required_results.append({
            "from_text": from_text,
            "to_text": to_text,
            "label": label,
            "from_node_found": len(from_node_ids) > 0,
            "to_node_found": len(to_node_ids) > 0,
            "edge_found": found,
            "actual_edge_id": actual_edge["edge_id"] if actual_edge else None,
            "actual_label": actual_edge.get("label") if actual_edge else None,
            "status": "PASS" if found else "FAIL",
        })
    
    # Check forbidden edges
    for fb in skeleton.get("forbidden_edges", []):
        from_text = fb["from_text"]
        to_text = fb["to_text"]
        label = fb.get("label")
        match_mode = fb.get("match_mode", "exact")
        reason = fb.get("reason", "")
        
        from_node_ids = _find_nodes_by_text(nodes, from_text, match_mode)
        to_node_ids = _find_nodes_by_text(nodes, to_text, match_mode)
        
        found = False
        for from_node_id in from_node_ids:
            for to_node_id in to_node_ids:
                for e in edges:
                    if e["from_node_id"] == from_node_id and e["to_node_id"] == to_node_id:
                        if label is None:
                            found = True
                            break
                        else:
                            edge_label = (e.get("label") or "").strip()
                            if _text_matches(edge_label, label, "contains"):
                                found = True
                                break
                if found:
                    break
            if found:
                break
        
        forbidden_results.append({
            "from_text": from_text,
            "to_text": to_text,
            "label": label,
            "reason": reason,
            "found": found,
            "status": "FAIL" if found else "PASS",
        })
    
    req_pass = sum(1 for r in required_results if r["status"] == "PASS")
    req_total = len(required_results)
    fb_pass = sum(1 for r in forbidden_results if r["status"] == "PASS")
    fb_total = len(forbidden_results)
    
    return {
        "required_edges": required_results,
        "forbidden_edges": forbidden_results,
        "summary": {
            "required_pass": req_pass,
            "required_total": req_total,
            "forbidden_pass": fb_pass,
            "forbidden_total": fb_total,
            "overall_pass": (req_pass == req_total and fb_pass == fb_total),
        }
    }


def generate_skeleton_report(check_result: dict) -> str:
    """Generate markdown report from skeleton check results."""
    lines = ["# Semantic Skeleton Check Report\n"]
    
    summary = check_result["summary"]
    lines.append(f"**Required Edges:** {summary['required_pass']}/{summary['required_total']} PASS")
    lines.append(f"**Forbidden Edges:** {summary['forbidden_pass']}/{summary['forbidden_total']} PASS")
    lines.append(f"**Overall:** {'✅ PASS' if summary['overall_pass'] else '❌ FAIL'}\n")
    
    lines.append("## Required Edge Check\n")
    lines.append("| From | To | Expected Label | Found | Actual Label | Status |")
    lines.append("|---|---|---|---|---|---|")
    for r in check_result["required_edges"]:
        label_str = r["label"] or "(any)"
        found_str = "✓" if r["edge_found"] else "✗"
        actual = r.get("actual_label") or ""
        status = "✅" if r["status"] == "PASS" else "❌"
        lines.append(f"| {r['from_text']} | {r['to_text']} | {label_str} | {found_str} | {actual} | {status} |")
    
    lines.append("\n## Forbidden Edge Check\n")
    lines.append("| From | To | Label | Found | Reason | Status |")
    lines.append("|---|---|---|---|---|---|")
    for r in check_result["forbidden_edges"]:
        label_str = r.get("label") or "(any)"
        found_str = "✓" if r["found"] else "✗"
        status = "✅" if r["status"] == "PASS" else "❌"
        lines.append(f"| {r['from_text']} | {r['to_text']} | {label_str} | {found_str} | {r.get('reason','')} | {status} |")
    
    return "\n".join(lines) + "\n"
