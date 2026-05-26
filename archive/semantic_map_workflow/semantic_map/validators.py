"""
Comprehensive validators for nodes, edges, Cypher statements, and graph
consistency in the semantic map workflow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from .constants import (
    CATEGORIES,
    LAYERS,
    LINK_METHODS,
    NODE_PREFIXES,
    RELATIONSHIP_TYPES,
    REVIEW_STATUSES,
    SOURCE_TYPES,
    VIEW_SCOPES,
    DISPLAY_GRAPH_MIN_NODES,
    DISPLAY_GRAPH_MAX_NODES,
    DISPLAY_GRAPH_MIN_EDGES,
    DISPLAY_GRAPH_MAX_EDGES,
)


# ---------------------------------------------------------------------------
# GraphValidationReport
# ---------------------------------------------------------------------------

@dataclass
class GraphValidationReport:
    """Summary report produced by graph-level validation helpers."""

    node_count: int = 0
    edge_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.error_count += 1

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        self.warning_count += 1

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def summary(self) -> str:
        status = "PASS" if self.is_valid else "FAIL"
        return (
            f"[{status}] nodes={self.node_count} edges={self.edge_count} "
            f"errors={self.error_count} warnings={self.warning_count}"
        )


# ---------------------------------------------------------------------------
# Node validation
# ---------------------------------------------------------------------------

def validate_node(node_dict: dict[str, Any]) -> list[str]:
    """
    Validate a node represented as a plain dict.

    Returns a list of human-readable error strings.  An empty list means the
    node is valid.
    """
    errors: list[str] = []

    # Required string fields
    for req_field in ("id", "name", "labels", "type", "layer", "category", "module"):
        val = node_dict.get(req_field)
        if not val or not isinstance(val, str) or not val.strip():
            errors.append(f"'{req_field}' is required and must be a non-empty string")

    node_id = node_dict.get("id", "<unknown>")

    # Enum fields
    layer = node_dict.get("layer", "")
    if layer and layer not in LAYERS:
        errors.append(f"[{node_id}] 'layer' {layer!r} not in {sorted(LAYERS)}")

    category = node_dict.get("category", "")
    if category and category not in CATEGORIES:
        errors.append(f"[{node_id}] 'category' {category!r} not in {sorted(CATEGORIES)}")

    source_type = node_dict.get("source_type", "")
    if source_type and source_type not in SOURCE_TYPES:
        errors.append(
            f"[{node_id}] 'source_type' {source_type!r} not in {sorted(SOURCE_TYPES)}"
        )

    review_status = node_dict.get("review_status", "")
    if review_status and review_status not in REVIEW_STATUSES:
        errors.append(
            f"[{node_id}] 'review_status' {review_status!r} not in {sorted(REVIEW_STATUSES)}"
        )

    view_scope = node_dict.get("view_scope", "")
    if view_scope and view_scope not in VIEW_SCOPES:
        errors.append(
            f"[{node_id}] 'view_scope' {view_scope!r} not in {sorted(VIEW_SCOPES)}"
        )

    # Numeric fields
    confidence = node_dict.get("confidence")
    if confidence is not None:
        try:
            c = float(confidence)
            if not (0.0 <= c <= 1.0):
                errors.append(
                    f"[{node_id}] 'confidence' must be between 0.0 and 1.0, got {c}"
                )
        except (TypeError, ValueError):
            errors.append(
                f"[{node_id}] 'confidence' must be a float, got {confidence!r}"
            )

    importance = node_dict.get("importance")
    if importance is not None:
        try:
            imp = int(importance)
            if not (1 <= imp <= 10):
                errors.append(
                    f"[{node_id}] 'importance' must be 1-10, got {imp}"
                )
        except (TypeError, ValueError):
            errors.append(
                f"[{node_id}] 'importance' must be an integer, got {importance!r}"
            )

    # ID prefix sanity check
    node_id_val = node_dict.get("id", "")
    if isinstance(node_id_val, str) and ":" in node_id_val:
        prefix = node_id_val.split(":")[0]
        if prefix not in NODE_PREFIXES:
            errors.append(
                f"[{node_id}] id prefix {prefix!r} not in NODE_PREFIXES "
                f"{sorted(NODE_PREFIXES)}"
            )

    return errors


# ---------------------------------------------------------------------------
# Edge validation
# ---------------------------------------------------------------------------

def validate_edge(edge_dict: dict[str, Any]) -> list[str]:
    """
    Validate an edge represented as a plain dict.

    Returns a list of human-readable error strings.  An empty list means the
    edge is valid.
    """
    errors: list[str] = []

    edge_id = edge_dict.get("id", "<unknown>")

    # Required string fields
    for req_field in ("id", "start_id", "end_id", "type", "label"):
        val = edge_dict.get(req_field)
        if not val or not isinstance(val, str) or not val.strip():
            errors.append(f"[{edge_id}] '{req_field}' is required and must be a non-empty string")

    # Self-loop check
    start_id = edge_dict.get("start_id")
    end_id = edge_dict.get("end_id")
    if start_id and end_id and start_id == end_id:
        errors.append(f"[{edge_id}] self-loop: start_id == end_id == {start_id!r}")

    # Relationship type
    rel_type = edge_dict.get("type", "")
    if rel_type and rel_type not in RELATIONSHIP_TYPES:
        errors.append(
            f"[{edge_id}] 'type' {rel_type!r} not in RELATIONSHIP_TYPES"
        )

    # Link method
    link_method = edge_dict.get("link_method", "")
    if link_method and link_method not in LINK_METHODS:
        errors.append(
            f"[{edge_id}] 'link_method' {link_method!r} not in {sorted(LINK_METHODS)}"
        )

    # Enum fields
    review_status = edge_dict.get("review_status", "")
    if review_status and review_status not in REVIEW_STATUSES:
        errors.append(
            f"[{edge_id}] 'review_status' {review_status!r} not in {sorted(REVIEW_STATUSES)}"
        )

    view_scope = edge_dict.get("view_scope", "")
    if view_scope and view_scope not in VIEW_SCOPES:
        errors.append(
            f"[{edge_id}] 'view_scope' {view_scope!r} not in {sorted(VIEW_SCOPES)}"
        )

    layer = edge_dict.get("layer", "")
    if layer and layer not in LAYERS:
        errors.append(
            f"[{edge_id}] 'layer' {layer!r} not in {sorted(LAYERS)}"
        )

    # Numeric fields
    confidence = edge_dict.get("confidence")
    if confidence is not None:
        try:
            c = float(confidence)
            if not (0.0 <= c <= 1.0):
                errors.append(
                    f"[{edge_id}] 'confidence' must be between 0.0 and 1.0, got {c}"
                )
        except (TypeError, ValueError):
            errors.append(
                f"[{edge_id}] 'confidence' must be a float, got {confidence!r}"
            )

    importance = edge_dict.get("importance")
    if importance is not None:
        try:
            imp = int(importance)
            if not (1 <= imp <= 10):
                errors.append(
                    f"[{edge_id}] 'importance' must be 1-10, got {imp}"
                )
        except (TypeError, ValueError):
            errors.append(
                f"[{edge_id}] 'importance' must be an integer, got {importance!r}"
            )

    return errors


# ---------------------------------------------------------------------------
# Cypher safety validation
# ---------------------------------------------------------------------------

# Patterns that must NOT appear in Cypher sent to Neptune
_DANGEROUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DELETE clause", re.compile(r"\bDELETE\b", re.IGNORECASE)),
    ("DROP clause", re.compile(r"\bDROP\b", re.IGNORECASE)),
    ("DETACH DELETE clause", re.compile(r"\bDETACH\s+DELETE\b", re.IGNORECASE)),
    ("REMOVE clause", re.compile(r"\bREMOVE\b", re.IGNORECASE)),
    # Matches both "key: [" (property map) and "= [" (SET assignment)
    ("array property (list literal)", re.compile(r"(?::\s*|\=\s*)\[")),
]


def validate_cypher_safety(cypher_str: str) -> list[str]:
    """
    Check a Cypher statement for dangerous operations and unsupported patterns.

    Checks performed:
    - No DELETE or DETACH DELETE
    - No DROP
    - No REMOVE (property removal)
    - No array property literals (Neptune openCypher does not support list
      values in property maps in all contexts)

    Returns a list of error strings; empty list means the statement is safe.
    """
    errors: list[str] = []

    if not isinstance(cypher_str, str) or not cypher_str.strip():
        errors.append("Cypher string is empty or not a string")
        return errors

    for label, pattern in _DANGEROUS_PATTERNS:
        if pattern.search(cypher_str):
            errors.append(f"Unsafe Cypher: contains {label}")

    return errors


# ---------------------------------------------------------------------------
# Display graph validation
# ---------------------------------------------------------------------------

def validate_display_graph(
    display_nodes: Sequence[dict[str, Any]],
    display_edges: Sequence[dict[str, Any]],
    all_nodes: Sequence[dict[str, Any]],
) -> list[str]:
    """
    Validate the display sub-graph against size constraints and referential
    integrity.

    Args:
        display_nodes: Nodes selected for the display graph.
        display_edges: Edges selected for the display graph.
        all_nodes:     Full universe of nodes (used to verify display nodes
                       are a subset).

    Returns a list of error/warning strings.
    """
    errors: list[str] = []
    n = len(display_nodes)
    e = len(display_edges)

    if n < DISPLAY_GRAPH_MIN_NODES:
        errors.append(
            f"Display graph has {n} nodes, minimum is {DISPLAY_GRAPH_MIN_NODES}"
        )
    if n > DISPLAY_GRAPH_MAX_NODES:
        errors.append(
            f"Display graph has {n} nodes, maximum is {DISPLAY_GRAPH_MAX_NODES}"
        )
    if e < DISPLAY_GRAPH_MIN_EDGES:
        errors.append(
            f"Display graph has {e} edges, minimum is {DISPLAY_GRAPH_MIN_EDGES}"
        )
    if e > DISPLAY_GRAPH_MAX_EDGES:
        errors.append(
            f"Display graph has {e} edges, maximum is {DISPLAY_GRAPH_MAX_EDGES}"
        )

    # Build sets of IDs
    all_node_ids: set[str] = {
        nd.get("id", "") for nd in all_nodes if nd.get("id")
    }
    display_node_ids: set[str] = {
        nd.get("id", "") for nd in display_nodes if nd.get("id")
    }

    # Every display node must exist in the full node set
    orphaned = display_node_ids - all_node_ids
    for oid in sorted(orphaned):
        errors.append(
            f"Display node {oid!r} does not exist in the full node set"
        )

    # Every display edge must reference display nodes (not just all_nodes)
    for ed in display_edges:
        edge_id = ed.get("id", "<unknown>")
        start = ed.get("start_id", "")
        end = ed.get("end_id", "")
        if start not in display_node_ids:
            errors.append(
                f"Display edge {edge_id!r}: start_id {start!r} not in display nodes"
            )
        if end not in display_node_ids:
            errors.append(
                f"Display edge {edge_id!r}: end_id {end!r} not in display nodes"
            )

    return errors


# ---------------------------------------------------------------------------
# ID registry consistency validation
# ---------------------------------------------------------------------------

def validate_id_registry(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> list[str]:
    """
    Verify that every edge endpoint references an existing node ID.

    Args:
        nodes: All node dicts (must have an 'id' key).
        edges: All edge dicts (must have 'start_id' and 'end_id' keys).

    Returns a list of error strings; empty means the graph is referentially
    intact.
    """
    errors: list[str] = []

    node_ids: set[str] = set()
    for nd in nodes:
        nid = nd.get("id")
        if not nid:
            errors.append(f"Node missing 'id' field: {nd!r}")
            continue
        if nid in node_ids:
            errors.append(f"Duplicate node id: {nid!r}")
        node_ids.add(nid)

    for ed in edges:
        edge_id = ed.get("id", "<unknown>")
        start = ed.get("start_id")
        end = ed.get("end_id")

        if not start:
            errors.append(f"Edge {edge_id!r} is missing 'start_id'")
        elif start not in node_ids:
            errors.append(
                f"Edge {edge_id!r}: start_id {start!r} references unknown node"
            )

        if not end:
            errors.append(f"Edge {edge_id!r} is missing 'end_id'")
        elif end not in node_ids:
            errors.append(
                f"Edge {edge_id!r}: end_id {end!r} references unknown node"
            )

    return errors


# ---------------------------------------------------------------------------
# Convenience: full graph report
# ---------------------------------------------------------------------------

def build_graph_validation_report(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> GraphValidationReport:
    """
    Run all per-entity validators plus ID registry check and return a
    consolidated :class:`GraphValidationReport`.
    """
    report = GraphValidationReport(
        node_count=len(nodes),
        edge_count=len(edges),
    )

    for nd in nodes:
        for err in validate_node(nd):
            report.add_error(err)

    for ed in edges:
        for err in validate_edge(ed):
            report.add_error(err)

    for err in validate_id_registry(nodes, edges):
        report.add_error(err)

    return report
