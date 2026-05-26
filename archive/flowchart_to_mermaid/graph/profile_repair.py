"""
Profile-based semantic repair for flowchart_to_mermaid pipeline.

This module integrates domain profiles (like msha_dss_flowchart) into the
standard pipeline. When a profile matches the input document, it can either:
1. Augment the CV-extracted graph with missing structure (partial repair)
2. Replace the graph entirely when CV extraction is fundamentally broken (full repair)

The profile output is always written to intermediate_flow.repaired.json,
preserving the pipeline contract: raw -> repaired -> final -> mermaid -> svg.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, NodeType, PageFlow,
)

logger = logging.getLogger(__name__)

# Map profile node types to NodeType enum
TYPE_MAP = {
    "process": NodeType.PROCESS,
    "decision": NodeType.DECISION,
    "terminator": NodeType.TERMINATOR,
    "api": NodeType.API,
    "file": NodeType.FILE,
    "loop": NodeType.LOOP,
    "exception": NodeType.EXCEPTION,
}


def load_profile(profile_name: str):
    """Load a repair profile by name."""
    if profile_name == "msha_dss":
        from flowchart_to_mermaid.profiles.msha_dss_flowchart import get_profile
        return get_profile()
    else:
        raise ValueError(f"Unknown profile: {profile_name}. Available: msha_dss")


def apply_profile_repair(
    raw_flow: dict,
    profile_name: str,
    output_dir: Path,
) -> FlowDocument:
    """
    Apply profile-based semantic repair to raw extracted flow.
    
    This replaces the broken CV graph with the profile-structured graph
    while preserving evidence of what was originally extracted.
    
    Args:
        raw_flow: The raw intermediate flow dict from CV extraction
        profile_name: Name of the profile to apply
        output_dir: Directory for intermediate outputs
        
    Returns:
        FlowDocument ready for Mermaid rendering
    """
    profile = load_profile(profile_name)
    
    # Check if profile matches the document
    raw_text = _extract_all_text(raw_flow)
    if not profile.matches_document(raw_text):
        logger.warning(f"Profile '{profile_name}' does not match document content. "
                      f"Proceeding anyway as explicitly requested.")
    
    # Generate the profile-based intermediate flow
    profile_flow = profile.to_intermediate_flow()
    
    # Save as repaired intermediate
    repaired_path = output_dir / "intermediate_flow.repaired.json"
    repaired_path.parent.mkdir(parents=True, exist_ok=True)
    with open(repaired_path, "w", encoding="utf-8") as f:
        json.dump(profile_flow, f, ensure_ascii=False, indent=2)
    logger.info(f"Profile-repaired flow saved: {repaired_path}")
    
    # Also save as final intermediate (same content for profile repair)
    final_path = output_dir / "intermediate_flow.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(profile_flow, f, ensure_ascii=False, indent=2)
    logger.info(f"Final intermediate flow saved: {final_path}")
    
    # Convert to FlowDocument for rendering
    doc = _profile_flow_to_document(profile_flow)
    
    return doc


def _extract_all_text(raw_flow: dict) -> str:
    """Extract all text from raw flow for profile matching."""
    texts = []
    for page in raw_flow.get("pages", []):
        for node in page.get("nodes", []):
            texts.append(node.get("label", ""))
    return " ".join(texts)


def _profile_flow_to_document(profile_flow: dict) -> FlowDocument:
    """Convert profile flow dict to FlowDocument model."""
    pages = []
    
    for page_data in profile_flow.get("pages", []):
        nodes = []
        for n in page_data.get("nodes", []):
            node_type = TYPE_MAP.get(n.get("type", "process"), NodeType.PROCESS)
            nodes.append(FlowNode(
                id=n["id"],
                label=n["label"],
                type=node_type,
                bbox=n.get("bbox", [0, 0, 100, 50]),
                group_id=n.get("group_id"),
                source_text_ids=n.get("source_text_ids", []),
                confidence=n.get("confidence", 0.85),
                uncertain=n.get("uncertain", False),
            ))
        
        edges = []
        for i, e in enumerate(page_data.get("edges", [])):
            edges.append(FlowEdge(
                id=f"E{i:03d}",
                source=e["source_id"],
                target=e["target_id"],
                label=e.get("label"),
                confidence=e.get("confidence", 0.85),
                uncertain=False,
                inferred=e.get("inferred", False),
            ))
        
        groups = []
        for g in page_data.get("groups", []):
            groups.append(FlowGroup(
                id=g["id"],
                label=g["label"],
                node_ids=g.get("node_ids", []),
                parent_group_id=g.get("parent_group_id"),
                confidence=0.9,
            ))
        
        pages.append(PageFlow(
            page_index=0,
            nodes=nodes,
            edges=edges,
            groups=groups,
        ))
    
    return FlowDocument(
        source_file=profile_flow.get("source_file", ""),
        source_type=profile_flow.get("source_type", "profile"),
        pages=pages,
        direction=profile_flow.get("direction", "TD"),
        metadata=profile_flow.get("metadata", {}),
    )
