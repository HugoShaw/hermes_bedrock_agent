"""Flow spec override applier.

Reads override YAML and modifies flow_spec edges/nodes accordingly.
"""
from typing import Optional


def _text_matches(text1: str, text2: str) -> bool:
    """Fuzzy text match (contains or equal, ignoring newlines)."""
    t1 = (text1 or "").strip().replace("\n", "")
    t2 = (text2 or "").strip().replace("\n", "")
    return t1 == t2 or t1 in t2 or t2 in t1


def _find_node_by_text(nodes: list[dict], text: str) -> Optional[str]:
    """Find node_id by text."""
    for n in nodes:
        if _text_matches(n.get("text", ""), text):
            return n["node_id"]
    return None


def apply_overrides(flow_spec: dict, overrides: dict) -> dict:
    """Apply overrides to flow_spec in-place, return report.
    
    Returns report dict with applied/skipped actions.
    """
    nodes = flow_spec.get("nodes", [])
    edges = flow_spec.get("edges", [])
    
    report = {"applied": [], "skipped": []}
    
    # Edge overrides
    for ovr in overrides.get("edge_overrides", []):
        action = ovr["action"]
        from_text = ovr.get("from_text", "")
        to_text = ovr.get("to_text", "")
        label = ovr.get("label", "")
        confidence = ovr.get("confidence", 0.9)
        reason = ovr.get("reason", "override")
        
        # Support direct node_id references (preferred for ambiguous text)
        from_id = ovr.get("from_id") or _find_node_by_text(nodes, from_text)
        to_id = ovr.get("to_id") or _find_node_by_text(nodes, to_text)
        
        if action == "relabel":
            if from_id and to_id:
                # Find the edge and set its label
                matched = False
                for e in edges:
                    if e["from_node_id"] == from_id and e["to_node_id"] == to_id:
                        if not e.get("label"):  # Only relabel if currently unlabeled
                            old_label = e.get("label", "")
                            e["label"] = label
                            e["condition"] = label
                            e["confidence"] = max(e.get("confidence", 0), confidence)
                            e["reason"] = e.get("reason", "") + f" [OVERRIDE: {reason}]"
                            e["review_status"] = "ok"
                            if "evidence" not in e:
                                e["evidence"] = {}
                            e["evidence"]["override_reason"] = reason
                            report["applied"].append({
                                "action": "relabel",
                                "edge": f"{from_text} -> {to_text}",
                                "old_label": old_label,
                                "new_label": label,
                                "reason": reason,
                            })
                            matched = True
                            break
                if not matched:
                    report["skipped"].append({
                        "action": "relabel",
                        "edge": f"{from_text} -> {to_text}",
                        "reason": "edge not found or already labeled",
                    })
            else:
                report["skipped"].append({
                    "action": "relabel",
                    "edge": f"{from_text} -> {to_text}",
                    "reason": f"nodes not found: from={'found' if from_id else 'missing'}, to={'found' if to_id else 'missing'}",
                })
        
        elif action == "add_edge":
            if from_id and to_id:
                # Check if edge already exists
                exists = any(
                    e["from_node_id"] == from_id and e["to_node_id"] == to_id
                    for e in edges
                )
                if not exists:
                    edge_id = f"e_ovr_{len(edges):03d}"
                    new_edge = {
                        "edge_id": edge_id,
                        "from_node_id": from_id,
                        "to_node_id": to_id,
                        "label": label or "",
                        "condition": label or "",
                        "edge_type": "semantic_override",
                        "confidence": confidence,
                        "review_status": "ok",
                        "reason": f"[OVERRIDE: {reason}]",
                        "evidence": {"override_reason": reason},
                    }
                    edges.append(new_edge)
                    report["applied"].append({
                        "action": "add_edge",
                        "edge": f"{from_text} -> {to_text}",
                        "reason": reason,
                    })
                else:
                    report["skipped"].append({
                        "action": "add_edge",
                        "edge": f"{from_text} -> {to_text}",
                        "reason": "edge already exists",
                    })
            else:
                report["skipped"].append({
                    "action": "add_edge",
                    "edge": f"{from_text} -> {to_text}",
                    "reason": f"nodes not found",
                })
        
        elif action == "remove_edge":
            if from_id and to_id:
                before_len = len(edges)
                flow_spec["edges"] = [
                    e for e in edges
                    if not (e["from_node_id"] == from_id and e["to_node_id"] == to_id
                            and (not label or _text_matches(e.get("label", ""), label)))
                ]
                edges = flow_spec["edges"]
                if len(edges) < before_len:
                    report["applied"].append({
                        "action": "remove_edge",
                        "edge": f"{from_text} -> {to_text}",
                        "label": label,
                        "reason": reason,
                    })
                else:
                    report["skipped"].append({
                        "action": "remove_edge",
                        "edge": f"{from_text} -> {to_text}",
                        "reason": "edge not found",
                    })
    
    # Node overrides
    for ovr in overrides.get("node_overrides", []):
        action = ovr["action"]
        text = ovr.get("text", "")
        
        if action == "exclude":
            node_id = _find_node_by_text(nodes, text)
            if node_id:
                # Move to excluded_objects
                excluded = flow_spec.setdefault("excluded_objects", [])
                node = next((n for n in nodes if n["node_id"] == node_id), None)
                if node:
                    excluded.append({
                        "object_id": node_id,
                        "object_type": "node",
                        "text": node.get("text", ""),
                        "exclude_reason": ovr.get("reason", "override"),
                    })
                    flow_spec["nodes"] = [n for n in nodes if n["node_id"] != node_id]
                    # Remove edges referencing this node
                    flow_spec["edges"] = [
                        e for e in flow_spec["edges"]
                        if e["from_node_id"] != node_id and e["to_node_id"] != node_id
                    ]
                    edges = flow_spec["edges"]
                    nodes = flow_spec["nodes"]
                    report["applied"].append({
                        "action": "exclude_node",
                        "node": text,
                        "reason": ovr.get("reason", ""),
                    })
            else:
                report["skipped"].append({
                    "action": "exclude_node",
                    "node": text,
                    "reason": "node not found (may already be excluded)",
                })
    
    return report


def generate_override_report(report: dict) -> str:
    """Generate markdown report."""
    lines = ["# Override Application Report\n"]
    
    lines.append(f"**Applied:** {len(report['applied'])}")
    lines.append(f"**Skipped:** {len(report['skipped'])}\n")
    
    if report["applied"]:
        lines.append("## Applied Overrides\n")
        lines.append("| Action | Target | Detail | Reason |")
        lines.append("|---|---|---|---|")
        for a in report["applied"]:
            action = a["action"]
            target = a.get("edge", a.get("node", ""))
            detail = a.get("new_label", a.get("label", ""))
            lines.append(f"| {action} | {target} | {detail} | {a.get('reason','')} |")
    
    if report["skipped"]:
        lines.append("\n## Skipped Overrides\n")
        lines.append("| Action | Target | Reason |")
        lines.append("|---|---|---|")
        for s in report["skipped"]:
            action = s["action"]
            target = s.get("edge", s.get("node", ""))
            lines.append(f"| {action} | {target} | {s.get('reason','')} |")
    
    return "\n".join(lines) + "\n"
