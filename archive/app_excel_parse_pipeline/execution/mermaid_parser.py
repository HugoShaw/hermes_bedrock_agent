"""Mermaid file parser.

Parses .mmd/.mermaid files to extract flow nodes and edges.
When a manual Mermaid file exists, it is treated as the AUTHORITATIVE
source for flowchart structure (confidence=1.0).
"""
import json
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_mermaid_file(file_path: str, related_workbook: str = "", related_sheet: str = "") -> dict:
    """Parse a Mermaid file and extract flow nodes and edges.
    
    Returns a dict with nodes, edges, and metadata.
    Manual Mermaid files are authoritative (confidence=1.0).
    """
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    # Detect graph type
    graph_type = _detect_graph_type(content)
    
    # Extract nodes and edges
    nodes = _extract_nodes(content)
    edges = _extract_edges(content)

    # Extract subgraphs
    subgraphs = _extract_subgraphs(content)

    return {
        "source_file": str(path),
        "source_type": "manual_mermaid",
        "graph_type": graph_type,
        "confidence": 1.0,
        "related_workbook": related_workbook,
        "related_sheet": related_sheet,
        "nodes": nodes,
        "edges": edges,
        "subgraphs": subgraphs,
        "raw_content": content,
    }


def _detect_graph_type(content: str) -> str:
    """Detect Mermaid diagram type."""
    first_lines = content.strip().split("\n")[:5]
    for line in first_lines:
        line_lower = line.strip().lower()
        if line_lower.startswith("graph") or line_lower.startswith("flowchart"):
            return "flowchart"
        elif line_lower.startswith("sequencediagram"):
            return "sequence"
        elif line_lower.startswith("classDiagram"):
            return "class"
        elif line_lower.startswith("statediagram"):
            return "state"
    return "flowchart"  # default


def _extract_nodes(content: str) -> list:
    """Extract node definitions from Mermaid content."""
    nodes = []
    seen_ids = set()

    # Pattern: NodeID[Label] or NodeID(Label) or NodeID{Label} or NodeID((Label))
    # Also: NodeID["Label"] 
    patterns = [
        r'(\w+)\["([^"]+)"\]',          # node["label"]
        r'(\w+)\[([^\]]+)\]',            # node[label]
        r"(\w+)\(\"([^\"]+)\"\)",         # node("label")
        r'(\w+)\(([^)]+)\)',             # node(label)
        r'(\w+)\{([^}]+)\}',            # node{label} (decision)
        r'(\w+)\(\(([^)]+)\)\)',         # node((label)) (circle)
        r'(\w+)>([^\]]+)\]',            # node>label] (flag)
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, content):
            node_id = match.group(1).strip()
            label = match.group(2).strip()

            # Skip keywords
            if node_id.lower() in ("graph", "flowchart", "subgraph", "end", "direction", 
                                     "td", "lr", "rl", "bt", "tb", "style", "classDef",
                                     "class", "click", "linkStyle"):
                continue

            if node_id not in seen_ids:
                seen_ids.add(node_id)
                nodes.append({
                    "node_id": node_id,
                    "label": label,
                    "node_type": _infer_node_type(label),
                    "source_type": "manual_mermaid",
                    "confidence": 1.0,
                })

    # Also find nodes that only appear in edges (no explicit definition)
    edge_node_pattern = r'(\w+)\s*(?:-->|---|-\.->|==>|--[>\|])'
    for match in re.finditer(edge_node_pattern, content):
        node_id = match.group(1).strip()
        if node_id.lower() not in ("graph", "flowchart", "subgraph", "end", "direction",
                                     "td", "lr", "rl", "bt", "tb", "style"):
            if node_id not in seen_ids:
                seen_ids.add(node_id)
                nodes.append({
                    "node_id": node_id,
                    "label": node_id,
                    "node_type": "process",
                    "source_type": "manual_mermaid",
                    "confidence": 1.0,
                })

    return nodes


def _extract_edges(content: str) -> list:
    """Extract edges from Mermaid content."""
    edges = []

    # Patterns for edges:
    # A --> B
    # A -->|label| B
    # A -- label --> B
    # A -.-> B (dotted)
    # A ==> B (thick)
    edge_patterns = [
        # A -->|label| B
        r'(\w+)\s*-->\|([^|]*)\|\s*(\w+)',
        # A -- label --> B
        r'(\w+)\s*--\s*([^-]+?)\s*-->\s*(\w+)',
        # A --> B (no label)
        r'(\w+)\s*-->\s*(\w+)',
        # A -.->|label| B  
        r'(\w+)\s*-\.?->\|([^|]*)\|\s*(\w+)',
        # A -.-> B
        r'(\w+)\s*-\.?->\s*(\w+)',
        # A ==>|label| B
        r'(\w+)\s*==>\|([^|]*)\|\s*(\w+)',
        # A ==> B
        r'(\w+)\s*==>\s*(\w+)',
    ]

    for i, pattern in enumerate(edge_patterns):
        for match in re.finditer(pattern, content):
            groups = match.groups()
            
            if len(groups) == 3:
                source = groups[0].strip()
                label = groups[1].strip()
                target = groups[2].strip()
            elif len(groups) == 2:
                source = groups[0].strip()
                target = groups[1].strip()
                label = ""
            else:
                continue

            # Skip keywords
            skip_words = {"graph", "flowchart", "subgraph", "end", "direction",
                         "td", "lr", "rl", "bt", "tb", "style"}
            if source.lower() in skip_words or target.lower() in skip_words:
                continue

            edge_type = "flow"
            if "-." in pattern or "dotted" in label.lower():
                edge_type = "conditional"
            elif "==" in pattern:
                edge_type = "strong"

            edges.append({
                "edge_id": f"e_{source}_{target}_{len(edges)}",
                "source_node": source,
                "target_node": target,
                "label": label,
                "edge_type": edge_type,
                "source_type": "manual_mermaid",
                "confidence": 1.0,
            })

    return edges


def _extract_subgraphs(content: str) -> list:
    """Extract subgraph definitions."""
    subgraphs = []
    pattern = r'subgraph\s+(.+?)[\n\r]'
    
    for match in re.finditer(pattern, content):
        name = match.group(1).strip()
        # Remove brackets if present
        name = re.sub(r'\[([^\]]+)\]', r'\1', name)
        subgraphs.append({"name": name})

    return subgraphs


def _infer_node_type(label: str) -> str:
    """Infer node type from label text (generic, not business-specific)."""
    label_lower = label.lower()
    
    # Decision indicators
    if any(w in label_lower for w in ["判断", "判定", "条件", "if ", "check", "?", "condition"]):
        return "decision"
    
    # Start/end indicators
    if any(w in label_lower for w in ["開始", "start", "begin", "初期"]):
        return "start"
    if any(w in label_lower for w in ["終了", "end", "完了", "finish"]):
        return "end"
    
    # Error/exception
    if any(w in label_lower for w in ["エラー", "error", "異常", "exception"]):
        return "error"
    
    return "process"


def save_mermaid_results(mermaid_data: list, output_dir: Path) -> dict:
    """Save parsed Mermaid results."""
    structured_dir = output_dir / "structured"
    structured_dir.mkdir(parents=True, exist_ok=True)

    # Flow nodes
    nodes_path = structured_dir / "flow_nodes.jsonl"
    edges_path = structured_dir / "flow_edges.jsonl"
    sources_path = structured_dir / "mermaid_sources.jsonl"

    all_nodes = []
    all_edges = []

    with open(sources_path, "w", encoding="utf-8") as f:
        for mermaid in mermaid_data:
            source_record = {
                "source_file": mermaid["source_file"],
                "source_type": "manual_mermaid",
                "graph_type": mermaid["graph_type"],
                "related_workbook": mermaid.get("related_workbook", ""),
                "related_sheet": mermaid.get("related_sheet", ""),
                "node_count": len(mermaid["nodes"]),
                "edge_count": len(mermaid["edges"]),
                "subgraph_count": len(mermaid.get("subgraphs", [])),
                "confidence": 1.0,
            }
            f.write(json.dumps(source_record, ensure_ascii=False) + "\n")

            for node in mermaid["nodes"]:
                node["mermaid_file"] = mermaid["source_file"]
                all_nodes.append(node)

            for edge in mermaid["edges"]:
                edge["mermaid_file"] = mermaid["source_file"]
                all_edges.append(edge)

    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in all_nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in all_edges:
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    return {
        "flow_nodes": {"path": str(nodes_path), "count": len(all_nodes)},
        "flow_edges": {"path": str(edges_path), "count": len(all_edges)},
        "mermaid_sources": {"path": str(sources_path), "count": len(mermaid_data)},
    }
