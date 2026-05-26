"""
V2 Graph schemas — GraphNode and GraphEdge.

These represent the entities and relationships in both the
Business Semantic Graph and Implementation Graph layers.
Every node and edge links back to evidence via evidence_chunk_ids.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


# Layer constants (duplicated here to avoid circular imports with schema_registry)
ALLOWED_LAYERS = {"business", "implementation", "evidence"}


class GraphNode(BaseModel):
    """Represents a single node in the V2 knowledge graph.

    Nodes live in one of three layers:
    - business: Business Semantic Graph (domains, processes, rules, terms, etc.)
    - implementation: Implementation Graph (systems, APIs, tables, code, etc.)
    - evidence: Evidence layer (documents, sections, chunks)

    Every node must link back to evidence via evidence_chunk_ids.
    """

    node_id: str = Field(..., description="Unique node identifier: {layer}:{label}:{hash}")
    label: str = Field(..., description="PascalCase node label from allowed schema set")
    name: str = Field(..., description="Canonical name (lowercase, normalized)")
    display_name: str = Field(default="", description="Human-readable display name")
    layer: str = Field(..., description="Graph layer: business, implementation, or evidence")
    aliases: list[str] = Field(default_factory=list, description="Alternative names (CJK variants, abbreviations)")
    description: str = Field(default="", description="Node description")
    properties: dict[str, Any] = Field(default_factory=dict, description="Label-specific properties")
    source_ids: list[str] = Field(default_factory=list, description="Document IDs that contributed to this node")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="Linked evidence chunk IDs")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    run_id: str = Field(default="murata_semantic_v2", description="Run identifier")
    dataset: str = Field(default="murata", description="Dataset name")

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("node_id must not be empty")
        return v.strip()

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("label must not be empty")
        # Label should be PascalCase — basic check
        if not v[0].isupper():
            raise ValueError(f"label '{v}' must be PascalCase (start with uppercase)")
        return v.strip()

    @field_validator("layer")
    @classmethod
    def validate_layer(cls, v: str) -> str:
        if v not in ALLOWED_LAYERS:
            raise ValueError(
                f"layer '{v}' is not allowed. "
                f"Allowed layers: {sorted(ALLOWED_LAYERS)}"
            )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()

    @staticmethod
    def generate_id(layer: str, label: str, canonical_name: str) -> str:
        """Generate a deterministic node_id.

        Format: {layer}:{label}:{sha256(canonical_name)[:12]}
        """
        name_hash = hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()[:12]
        return f"{layer}:{label}:{name_hash}"

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "GraphNode":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())


class GraphEdge(BaseModel):
    """Represents a single edge (relationship) in the V2 knowledge graph.

    Edges connect two nodes and belong to a layer:
    - business: Business-layer relationships (CONTAINS, HAS_STEP, HAS_RULE, etc.)
    - implementation: Implementation-layer relationships (CALLS, READS, WRITES, etc.)
    - cross: Cross-layer relationships (MAPS_TO, IMPLEMENTS)
    - evidence: Evidence-layer relationships (HAS_EVIDENCE, MENTIONED_IN)

    Every edge must link back to evidence via evidence_chunk_ids.
    """

    edge_id: str = Field(..., description="Unique edge identifier: sha256(source + relation + target)")
    source_node_id: str = Field(..., description="Source node identifier")
    target_node_id: str = Field(..., description="Target node identifier")
    relation_type: str = Field(..., description="UPPER_CASE relation type from allowed schema set")
    layer: str = Field(..., description="Edge layer: business, implementation, cross, or evidence")
    description: str = Field(default="", description="Edge description")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relation-specific properties")
    source_ids: list[str] = Field(default_factory=list, description="Document IDs that contributed to this edge")
    evidence_chunk_ids: list[str] = Field(default_factory=list, description="Linked evidence chunk IDs")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    run_id: str = Field(default="murata_semantic_v2", description="Run identifier")
    dataset: str = Field(default="murata", description="Dataset name")

    @field_validator("edge_id")
    @classmethod
    def validate_edge_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("edge_id must not be empty")
        return v.strip()

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("relation_type must not be empty")
        # Relation types should be UPPER_CASE with underscores
        if v != v.upper():
            raise ValueError(f"relation_type '{v}' must be UPPER_CASE")
        return v.strip()

    @field_validator("layer")
    @classmethod
    def validate_layer(cls, v: str) -> str:
        allowed_edge_layers = {"business", "implementation", "cross", "evidence"}
        if v not in allowed_edge_layers:
            raise ValueError(
                f"layer '{v}' is not allowed for edges. "
                f"Allowed layers: {sorted(allowed_edge_layers)}"
            )
        return v

    @staticmethod
    def generate_id(source_node_id: str, relation_type: str, target_node_id: str) -> str:
        """Generate a deterministic edge_id.

        Format: sha256(source_node_id + relation_type + target_node_id)[:16]
        """
        raw = f"{source_node_id}:{relation_type}:{target_node_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "GraphEdge":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())
