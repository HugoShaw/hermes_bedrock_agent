"""Semantic Mermaid builder - generates Mermaid from flow_spec, NOT from raw connectors.

Key principles:
- Only flow_spec nodes with is_flow_node=True become Mermaid nodes
- Edge labels become |"label"| on edges, NOT nodes
- Decisions use diamond syntax {...}
- Start/end use stadium syntax ([...])
- Regions become subgraphs
- Semantic IDs are used instead of N001
- LR direction for wide flowcharts
"""
import re
import logging
from .flow_spec_models import (
    FlowSpec, FlowNode, FlowEdge, FlowLane,
    NodeType, NodeRole, EdgeType, ReviewStatus
)

logger = logging.getLogger(__name__)


def build_mermaid_from_flow_spec(flow_spec: FlowSpec,
                                 direction: str = "LR",
                                 include_subgraphs: bool = True,
                                 include_annotations: bool = False) -> str:
    """Generate Mermaid diagram from a semantic flow specification.
    
    Args:
        flow_spec: The semantic flow specification
        direction: Flow direction (LR, TD, etc.)
        include_subgraphs: Whether to wrap regions as subgraphs
        include_annotations: Whether to include annotation nodes
    """
    lines = [f"flowchart {direction}"]
    lines.append("")
    
    # Group nodes by region/lane
    region_nodes = {}
    ungrouped_nodes = []
    
    for node in flow_spec.nodes:
        if node.review_status == ReviewStatus.EXCLUDE:
            continue
        if node.role == NodeRole.ANNOTATION and not include_annotations:
            continue
        if node.role == NodeRole.EDGE_LABEL:
            continue  # Never render edge labels as nodes
        if node.role == NodeRole.CONTAINER:
            continue  # Containers are subgraphs, not nodes
        
        if node.region_id and node.region_id != "main_flow":
            if node.region_id not in region_nodes:
                region_nodes[node.region_id] = []
            region_nodes[node.region_id].append(node)
        else:
            ungrouped_nodes.append(node)
    
    # Render ungrouped (main flow) nodes first
    if ungrouped_nodes:
        lines.append("    %% Main Flow")
        for node in ungrouped_nodes:
            lines.append(f"    {_render_node(node)}")
        lines.append("")
    
    # Render region subgraphs
    if include_subgraphs and region_nodes:
        for lane in flow_spec.lanes:
            if lane.lane_id in region_nodes:
                nodes_in_lane = region_nodes[lane.lane_id]
                safe_title = _sanitize_text(lane.title)
                lines.append(f"    subgraph {_safe_id(lane.lane_id)}[\"{safe_title}\"]")
                for node in nodes_in_lane:
                    lines.append(f"        {_render_node(node)}")
                lines.append("    end")
                lines.append("")
    
    # Render edges
    lines.append("    %% Edges")
    for edge in flow_spec.edges:
        if edge.review_status == ReviewStatus.EXCLUDE:
            continue
        line = _render_edge(edge)
        if line:
            lines.append(f"    {line}")
    
    return "\n".join(lines) + "\n"


def build_region_mermaid(flow_spec: FlowSpec, region_id: str,
                         direction: str = "TD") -> str:
    """Generate Mermaid for a single region."""
    # Filter to region nodes and edges
    region_nodes = [n for n in flow_spec.nodes 
                    if n.region_id == region_id
                    and n.role not in (NodeRole.EDGE_LABEL, NodeRole.CONTAINER)
                    and n.review_status != ReviewStatus.EXCLUDE]
    
    region_node_ids = set(n.node_id for n in region_nodes)
    
    # Include edges where both endpoints are in this region
    # OR edges connecting this region to main flow
    region_edges = [e for e in flow_spec.edges
                    if e.from_node_id in region_node_ids 
                    or e.to_node_id in region_node_ids]
    
    if not region_nodes:
        return ""
    
    # Find region title
    title = region_id
    for lane in flow_spec.lanes:
        if lane.lane_id == region_id:
            title = lane.title
            break
    
    lines = [f"flowchart {direction}"]
    lines.append(f"    %% Region: {title}")
    lines.append("")
    
    for node in region_nodes:
        lines.append(f"    {_render_node(node)}")
    
    lines.append("")
    
    for edge in region_edges:
        if edge.review_status == ReviewStatus.EXCLUDE:
            continue
        line = _render_edge(edge)
        if line:
            lines.append(f"    {line}")
    
    return "\n".join(lines) + "\n"


def _render_node(node: FlowNode) -> str:
    """Render a single node in Mermaid syntax."""
    nid = _safe_id(node.node_id)
    text = _sanitize_text(node.text)
    
    # Replace newlines with <br/>
    text = text.replace("\n", "<br/>")
    
    if node.node_type == NodeType.START:
        return f'{nid}(["{text}"])'
    elif node.node_type == NodeType.END:
        return f'{nid}(["{text}"])'
    elif node.node_type == NodeType.DECISION:
        return f'{nid}{{"{text}"}}'
    elif node.node_type == NodeType.LOOP:
        return f'{nid}[["{text}"]]'
    elif node.node_type == NodeType.DATA:
        return f'{nid}[/"{text}"/]'
    elif node.node_type == NodeType.DB:
        return f'{nid}[("{text}")]'
    else:
        return f'{nid}["{text}"]'


def _render_edge(edge: FlowEdge) -> str:
    """Render a single edge in Mermaid syntax."""
    from_id = _safe_id(edge.from_node_id)
    to_id = _safe_id(edge.to_node_id)
    
    if not from_id or not to_id:
        return ""
    
    if edge.label:
        label = _sanitize_text(edge.label)
        return f'{from_id} -->|"{label}"| {to_id}'
    elif edge.edge_type == EdgeType.INFERRED:
        return f'{from_id} -.-> {to_id}'
    else:
        return f'{from_id} --> {to_id}'


def _safe_id(text: str) -> str:
    """Make a Mermaid-safe ID."""
    if not text:
        return "UNKNOWN"
    # Replace non-alphanumeric with underscore
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', text)
    safe = re.sub(r'_+', '_', safe).strip('_')
    if not safe:
        return "NODE"
    if safe[0].isdigit():
        safe = "N_" + safe
    return safe


def _sanitize_text(text: str) -> str:
    """Sanitize text for use in Mermaid labels."""
    if not text:
        return ""
    # Escape quotes
    result = text.replace('"', "'")
    # Remove characters that break Mermaid
    result = result.replace("#", "")
    result = result.replace("&", "and")
    # Keep Japanese characters intact
    return result.strip()
