"""
Excel Graph Visualization Builder — generates interactive HTML knowledge graphs
using vis-network (CDN) with embedded graph JSON data.

Generates multiple focused HTML views:
- full: all nodes + relationships
- core: graph without EvidenceChunk nodes
- field_mapping: System/Message/Column/MAPS_TO/HAS_FIELD
- business_implementation: cross-layer business+implementation view
- evidence: graph nodes -> HAS_EVIDENCE -> EvidenceChunk
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Color schemes by label
NODE_COLORS = {
    # Business layer
    "BusinessDomain": "#4CAF50",
    "BusinessProcess": "#66BB6A",
    "Function": "#81C784",
    "BusinessRule": "#A5D6A7",
    "BusinessTerm": "#C8E6C9",
    # Implementation layer
    "System": "#2196F3",
    "Message": "#42A5F5",
    "Column": "#90CAF9",
    "File": "#64B5F6",
    "API": "#BBDEFB",
    "DataType": "#E3F2FD",
    "Attribute": "#B3E5FC",
    # Evidence layer
    "EvidenceChunk": "#FFF9C4",
    # Default
    "Unknown": "#E0E0E0",
}

NODE_SHAPES = {
    "BusinessDomain": "diamond",
    "BusinessProcess": "hexagon",
    "Function": "triangle",
    "BusinessRule": "square",
    "BusinessTerm": "dot",
    "System": "star",
    "Message": "box",
    "Column": "dot",
    "File": "triangleDown",
    "API": "diamond",
    "EvidenceChunk": "ellipse",
}

EDGE_COLORS = {
    "MAPS_TO": "#FF5722",
    "HAS_FIELD": "#607D8B",
    "HAS_EVIDENCE": "#BDBDBD",
    "RELATED_TO": "#9C27B0",
    "HAS_RULE": "#4CAF50",
    "HAS_TERM": "#8BC34A",
    "CONTAINS": "#795548",
    "HAS_FUNCTION": "#009688",
}

EDGE_DASHES = {
    "HAS_EVIDENCE": True,
    "RELATED_TO": [5, 5],
}


class ExcelGraphVisualizationBuilder:
    """Build interactive HTML graph visualizations."""

    def __init__(
        self,
        nodes: list[dict],
        edges: list[dict],
        output_dir: str | Path,
        run_id: str = "",
        dataset: str = "",
    ):
        self.all_nodes = nodes
        self.all_edges = edges
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.dataset = dataset
        self.generated_files: list[str] = []

    def build_all(self) -> list[str]:
        """Generate all HTML visualization files."""
        self._build_full_graph()
        self._build_core_graph()
        self._build_field_mapping_graph()
        self._build_business_implementation_graph()
        self._build_evidence_graph()
        self._export_vis_data()
        self._export_mermaid()
        return self.generated_files

    def _build_full_graph(self):
        """Full graph with all nodes and edges."""
        html = self._generate_html(
            title="Excel Knowledge Graph — Full",
            nodes=self.all_nodes,
            edges=self.all_edges,
            description="Full graph: all nodes and relationships including evidence",
        )
        path = self.output_dir / "excel_knowledge_graph_full.html"
        path.write_text(html, encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s (%d nodes, %d edges)", path.name, len(self.all_nodes), len(self.all_edges))

    def _build_core_graph(self):
        """Core graph without EvidenceChunk nodes and HAS_EVIDENCE edges."""
        nodes = [n for n in self.all_nodes if n.get("label") != "EvidenceChunk"]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.all_edges
                 if e.get("type") != "HAS_EVIDENCE"
                 and e.get("source") in node_ids
                 and e.get("target") in node_ids]
        html = self._generate_html(
            title="Excel Knowledge Graph — Core",
            nodes=nodes,
            edges=edges,
            description="Core graph: business + implementation without evidence chunks",
        )
        path = self.output_dir / "excel_knowledge_graph_core.html"
        path.write_text(html, encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s (%d nodes, %d edges)", path.name, len(nodes), len(edges))

    def _build_field_mapping_graph(self):
        """Focus on field mapping: System/Message/Column/MAPS_TO/HAS_FIELD."""
        target_labels = {"System", "Message", "Column", "File", "API"}
        target_rels = {"MAPS_TO", "HAS_FIELD", "CONTAINS"}
        nodes = [n for n in self.all_nodes if n.get("label") in target_labels]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.all_edges
                 if e.get("type") in target_rels
                 and e.get("source") in node_ids
                 and e.get("target") in node_ids]
        html = self._generate_html(
            title="Excel Field Mapping Graph",
            nodes=nodes,
            edges=edges,
            description="SAP ↔ 中間F ↔ Andpad field mapping visualization",
        )
        path = self.output_dir / "excel_field_mapping_graph.html"
        path.write_text(html, encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s (%d nodes, %d edges)", path.name, len(nodes), len(edges))

    def _build_business_implementation_graph(self):
        """Cross-layer business+implementation graph."""
        target_labels = {
            "BusinessDomain", "BusinessProcess", "Function",
            "BusinessTerm", "BusinessRule",
            "System", "Message", "Column",
        }
        target_rels = {
            "RELATED_TO", "HAS_RULE", "HAS_TERM", "HAS_FIELD",
            "MAPS_TO", "HAS_FUNCTION", "CONTAINS",
        }
        nodes = [n for n in self.all_nodes if n.get("label") in target_labels]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.all_edges
                 if e.get("type") in target_rels
                 and e.get("source") in node_ids
                 and e.get("target") in node_ids]
        html = self._generate_html(
            title="Excel Business → Implementation Graph",
            nodes=nodes,
            edges=edges,
            description="Business semantics connected to implementation mapping",
        )
        path = self.output_dir / "excel_business_to_implementation_graph.html"
        path.write_text(html, encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s (%d nodes, %d edges)", path.name, len(nodes), len(edges))

    def _build_evidence_graph(self):
        """Evidence traceability: graph nodes -> HAS_EVIDENCE -> EvidenceChunk."""
        evidence_edges = [e for e in self.all_edges if e.get("type") == "HAS_EVIDENCE"]
        # Collect node IDs involved
        involved_ids = set()
        for e in evidence_edges:
            involved_ids.add(e["source"])
            involved_ids.add(e["target"])
        nodes = [n for n in self.all_nodes if n["id"] in involved_ids]
        html = self._generate_html(
            title="Excel Evidence Traceability Graph",
            nodes=nodes,
            edges=evidence_edges,
            description="Source traceability: graph nodes → HAS_EVIDENCE → EvidenceChunk (sheet/cell_range)",
        )
        path = self.output_dir / "excel_evidence_graph.html"
        path.write_text(html, encoding="utf-8")
        self.generated_files.append(str(path))
        logger.info("Generated: %s (%d nodes, %d edges)", path.name, len(nodes), len(evidence_edges))

    def _export_vis_data(self):
        """Export raw vis data JSON for all views."""
        views = {
            "graph_full_vis_data.json": (self.all_nodes, self.all_edges),
            "graph_core_vis_data.json": (
                [n for n in self.all_nodes if n.get("label") != "EvidenceChunk"],
                [e for e in self.all_edges if e.get("type") != "HAS_EVIDENCE"],
            ),
        }
        for filename, (nodes, edges) in views.items():
            path = self.output_dir / filename
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"nodes": self._to_vis_nodes(nodes), "edges": self._to_vis_edges(edges)},
                    f, ensure_ascii=False, indent=2,
                )
            self.generated_files.append(str(path))

    def _export_mermaid(self):
        """Export Mermaid diagram for core (non-Column) graph."""
        # Only top-level nodes for readability
        top_labels = {"System", "Message", "Function", "BusinessDomain", "BusinessProcess", "File"}
        nodes = [n for n in self.all_nodes if n.get("label") in top_labels]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.all_edges
                 if e.get("source") in node_ids and e.get("target") in node_ids
                 and e.get("type") != "HAS_EVIDENCE"]

        lines = ["graph TD"]
        # Node definitions
        id_map = {}
        for i, n in enumerate(nodes):
            safe_id = f"N{i}"
            id_map[n["id"]] = safe_id
            display = n.get("display_name") or n.get("name") or n["id"][:8]
            label_type = n.get("label", "")
            lines.append(f"    {safe_id}[\"{display}<br/><small>{label_type}</small>\"]")

        # Edge definitions
        for e in edges:
            src = id_map.get(e["source"])
            tgt = id_map.get(e["target"])
            if src and tgt:
                rel = e.get("type", "")
                lines.append(f"    {src} -->|{rel}| {tgt}")

        mmd_path = self.output_dir / "excel_core_graph.mmd"
        mmd_path.write_text("\n".join(lines), encoding="utf-8")
        self.generated_files.append(str(mmd_path))
        logger.info("Generated Mermaid: %s (%d nodes, %d edges)", mmd_path.name, len(nodes), len(edges))

    def _to_vis_nodes(self, nodes: list[dict]) -> list[dict]:
        """Convert to vis-network node format."""
        vis_nodes = []
        for n in nodes:
            label = n.get("label", "Unknown")
            display = n.get("display_name") or n.get("name") or n["id"][:12]
            vis_nodes.append({
                "id": n["id"],
                "label": display[:30],
                "title": self._node_tooltip(n),
                "group": label,
                "color": NODE_COLORS.get(label, NODE_COLORS["Unknown"]),
                "shape": NODE_SHAPES.get(label, "dot"),
                "size": max(8, min(30, 8 + n.get("evidence_count", 0) * 2)),
                "font": {"size": 10 if label == "Column" else 12},
            })
        return vis_nodes

    def _to_vis_edges(self, edges: list[dict]) -> list[dict]:
        """Convert to vis-network edge format."""
        vis_edges = []
        for e in edges:
            rel = e.get("type", "")
            vis_edge: dict[str, Any] = {
                "from": e["source"],
                "to": e["target"],
                "label": rel,
                "title": self._edge_tooltip(e),
                "color": {"color": EDGE_COLORS.get(rel, "#999999")},
                "arrows": "to",
                "font": {"size": 8, "align": "middle"},
            }
            if rel in EDGE_DASHES:
                vis_edge["dashes"] = EDGE_DASHES[rel]
            if rel == "HAS_EVIDENCE":
                vis_edge["width"] = 0.5
                vis_edge["font"]["size"] = 0
            vis_edges.append(vis_edge)
        return vis_edges

    def _node_tooltip(self, n: dict) -> str:
        """Generate HTML tooltip for a node."""
        parts = [
            f"<b>{n.get('display_name') or n.get('name', '')}</b>",
            f"Label: {n.get('label', '')}",
            f"Layer: {n.get('layer', '')}",
            f"Confidence: {n.get('confidence', 0):.2f}",
            f"Evidence: {n.get('evidence_count', 0)}",
        ]
        if n.get("sheet_name"):
            parts.append(f"Sheet: {n['sheet_name']}")
        if n.get("cell_range"):
            parts.append(f"Range: {n['cell_range']}")
        if n.get("text_preview"):
            parts.append(f"Preview: {n['text_preview'][:100]}")
        if n.get("description"):
            parts.append(f"Desc: {n['description'][:100]}")
        return "<br>".join(parts)

    def _edge_tooltip(self, e: dict) -> str:
        """Generate HTML tooltip for an edge."""
        parts = [
            f"<b>{e.get('type', '')}</b>",
            f"Layer: {e.get('layer', '')}",
            f"Confidence: {e.get('confidence', 0):.2f}",
            f"Evidence: {e.get('evidence_count', 0)}",
        ]
        return "<br>".join(parts)

    def _generate_html(
        self,
        title: str,
        nodes: list[dict],
        edges: list[dict],
        description: str = "",
    ) -> str:
        """Generate self-contained HTML with vis-network."""
        vis_nodes = self._to_vis_nodes(nodes)
        vis_edges = self._to_vis_edges(edges)

        # Statistics
        label_counts = Counter(n.get("label", "Unknown") for n in nodes)
        rel_counts = Counter(e.get("type", "Unknown") for e in edges)

        stats_html = "<br>".join(
            f"{label}: {count}" for label, count in
            sorted(label_counts.items(), key=lambda x: -x[1])
        )
        rel_stats_html = "<br>".join(
            f"{rel}: {count}" for rel, count in
            sorted(rel_counts.items(), key=lambda x: -x[1])
        )

        # Legend HTML
        legend_items = []
        for label in sorted(label_counts.keys()):
            color = NODE_COLORS.get(label, NODE_COLORS["Unknown"])
            legend_items.append(
                f'<span style="display:inline-block;width:12px;height:12px;'
                f'background:{color};margin-right:4px;border-radius:2px;"></span>{label}'
            )
        legend_html = " &nbsp; ".join(legend_items)

        nodes_json = json.dumps(vis_nodes, ensure_ascii=False)
        edges_json = json.dumps(vis_edges, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; }}
#header {{ padding: 12px 20px; background: #16213e; border-bottom: 1px solid #333; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
#header h1 {{ font-size: 16px; white-space: nowrap; }}
#header .desc {{ font-size: 12px; color: #aaa; }}
#controls {{ padding: 8px 20px; background: #0f3460; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
#controls input, #controls select, #controls button {{ font-size: 12px; padding: 4px 8px; border: 1px solid #555; border-radius: 4px; background: #1a1a2e; color: #eee; }}
#controls button {{ cursor: pointer; background: #2196F3; border: none; color: white; }}
#controls button:hover {{ background: #1976D2; }}
#graph-container {{ width: 100%; height: calc(100vh - 140px); }}
#sidebar {{ position: fixed; right: 0; top: 80px; width: 320px; max-height: calc(100vh - 100px); overflow-y: auto; background: #16213e; border-left: 1px solid #333; padding: 12px; font-size: 11px; display: none; z-index: 10; }}
#sidebar.show {{ display: block; }}
#sidebar h3 {{ margin-bottom: 8px; color: #64B5F6; }}
#sidebar .prop {{ margin: 4px 0; }}
#sidebar .prop-key {{ color: #aaa; }}
#sidebar .prop-val {{ color: #eee; word-break: break-all; }}
#legend {{ padding: 4px 20px; font-size: 11px; background: #0a0a1a; border-top: 1px solid #333; }}
#stats {{ position: fixed; left: 10px; bottom: 40px; background: rgba(22,33,62,0.9); padding: 8px 12px; border-radius: 6px; font-size: 11px; max-width: 200px; }}
</style>
</head>
<body>
<div id="header">
  <h1>{title}</h1>
  <span class="desc">{description} | run_id={self.run_id} | dataset={self.dataset}</span>
</div>
<div id="controls">
  <input type="text" id="search" placeholder="Search node name..." style="width:200px">
  <select id="labelFilter"><option value="">All Labels</option></select>
  <select id="relFilter"><option value="">All Relations</option></select>
  <button onclick="toggleEvidence()">Toggle Evidence</button>
  <button onclick="fitGraph()">Fit</button>
  <button onclick="resetView()">Reset</button>
</div>
<div id="graph-container"></div>
<div id="sidebar">
  <h3 id="sidebar-title">Properties</h3>
  <div id="sidebar-content"></div>
</div>
<div id="legend">{legend_html}</div>
<div id="stats">
  <b>Nodes:</b> {len(nodes)}<br>
  <b>Edges:</b> {len(edges)}<br>
  <b>Labels:</b><br>{stats_html}<br>
  <b>Relations:</b><br>{rel_stats_html}
</div>

<script>
const nodesData = {nodes_json};
const edgesData = {edges_json};

let allNodes = new vis.DataSet(nodesData);
let allEdges = new vis.DataSet(edgesData);
let evidenceHidden = false;

const container = document.getElementById('graph-container');
const data = {{ nodes: allNodes, edges: allEdges }};
const options = {{
  physics: {{
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {{ gravitationalConstant: -50, centralGravity: 0.01, springLength: 100 }},
    stabilization: {{ iterations: 150 }},
  }},
  interaction: {{ hover: true, tooltipDelay: 200, navigationButtons: true }},
  edges: {{ smooth: {{ type: 'continuous' }}, font: {{ size: 8 }} }},
  nodes: {{ font: {{ size: 11, color: '#eee' }} }},
}};
const network = new vis.Network(container, data, options);

// Populate filters
const labels = [...new Set(nodesData.map(n => n.group))].sort();
const rels = [...new Set(edgesData.map(e => e.label))].sort();
const labelSel = document.getElementById('labelFilter');
const relSel = document.getElementById('relFilter');
labels.forEach(l => {{ const o = document.createElement('option'); o.value = l; o.text = l; labelSel.add(o); }});
rels.forEach(r => {{ const o = document.createElement('option'); o.value = r; o.text = r; relSel.add(o); }});

// Search
document.getElementById('search').addEventListener('input', function(e) {{
  const q = e.target.value.toLowerCase();
  if (!q) {{ allNodes.forEach(n => allNodes.update({{id: n.id, hidden: false}})); return; }}
  allNodes.forEach(n => {{
    const match = (n.label || '').toLowerCase().includes(q) || (n.title || '').toLowerCase().includes(q);
    allNodes.update({{id: n.id, hidden: !match}});
  }});
}});

// Label filter
labelSel.addEventListener('change', function(e) {{
  const v = e.target.value;
  if (!v) {{ allNodes.forEach(n => allNodes.update({{id: n.id, hidden: false}})); return; }}
  allNodes.forEach(n => {{ allNodes.update({{id: n.id, hidden: n.group !== v}}); }});
}});

// Relation filter
relSel.addEventListener('change', function(e) {{
  const v = e.target.value;
  if (!v) {{ allEdges.forEach(ed => allEdges.update({{id: ed.id, hidden: false}})); return; }}
  allEdges.forEach(ed => {{ allEdges.update({{id: ed.id, hidden: ed.label !== v}}); }});
}});

function toggleEvidence() {{
  evidenceHidden = !evidenceHidden;
  allNodes.forEach(n => {{
    if (n.group === 'EvidenceChunk') allNodes.update({{id: n.id, hidden: evidenceHidden}});
  }});
  allEdges.forEach(ed => {{
    if (ed.label === 'HAS_EVIDENCE') allEdges.update({{id: ed.id, hidden: evidenceHidden}});
  }});
}}

function fitGraph() {{ network.fit(); }}
function resetView() {{
  document.getElementById('search').value = '';
  labelSel.value = '';
  relSel.value = '';
  evidenceHidden = false;
  allNodes.forEach(n => allNodes.update({{id: n.id, hidden: false}}));
  allEdges.forEach(ed => allEdges.update({{id: ed.id, hidden: false}}));
  network.fit();
}}

// Click to show properties
network.on('click', function(params) {{
  const sidebar = document.getElementById('sidebar');
  const content = document.getElementById('sidebar-content');
  const title = document.getElementById('sidebar-title');
  if (params.nodes.length > 0) {{
    const nodeId = params.nodes[0];
    const node = allNodes.get(nodeId);
    title.textContent = node.label + ' (Node)';
    content.innerHTML = Object.entries(node).map(([k,v]) =>
      '<div class="prop"><span class="prop-key">' + k + ':</span> <span class="prop-val">' + String(v).substring(0, 200) + '</span></div>'
    ).join('');
    sidebar.classList.add('show');
  }} else if (params.edges.length > 0) {{
    const edgeId = params.edges[0];
    const edge = allEdges.get(edgeId);
    title.textContent = edge.label + ' (Edge)';
    content.innerHTML = Object.entries(edge).map(([k,v]) =>
      '<div class="prop"><span class="prop-key">' + k + ':</span> <span class="prop-val">' + String(v).substring(0, 200) + '</span></div>'
    ).join('');
    sidebar.classList.add('show');
  }} else {{
    sidebar.classList.remove('show');
  }}
}});
</script>
</body>
</html>"""
