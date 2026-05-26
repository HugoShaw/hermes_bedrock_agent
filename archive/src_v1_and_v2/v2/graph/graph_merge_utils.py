"""
Graph Merge Utilities for Stage 07.

Provides stable normalization, deduplication, and merge helpers
for combining Business and Implementation graph nodes/edges.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from typing import Any


# ============================================================================
# Normalization
# ============================================================================

def normalize_key(text: str) -> str:
    """Normalize a name to a stable comparison key.
    
    - Unicode NFKC normalization
    - Lowercase
    - Strip whitespace
    - Collapse repeated spaces
    - Normalize hyphens/underscores to underscores
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    # Do NOT normalize hyphens/underscores for technical names
    # Only collapse repeated underscores
    text = re.sub(r"_{2,}", "_", text)
    return text


def normalize_technical_name(name: str) -> str:
    """Normalize a technical name (class, method, table) more aggressively.
    
    - NFKC + lowercase + strip
    - Remove quotes
    - Replace hyphens with underscores (technical context)
    """
    name = unicodedata.normalize("NFKC", name)
    name = name.lower().strip()
    name = name.replace('"', '').replace("'", "")
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_{2,}", "_", name)
    return name


def basename_from_path(path: str) -> str:
    """Extract filename from a path."""
    if "/" in path:
        return path.rsplit("/", 1)[-1]
    if "\\" in path:
        return path.rsplit("\\", 1)[-1]
    return path


# ============================================================================
# Merge Helpers
# ============================================================================

def merge_string_lists(a: list[str], b: list[str]) -> list[str]:
    """Merge two string lists, preserving order, deduplicating."""
    seen = set()
    result = []
    for item in a + b:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def merge_aliases(a: list[str], b: list[str]) -> list[str]:
    """Merge alias lists."""
    return merge_string_lists(a, b)


def merge_source_ids(a: list[str], b: list[str]) -> list[str]:
    """Merge source_ids lists."""
    return merge_string_lists(a, b)


def merge_evidence_chunk_ids(a: list[str], b: list[str]) -> list[str]:
    """Merge evidence_chunk_ids lists."""
    return merge_string_lists(a, b)


def merge_properties(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge property dicts. b's values override a's for same keys."""
    result = dict(a)
    result.update(b)
    return result


def merge_confidence(a: float, b: float) -> float:
    """Merge confidence scores — take maximum."""
    return max(a, b)


def merge_nodes(node_a: dict[str, Any], node_b: dict[str, Any]) -> dict[str, Any]:
    """Merge two nodes with the same node_id into one.
    
    Preserves node_a as base, merging in node_b's evidence/aliases.
    """
    merged = dict(node_a)
    merged["aliases"] = merge_aliases(
        node_a.get("aliases", []),
        node_b.get("aliases", [])
    )
    merged["source_ids"] = merge_source_ids(
        node_a.get("source_ids", []),
        node_b.get("source_ids", [])
    )
    merged["evidence_chunk_ids"] = merge_evidence_chunk_ids(
        node_a.get("evidence_chunk_ids", []),
        node_b.get("evidence_chunk_ids", [])
    )
    merged["properties"] = merge_properties(
        node_a.get("properties", {}),
        node_b.get("properties", {})
    )
    merged["confidence"] = merge_confidence(
        node_a.get("confidence", 0.0),
        node_b.get("confidence", 0.0)
    )
    # Merge display_name: prefer longer/more descriptive
    if len(node_b.get("display_name", "")) > len(merged.get("display_name", "")):
        merged["display_name"] = node_b["display_name"]
    # Merge description: prefer longer
    if len(node_b.get("description", "")) > len(merged.get("description", "")):
        merged["description"] = node_b["description"]
    return merged


def merge_edges(edge_a: dict[str, Any], edge_b: dict[str, Any]) -> dict[str, Any]:
    """Merge two edges with the same edge_id into one."""
    merged = dict(edge_a)
    merged["source_ids"] = merge_source_ids(
        edge_a.get("source_ids", []),
        edge_b.get("source_ids", [])
    )
    merged["evidence_chunk_ids"] = merge_evidence_chunk_ids(
        edge_a.get("evidence_chunk_ids", []),
        edge_b.get("evidence_chunk_ids", [])
    )
    merged["properties"] = merge_properties(
        edge_a.get("properties", {}),
        edge_b.get("properties", {})
    )
    merged["confidence"] = merge_confidence(
        edge_a.get("confidence", 0.0),
        edge_b.get("confidence", 0.0)
    )
    return merged


# ============================================================================
# Duplicate Detection
# ============================================================================

def detect_duplicate_nodes(nodes: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Detect nodes with duplicate node_ids.
    
    Returns: {node_id: [indices]} for node_ids with >1 occurrence.
    """
    id_to_indices: dict[str, list[int]] = {}
    for i, node in enumerate(nodes):
        nid = node["node_id"]
        id_to_indices.setdefault(nid, []).append(i)
    return {k: v for k, v in id_to_indices.items() if len(v) > 1}


def detect_duplicate_edges(edges: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Detect edges with duplicate edge_ids.
    
    Returns: {edge_id: [indices]} for edge_ids with >1 occurrence.
    """
    id_to_indices: dict[str, list[int]] = {}
    for i, edge in enumerate(edges):
        eid = edge["edge_id"]
        id_to_indices.setdefault(eid, []).append(i)
    return {k: v for k, v in id_to_indices.items() if len(v) > 1}


# ============================================================================
# Degree Calculation
# ============================================================================

def compute_degree(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, int]:
    """Compute degree (in+out) for each node."""
    degree: Counter = Counter()
    for edge in edges:
        degree[edge["source_node_id"]] += 1
        degree[edge["target_node_id"]] += 1
    # Include zero-degree nodes
    for node in nodes:
        if node["node_id"] not in degree:
            degree[node["node_id"]] = 0
    return dict(degree)


# ============================================================================
# Generic Name Detection
# ============================================================================

# Names too generic to be standalone nodes without strong context
GENERIC_NAMES = {
    "data", "system", "process", "user", "file", "table", "method",
    "service", "module", "config", "class", "info", "item", "record",
    "type", "name", "value", "list", "result", "action", "base",
    "common", "util", "utils", "helper", "manager", "handler",
}


def is_generic_name(name: str) -> bool:
    """Check if a name is too generic to be a standalone entity."""
    normalized = normalize_key(name)
    return normalized in GENERIC_NAMES
