#!/usr/bin/env python3
"""
Murata Enterprise GraphRAG — Neptune Subgraph Exporter
======================================================

Export Neptune subgraphs centered on a focus entity in multiple formats:
Mermaid, HTML (vis.js), ReactFlow JSON, or raw JSON.

Usage:
    python scripts/export_neptune_subgraph.py --focus JOURNAL_BASE --format mermaid
    python scripts/export_neptune_subgraph.py --focus PAYMENT_REQ --depth 2 --format html
    python scripts/export_neptune_subgraph.py --focus "応付管理" --format reactflow --max-nodes 30
    python scripts/export_neptune_subgraph.py --focus AP_FLOW --format mermaid --label-mode business

Formats:
    mermaid    - Mermaid flowchart (paste into docs or render)
    html       - Self-contained HTML with vis.js network visualization
    reactflow  - ReactFlow-compatible JSON (nodes + edges arrays)
    json       - Raw graph data as JSON

Special focus values:
    AP_FLOW       - Full AP business flow (main chain)
    Q4_SEMANTIC   - Q4 semantic map (curated 15-25 nodes)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from hermes_bedrock_agent.clients.neptune_client import NeptuneClient

RUN_ID = "murata_rebuild_v1"
DATASET = "murata"

# ======================================================================
# Graph Query Functions
# ======================================================================

def get_entity_subgraph(neptune, focus, depth=2, max_nodes=50, max_edges=80):
    """Get subgraph centered on focus entity."""
    # Find focus nodes
    result = neptune.execute_query(
        f"""MATCH (n {{run_id: '{RUN_ID}', dataset: '{DATASET}'}})
        WHERE n.canonical_name CONTAINS $focus OR n.entity_id CONTAINS $focus
        RETURN n.entity_id AS eid, n.canonical_name AS cname, labels(n) AS lbls
        LIMIT 5""",
        {"focus": focus}
    )
    focus_nodes = result.get("results", [])
    if not focus_nodes:
        return {"nodes": [], "edges": [], "error": f"No nodes found for: {focus}"}

    # Get neighbors
    all_nodes = {}
    all_edges = []
    for node in focus_nodes[:3]:
        eid = node["eid"]
        all_nodes[eid] = {"id": eid, "label": node["cname"], "labels": node.get("lbls", [])}

        nbr_result = neptune.execute_query(
            f"""MATCH (n {{entity_id: $eid, run_id: '{RUN_ID}'}})-[r]-(m {{run_id: '{RUN_ID}'}})
            RETURN n.entity_id AS src_id, n.canonical_name AS src_name,
                   type(r) AS rel, r.relation_id AS rid,
                   m.entity_id AS tgt_id, m.canonical_name AS tgt_name, labels(m) AS tgt_labels
            LIMIT $lim""",
            {"eid": eid, "lim": max_edges}
        )
        for edge in nbr_result.get("results", []):
            tgt_id = edge["tgt_id"]
            if tgt_id not in all_nodes and len(all_nodes) < max_nodes:
                all_nodes[tgt_id] = {"id": tgt_id, "label": edge["tgt_name"], "labels": edge.get("tgt_labels", [])}
            all_edges.append({
                "source": edge["src_id"],
                "target": edge["tgt_id"],
                "relation": edge["rel"],
                "id": edge.get("rid", ""),
            })

    return {"nodes": list(all_nodes.values()), "edges": all_edges}


def get_ap_flow_graph(neptune):
    """Get the AP business flow main chain."""
    result = neptune.execute_query(
        f"""MATCH (n {{run_id: '{RUN_ID}', dataset: '{DATASET}'}})
        WHERE n.canonical_name CONTAINS 'MS' OR n.canonical_name CONTAINS 'HULFT'
           OR n.canonical_name CONTAINS 'JOURNAL_BASE' OR n.canonical_name CONTAINS 'RECEIVING'
           OR n.canonical_name CONTAINS 'PAYMENT' OR n.canonical_name CONTAINS 'SUN'
           OR n.canonical_name CONTAINS '応付' OR n.canonical_name CONTAINS '付款'
           OR n.canonical_name CONTAINS '対帳' OR n.canonical_name CONTAINS '審批'
        RETURN n.entity_id AS eid, n.canonical_name AS cname, labels(n) AS lbls
        LIMIT 40""",
        {}
    )
    nodes = {}
    for n in result.get("results", []):
        nodes[n["eid"]] = {"id": n["eid"], "label": n["cname"], "labels": n.get("lbls", [])}

    # Get edges between these nodes
    eids = list(nodes.keys())[:30]
    edges = []
    for eid in eids[:15]:
        edge_result = neptune.execute_query(
            f"""MATCH (n {{entity_id: $eid, run_id: '{RUN_ID}'}})-[r]->(m {{run_id: '{RUN_ID}'}})
            RETURN n.entity_id AS src, type(r) AS rel, m.entity_id AS tgt, m.canonical_name AS tgt_name
            LIMIT 10""",
            {"eid": eid}
        )
        for e in edge_result.get("results", []):
            if e["tgt"] in nodes:
                edges.append({"source": eid, "target": e["tgt"], "relation": e["rel"]})

    return {"nodes": list(nodes.values()), "edges": edges}


def get_q4_semantic_map():
    """Generate curated Q4 semantic map (15-25 nodes, main chain)."""
    nodes = [
        {"id": "ms_system", "label": "MS系统/外部订単", "type": "ExternalSystem"},
        {"id": "hulft", "label": "HULFT転送", "type": "Integration"},
        {"id": "journal_base", "label": "JOURNAL_BASE", "type": "Table"},
        {"id": "receiving_list", "label": "RECEIVING_LIST/対帳単", "type": "Table"},
        {"id": "receiving_journal", "label": "RECEIVING_JOURNAL", "type": "Table"},
        {"id": "approval_1", "label": "対帳単審批", "type": "Process"},
        {"id": "payment_req", "label": "PAYMENT_REQ/付款申請", "type": "Table"},
        {"id": "approval_2", "label": "付款審批", "type": "Process"},
        {"id": "payment_receiving", "label": "PAYMENT_RECEIVING", "type": "Table"},
        {"id": "sun_request", "label": "SUN_REQUEST", "type": "Table"},
        {"id": "sun_erp", "label": "SUN ERP/支付", "type": "ExternalSystem"},
        {"id": "report", "label": "報表/支払出力", "type": "Output"},
        {"id": "custodian", "label": "CUSTODIAN/管理者", "type": "Role"},
        {"id": "client_entity", "label": "CLIENT_ENTITY/取引先", "type": "MasterData"},
        {"id": "oa_system", "label": "OA系統", "type": "ExternalSystem"},
    ]
    edges = [
        {"from": "ms_system", "to": "hulft", "relation": "generates"},
        {"from": "hulft", "to": "journal_base", "relation": "generates"},
        {"from": "journal_base", "to": "receiving_list", "relation": "generates"},
        {"from": "receiving_list", "to": "approval_1", "relation": "depends_on"},
        {"from": "approval_1", "to": "receiving_journal", "relation": "generates"},
        {"from": "receiving_journal", "to": "payment_req", "relation": "generates"},
        {"from": "payment_req", "to": "approval_2", "relation": "depends_on"},
        {"from": "approval_2", "to": "payment_receiving", "relation": "generates"},
        {"from": "payment_receiving", "to": "sun_request", "relation": "generates"},
        {"from": "sun_request", "to": "sun_erp", "relation": "generates"},
        {"from": "sun_erp", "to": "report", "relation": "generates"},
        {"from": "custodian", "to": "approval_1", "relation": "relates_to"},
        {"from": "custodian", "to": "approval_2", "relation": "relates_to"},
        {"from": "client_entity", "to": "payment_req", "relation": "relates_to"},
        {"from": "oa_system", "to": "approval_2", "relation": "relates_to"},
    ]
    return {"nodes": nodes, "edges": edges}


# ======================================================================
# Format Exporters
# ======================================================================

def to_mermaid(graph, label_mode="business", lang="zh"):
    """Convert graph to Mermaid flowchart."""
    lines = ["```mermaid", "flowchart TD"]

    # Node definitions
    for node in graph["nodes"]:
        nid = node["id"].replace("-", "_").replace(" ", "_")[:30]
        label = node["label"]
        if label_mode == "technical":
            label = node["id"]
        elif label_mode == "mixed":
            label = f"{node['label']} ({node['id'][:15]})"
        lines.append(f'    {nid}["{label}"]')

    lines.append("")

    # Edges
    for edge in graph["edges"]:
        src = (edge.get("source") or edge.get("from", "")).replace("-", "_").replace(" ", "_")[:30]
        tgt = (edge.get("target") or edge.get("to", "")).replace("-", "_").replace(" ", "_")[:30]
        rel = edge.get("relation", "")
        if rel:
            lines.append(f"    {src} -->|{rel}| {tgt}")
        else:
            lines.append(f"    {src} --> {tgt}")

    lines.append("```")
    return "\n".join(lines)


def to_html(graph, title="Graph Visualization"):
    """Convert graph to self-contained HTML with vis.js."""
    nodes_js = json.dumps([
        {"id": n["id"], "label": n["label"],
         "color": "#4fc3f7" if "Table" in str(n.get("labels", n.get("type", ""))) else
                  "#81c784" if "Process" in str(n.get("labels", n.get("type", ""))) else
                  "#ffb74d" if "External" in str(n.get("labels", n.get("type", ""))) else "#ce93d8"}
        for n in graph["nodes"]
    ], ensure_ascii=False)

    edges_js = json.dumps([
        {"from": e.get("source", e.get("from")),
         "to": e.get("target", e.get("to")),
         "label": e.get("relation", ""),
         "arrows": "to"}
        for e in graph["edges"]
    ], ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html><head>
<title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
body {{ margin: 0; padding: 20px; background: #1a1a2e; color: #eee; font-family: sans-serif; }}
h1 {{ text-align: center; color: #4fc3f7; }}
#graph {{ width: 100%; height: 80vh; border: 1px solid #333; border-radius: 8px; }}
.legend {{ display: flex; gap: 20px; justify-content: center; margin: 10px; }}
.legend span {{ padding: 4px 12px; border-radius: 4px; font-size: 12px; }}
</style>
</head><body>
<h1>{title}</h1>
<div class="legend">
  <span style="background:#4fc3f7;color:#000">Table</span>
  <span style="background:#81c784;color:#000">Process</span>
  <span style="background:#ffb74d;color:#000">External</span>
  <span style="background:#ce93d8;color:#000">Other</span>
</div>
<div id="graph"></div>
<script>
var nodes = new vis.DataSet({nodes_js});
var edges = new vis.DataSet({edges_js});
var container = document.getElementById('graph');
var data = {{ nodes: nodes, edges: edges }};
var options = {{
  nodes: {{ shape: 'box', font: {{ size: 14, color: '#fff' }}, borderWidth: 2 }},
  edges: {{ font: {{ size: 10, color: '#aaa' }}, color: '#666' }},
  physics: {{ solver: 'forceAtlas2Based', stabilization: {{ iterations: 100 }} }},
  layout: {{ improvedLayout: true }}
}};
new vis.Network(container, data, options);
</script>
</body></html>"""
    return html


def to_reactflow(graph):
    """Convert graph to ReactFlow JSON format."""
    rf_nodes = []
    for i, node in enumerate(graph["nodes"]):
        rf_nodes.append({
            "id": node["id"],
            "type": "default",
            "position": {"x": (i % 5) * 200, "y": (i // 5) * 120},
            "data": {"label": node["label"]},
            "style": {
                "background": "#4fc3f7" if "Table" in str(node.get("labels", node.get("type", ""))) else
                              "#81c784" if "Process" in str(node.get("labels", node.get("type", ""))) else "#ffb74d",
                "color": "#000",
                "border": "1px solid #333",
                "borderRadius": "8px",
                "padding": "10px",
            }
        })

    rf_edges = []
    for i, edge in enumerate(graph["edges"]):
        rf_edges.append({
            "id": f"e{i}",
            "source": edge.get("source", edge.get("from")),
            "target": edge.get("target", edge.get("to")),
            "label": edge.get("relation", ""),
            "type": "smoothstep",
            "animated": True if edge.get("relation") == "generates" else False,
        })

    return {"nodes": rf_nodes, "edges": rf_edges}


# ======================================================================
# Main
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Neptune Subgraph Exporter")
    parser.add_argument("--focus", "-f", required=True,
                       help="Focus entity (e.g. JOURNAL_BASE, PAYMENT_REQ, AP_FLOW, Q4_SEMANTIC)")
    parser.add_argument("--depth", "-d", type=int, default=2, help="Traversal depth")
    parser.add_argument("--max-nodes", type=int, default=50, help="Max nodes")
    parser.add_argument("--max-edges", type=int, default=80, help="Max edges")
    parser.add_argument("--format", choices=["mermaid", "html", "reactflow", "json"], default="mermaid")
    parser.add_argument("--lang", choices=["zh", "ja", "en", "auto"], default="zh")
    parser.add_argument("--label-mode", choices=["business", "technical", "mixed"], default="business")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    # Get graph data
    if args.focus == "Q4_SEMANTIC":
        print("  Using curated Q4 Semantic Map...")
        graph = get_q4_semantic_map()
    elif args.focus == "AP_FLOW":
        print("  Querying Neptune for AP business flow...")
        neptune = NeptuneClient()
        graph = get_ap_flow_graph(neptune)
    else:
        print(f"  Querying Neptune for subgraph around: {args.focus}...")
        neptune = NeptuneClient()
        graph = get_entity_subgraph(neptune, args.focus, args.depth, args.max_nodes, args.max_edges)

    print(f"  Graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")

    # Export
    if args.format == "mermaid":
        output = to_mermaid(graph, args.label_mode, args.lang)
    elif args.format == "html":
        output = to_html(graph, title=f"Murata GraphRAG — {args.focus}")
    elif args.format == "reactflow":
        output = json.dumps(to_reactflow(graph), ensure_ascii=False, indent=2)
    else:
        output = json.dumps(graph, ensure_ascii=False, indent=2)

    # Save or print
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"  ✅ Saved to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
