"""
V2 Graph Schema Registry — constants and validation helpers.

This module defines the allowed node labels, relation types, and layers
for the V2 knowledge graph. It provides validation functions that can be
used by graph builders, entity resolvers, and quality filters to ensure
schema compliance.

Design principle: Keep this module free from heavy dependencies.
Only stdlib + basic type checks. No Pydantic, no Bedrock, no Neptune imports.
"""

from __future__ import annotations

import re
from typing import Optional


# ===========================================================================
# Layer Constants
# ===========================================================================

BUSINESS_LAYER = "business"
IMPLEMENTATION_LAYER = "implementation"
EVIDENCE_LAYER = "evidence"

ALLOWED_LAYERS = {BUSINESS_LAYER, IMPLEMENTATION_LAYER, EVIDENCE_LAYER}


# ===========================================================================
# Node Labels by Layer
# ===========================================================================

# Business Semantic Graph labels (from .hermes.md Section 8)
BUSINESS_LABELS = {
    "Project",
    "BusinessDomain",
    "BusinessProcess",
    "BusinessStep",
    "BusinessRule",
    "BusinessTerm",
    "Function",
    "Screen",
    "Role",
    "Organization",
    "Document",
    "EvidenceChunk",
}

# Implementation Graph labels (from .hermes.md Section 9)
IMPLEMENTATION_LABELS = {
    "System",
    "Module",
    "API",
    "Service",
    "Class",
    "Method",
    "Table",
    "Column",
    "SQL",
    "Job",
    "File",
    "ExternalSystem",
    "Config",
    "Message",
    "ErrorCode",
    "Document",
    "EvidenceChunk",
}

# Evidence Layer labels (from .hermes.md Section 10)
EVIDENCE_LABELS = {
    "Document",
    "Section",
    "EvidenceChunk",
    "SourceFile",
}

# Union of all labels (for global validation without layer context)
ALL_LABELS = BUSINESS_LABELS | IMPLEMENTATION_LABELS | EVIDENCE_LABELS

# Mapping from layer to allowed labels
_LAYER_TO_LABELS: dict[str, set[str]] = {
    BUSINESS_LAYER: BUSINESS_LABELS,
    IMPLEMENTATION_LAYER: IMPLEMENTATION_LABELS,
    EVIDENCE_LAYER: EVIDENCE_LABELS,
}


# ===========================================================================
# Relation Types (from .hermes.md Sections 8, 9, 10)
# ===========================================================================

# Business layer relations
BUSINESS_RELATION_TYPES = {
    "BELONGS_TO",
    "CONTAINS",
    "HAS_STEP",
    "NEXT_STEP",
    "HAS_RULE",
    "HAS_TERM",
    "HAS_FUNCTION",
    "VALIDATES",
    "USES",
    "DEPENDS_ON",
    "HAS_EVIDENCE",
    "MENTIONED_IN",
    "RELATED_TO",
}

# Implementation layer relations
IMPLEMENTATION_RELATION_TYPES = {
    "BELONGS_TO",
    "CONTAINS",
    "IMPLEMENTS",
    "USES",
    "CALLS",
    "READS",
    "WRITES",
    "MAPS_TO",
    "DEPENDS_ON",
    "TRIGGERS",
    "VALIDATES",
    "HAS_FIELD",
    "HAS_API",
    "HAS_METHOD",
    "HAS_TABLE",
    "HAS_COLUMN",
    "HAS_ERROR",
    "HAS_EVIDENCE",
    "MENTIONED_IN",
    "RELATED_TO",
}

# Evidence layer relations
EVIDENCE_RELATION_TYPES = {
    "CONTAINS",
    "HAS_SECTION",
    "HAS_CHUNK",
    "MENTIONED_IN",
    "HAS_EVIDENCE",
}

# Union of all allowed relation types
ALLOWED_RELATION_TYPES = (
    BUSINESS_RELATION_TYPES
    | IMPLEMENTATION_RELATION_TYPES
    | EVIDENCE_RELATION_TYPES
)

# Mapping from layer to allowed relation types
_LAYER_TO_RELATIONS: dict[str, set[str]] = {
    BUSINESS_LAYER: BUSINESS_RELATION_TYPES,
    IMPLEMENTATION_LAYER: IMPLEMENTATION_RELATION_TYPES,
    EVIDENCE_LAYER: EVIDENCE_RELATION_TYPES,
}


# ===========================================================================
# Label Normalization Map
# ===========================================================================

# Common aliases/typos to canonical PascalCase labels
_LABEL_ALIASES: dict[str, str] = {
    # Business layer aliases
    "project": "Project",
    "business_domain": "BusinessDomain",
    "businessdomain": "BusinessDomain",
    "domain": "BusinessDomain",
    "business_process": "BusinessProcess",
    "businessprocess": "BusinessProcess",
    "process": "BusinessProcess",
    "business_step": "BusinessStep",
    "businessstep": "BusinessStep",
    "step": "BusinessStep",
    "business_rule": "BusinessRule",
    "businessrule": "BusinessRule",
    "rule": "BusinessRule",
    "business_term": "BusinessTerm",
    "businessterm": "BusinessTerm",
    "term": "BusinessTerm",
    "function": "Function",
    "screen": "Screen",
    "role": "Role",
    "organization": "Organization",
    "org": "Organization",
    # Implementation layer aliases
    "system": "System",
    "module": "Module",
    "api": "API",
    "service": "Service",
    "class": "Class",
    "method": "Method",
    "table": "Table",
    "column": "Column",
    "sql": "SQL",
    "job": "Job",
    "file": "File",
    "external_system": "ExternalSystem",
    "externalsystem": "ExternalSystem",
    "config": "Config",
    "configuration": "Config",
    "message": "Message",
    "error_code": "ErrorCode",
    "errorcode": "ErrorCode",
    # Evidence layer aliases
    "document": "Document",
    "doc": "Document",
    "section": "Section",
    "evidence_chunk": "EvidenceChunk",
    "evidencechunk": "EvidenceChunk",
    "chunk": "EvidenceChunk",
    "source_file": "SourceFile",
    "sourcefile": "SourceFile",
}

# Relation type normalization
_RELATION_ALIASES: dict[str, str] = {
    "belongs_to": "BELONGS_TO",
    "contains": "CONTAINS",
    "has_step": "HAS_STEP",
    "next_step": "NEXT_STEP",
    "has_rule": "HAS_RULE",
    "has_term": "HAS_TERM",
    "has_function": "HAS_FUNCTION",
    "implements": "IMPLEMENTS",
    "uses": "USES",
    "calls": "CALLS",
    "reads": "READS",
    "writes": "WRITES",
    "maps_to": "MAPS_TO",
    "depends_on": "DEPENDS_ON",
    "triggers": "TRIGGERS",
    "validates": "VALIDATES",
    "has_field": "HAS_FIELD",
    "has_api": "HAS_API",
    "has_method": "HAS_METHOD",
    "has_table": "HAS_TABLE",
    "has_column": "HAS_COLUMN",
    "has_error": "HAS_ERROR",
    "has_evidence": "HAS_EVIDENCE",
    "mentioned_in": "MENTIONED_IN",
    "related_to": "RELATED_TO",
    "has_section": "HAS_SECTION",
    "has_chunk": "HAS_CHUNK",
    # Common V1 aliases that need remapping
    "references": "RELATED_TO",
    "reads_from": "READS",
    "writes_to": "WRITES",
    "supports": "IMPLEMENTS",
}


# ===========================================================================
# Validation Functions
# ===========================================================================

def is_valid_layer(layer: str) -> bool:
    """Check if a layer string is valid."""
    return layer in ALLOWED_LAYERS


def allowed_labels_for_layer(layer: str) -> set[str]:
    """Return the set of allowed labels for a given layer.

    Returns empty set for invalid layers.
    """
    return _LAYER_TO_LABELS.get(layer, set())


def is_valid_label(label: str, layer: Optional[str] = None) -> bool:
    """Check if a label is valid, optionally within a specific layer.

    Args:
        label: PascalCase label to validate
        layer: Optional layer constraint. If None, checks against all labels.
    """
    if layer is not None:
        return label in _LAYER_TO_LABELS.get(layer, set())
    return label in ALL_LABELS


def is_valid_relation(relation_type: str, layer: Optional[str] = None) -> bool:
    """Check if a relation type is valid, optionally within a specific layer.

    Args:
        relation_type: UPPER_CASE relation type to validate
        layer: Optional layer constraint. If None, checks against all relations.
    """
    if layer is not None:
        return relation_type in _LAYER_TO_RELATIONS.get(layer, set())
    return relation_type in ALLOWED_RELATION_TYPES


def normalize_label(label: str) -> str:
    """Normalize a label string to its canonical PascalCase form.

    Handles:
    - Lowercase input → PascalCase
    - snake_case → PascalCase
    - Known aliases → canonical form
    - Already valid labels pass through unchanged

    Returns:
        Canonical label if found, otherwise the input with basic PascalCase applied.
    """
    # Already valid?
    if label in ALL_LABELS:
        return label

    # Check alias map (case-insensitive)
    lower = label.lower().strip()
    if lower in _LABEL_ALIASES:
        return _LABEL_ALIASES[lower]

    # Try converting snake_case to PascalCase
    pascal = "".join(word.capitalize() for word in re.split(r"[_\s-]+", label))
    if pascal in ALL_LABELS:
        return pascal

    # Return as-is if we can't normalize (will fail validation)
    return label


def normalize_relation_type(relation_type: str) -> str:
    """Normalize a relation type to its canonical UPPER_CASE form.

    Handles:
    - Lowercase input → UPPER_CASE
    - Known aliases → canonical form
    - V1 relation names → V2 equivalents
    - Already valid types pass through unchanged

    Returns:
        Canonical relation type if found, otherwise the input uppercased.
    """
    # Already valid?
    if relation_type in ALLOWED_RELATION_TYPES:
        return relation_type

    # Check alias map (case-insensitive)
    lower = relation_type.lower().strip()
    if lower in _RELATION_ALIASES:
        return _RELATION_ALIASES[lower]

    # Try simple uppercase
    upper = relation_type.upper().strip()
    if upper in ALLOWED_RELATION_TYPES:
        return upper

    # Return uppercased (will fail validation if not in allowed set)
    return upper


def validate_node_schema(label: str, layer: str) -> tuple[bool, Optional[str]]:
    """Validate a node's label against its declared layer.

    Returns:
        (is_valid, error_message)
        If valid: (True, None)
        If invalid: (False, "description of error")
    """
    if not is_valid_layer(layer):
        return False, f"Invalid layer '{layer}'. Allowed: {sorted(ALLOWED_LAYERS)}"

    allowed = allowed_labels_for_layer(layer)
    if label not in allowed:
        return False, (
            f"Label '{label}' is not allowed in layer '{layer}'. "
            f"Allowed labels for {layer}: {sorted(allowed)}"
        )

    return True, None


def validate_edge_schema(
    relation_type: str, layer: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """Validate an edge's relation type, optionally against a layer.

    For edges, layer can also be "cross" (cross-layer edges like MAPS_TO).
    Cross-layer edges are validated against the union of all relation types.

    Returns:
        (is_valid, error_message)
        If valid: (True, None)
        If invalid: (False, "description of error")
    """
    # Cross-layer edges validate against all relation types
    if layer == "cross" or layer is None:
        if relation_type not in ALLOWED_RELATION_TYPES:
            return False, (
                f"Relation type '{relation_type}' is not in allowed set. "
                f"Allowed: {sorted(ALLOWED_RELATION_TYPES)}"
            )
        return True, None

    # Layer-specific validation
    if layer not in _LAYER_TO_RELATIONS:
        return False, f"Invalid layer '{layer}' for edge validation."

    allowed = _LAYER_TO_RELATIONS[layer]
    if relation_type not in allowed:
        return False, (
            f"Relation type '{relation_type}' is not allowed in layer '{layer}'. "
            f"Allowed for {layer}: {sorted(allowed)}"
        )

    return True, None
