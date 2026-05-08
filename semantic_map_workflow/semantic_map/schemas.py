"""
Dataclass schemas for semantic map nodes and edges, with validation,
serialization, and Neptune Cypher property helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Optional

from .constants import (
    LAYERS,
    CATEGORIES,
    SOURCE_TYPES,
    REVIEW_STATUSES,
    VIEW_SCOPES,
    RELATIONSHIP_TYPES,
    LINK_METHODS,
    NODE_PREFIXES,
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class EntityValidationError(ValueError):
    """Raised when a Node or Edge fails schema validation."""

    def __init__(self, entity_type: str, entity_id: str, errors: list[str]) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.errors = errors
        joined = "; ".join(errors)
        super().__init__(f"[{entity_type} id={entity_id!r}] Validation failed: {joined}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_cypher(value: str) -> str:
    """Escape single quotes for Cypher string literals (replace ' with '')."""
    return value.replace("'", "''")


def _to_scalar_cypher(value: Any) -> Optional[str]:
    """
    Convert a Python value to its Cypher literal representation.
    Returns None if the value is not a supported scalar type (list / dict are
    excluded because Neptune openCypher does not support array / map properties
    in all contexts).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f"'{_escape_cypher(value)}'"
    # Skip complex types silently
    return None


# ---------------------------------------------------------------------------
# NodeSchema
# ---------------------------------------------------------------------------

@dataclass
class NodeSchema:
    """Represents a single node in the semantic map graph."""

    id: str
    labels: str                       # comma-separated Cypher labels, e.g. "Node,Process"
    type: str                         # fine-grained type, e.g. "process"
    layer: str                        # one of LAYERS
    category: str                     # one of CATEGORIES
    module: str                       # business module key or empty string
    name: str                         # canonical name
    display_name: str = ""            # human-readable display name
    description: str = ""
    aliases_text: str = ""            # pipe-separated aliases
    properties_text: str = ""         # free-form property key=value pairs
    evidence_text: str = ""           # evidence snippet(s)
    source_file: str = ""             # origin file path or identifier
    source_type: str = "unknown"      # one of SOURCE_TYPES
    confidence: float = 1.0
    review_status: str = "pending"    # one of REVIEW_STATUSES
    importance: int = 5               # 1-10 scale
    view_scope: str = "detail"        # one of VIEW_SCOPES

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Validate all fields; raises EntityValidationError on failure."""
        errors: list[str] = []

        if not self.id or not isinstance(self.id, str):
            errors.append("'id' must be a non-empty string")

        if not self.name or not isinstance(self.name, str):
            errors.append("'name' must be a non-empty string")

        if not self.labels or not isinstance(self.labels, str):
            errors.append("'labels' must be a non-empty string")

        if self.layer not in LAYERS:
            errors.append(f"'layer' must be one of {sorted(LAYERS)}, got {self.layer!r}")

        if self.category not in CATEGORIES:
            errors.append(
                f"'category' must be one of {sorted(CATEGORIES)}, got {self.category!r}"
            )

        if self.source_type not in SOURCE_TYPES:
            errors.append(
                f"'source_type' must be one of {sorted(SOURCE_TYPES)}, got {self.source_type!r}"
            )

        if self.review_status not in REVIEW_STATUSES:
            errors.append(
                f"'review_status' must be one of {sorted(REVIEW_STATUSES)}, "
                f"got {self.review_status!r}"
            )

        if self.view_scope not in VIEW_SCOPES:
            errors.append(
                f"'view_scope' must be one of {sorted(VIEW_SCOPES)}, got {self.view_scope!r}"
            )

        if not (0.0 <= self.confidence <= 1.0):
            errors.append(
                f"'confidence' must be between 0.0 and 1.0, got {self.confidence}"
            )

        if not isinstance(self.importance, int) or not (1 <= self.importance <= 10):
            errors.append(
                f"'importance' must be an integer between 1 and 10, got {self.importance!r}"
            )

        # Validate id prefix matches a known NODE_PREFIXES (best-effort warning only,
        # stored as error so callers can decide severity)
        if ":" in self.id:
            prefix = self.id.split(":")[0]
            if prefix not in NODE_PREFIXES:
                errors.append(
                    f"id prefix {prefix!r} is not in NODE_PREFIXES; "
                    f"known prefixes: {sorted(NODE_PREFIXES)}"
                )

        if errors:
            raise EntityValidationError("Node", self.id, errors)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this node."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeSchema":
        """Construct a NodeSchema from a plain dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    # ------------------------------------------------------------------
    # Neptune / Cypher helpers
    # ------------------------------------------------------------------

    def to_cypher_props(self) -> str:
        """
        Return a Cypher property map string containing only scalar fields,
        safe for use in MERGE / CREATE statements targeting Neptune openCypher.

        Example output:
            {id: 'process:foo', name: 'Foo', confidence: 0.9, ...}
        """
        parts: list[str] = []
        for f in fields(self):
            value = getattr(self, f.name)
            cypher_val = _to_scalar_cypher(value)
            if cypher_val is not None:
                parts.append(f"{f.name}: {cypher_val}")
        return "{" + ", ".join(parts) + "}"


# ---------------------------------------------------------------------------
# EdgeSchema
# ---------------------------------------------------------------------------

@dataclass
class EdgeSchema:
    """Represents a single directed edge in the semantic map graph."""

    id: str                           # e.g. rel:000001
    start_id: str                     # source node id
    type: str                         # one of RELATIONSHIP_TYPES
    label: str                        # human-readable label (may equal type)
    end_id: str                       # target node id
    evidence_text: str = ""
    source_file: str = ""
    link_method: str = "manual_inference"   # one of LINK_METHODS
    confidence: float = 1.0
    review_status: str = "pending"    # one of REVIEW_STATUSES
    importance: int = 5               # 1-10 scale
    view_scope: str = "detail"        # one of VIEW_SCOPES
    module: str = ""
    layer: str = ""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Validate all fields; raises EntityValidationError on failure."""
        errors: list[str] = []

        if not self.id or not isinstance(self.id, str):
            errors.append("'id' must be a non-empty string")

        if not self.start_id or not isinstance(self.start_id, str):
            errors.append("'start_id' must be a non-empty string")

        if not self.end_id or not isinstance(self.end_id, str):
            errors.append("'end_id' must be a non-empty string")

        if self.start_id == self.end_id:
            errors.append(
                f"self-loop detected: 'start_id' and 'end_id' are both {self.start_id!r}"
            )

        if self.type not in RELATIONSHIP_TYPES:
            errors.append(
                f"'type' must be one of {sorted(RELATIONSHIP_TYPES)}, got {self.type!r}"
            )

        if self.link_method not in LINK_METHODS:
            errors.append(
                f"'link_method' must be one of {sorted(LINK_METHODS)}, "
                f"got {self.link_method!r}"
            )

        if self.review_status not in REVIEW_STATUSES:
            errors.append(
                f"'review_status' must be one of {sorted(REVIEW_STATUSES)}, "
                f"got {self.review_status!r}"
            )

        if self.view_scope not in VIEW_SCOPES:
            errors.append(
                f"'view_scope' must be one of {sorted(VIEW_SCOPES)}, "
                f"got {self.view_scope!r}"
            )

        if not (0.0 <= self.confidence <= 1.0):
            errors.append(
                f"'confidence' must be between 0.0 and 1.0, got {self.confidence}"
            )

        if not isinstance(self.importance, int) or not (1 <= self.importance <= 10):
            errors.append(
                f"'importance' must be an integer between 1 and 10, got {self.importance!r}"
            )

        if self.layer and self.layer not in LAYERS:
            errors.append(
                f"'layer' must be one of {sorted(LAYERS)} or empty, got {self.layer!r}"
            )

        if not self.label or not isinstance(self.label, str):
            errors.append("'label' must be a non-empty string")

        if errors:
            raise EntityValidationError("Edge", self.id, errors)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this edge."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EdgeSchema":
        """Construct an EdgeSchema from a plain dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    # ------------------------------------------------------------------
    # Neptune / Cypher helpers
    # ------------------------------------------------------------------

    def to_cypher_props(self) -> str:
        """
        Return a Cypher property map string containing only scalar fields,
        safe for use in MERGE / CREATE statements targeting Neptune openCypher.

        Array and dict values are silently skipped.
        """
        parts: list[str] = []
        for f in fields(self):
            value = getattr(self, f.name)
            cypher_val = _to_scalar_cypher(value)
            if cypher_val is not None:
                parts.append(f"{f.name}: {cypher_val}")
        return "{" + ", ".join(parts) + "}"
