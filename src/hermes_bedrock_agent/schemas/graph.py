"""Graph data models for entity/relation extraction and Neptune loading.

Covers the full graph lifecycle:
- Raw extraction output (from LLM)
- Normalized entities/relations (after dedup/merge)
- Evidence records linking graph elements back to source chunks
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Standard entity types for the enterprise knowledge graph."""

    SYSTEM = "system"
    MODULE = "module"
    TABLE = "table"
    COLUMN = "column"
    API = "api"
    PROCESS = "process"
    DOCUMENT = "document"
    PERSON = "person"
    ORGANIZATION = "organization"
    ROLE = "role"
    TERM = "term"
    CONCEPT = "concept"
    FILE = "file"
    SERVICE = "service"
    DATABASE = "database"
    SCREEN = "screen"
    FIELD = "field"
    EVENT = "event"
    RULE = "rule"
    UNKNOWN = "unknown"


class RelationType(str, Enum):
    """Standard relation types for the enterprise knowledge graph."""

    BELONGS_TO = "belongs_to"
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    CALLS = "calls"
    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    REFERENCES = "references"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    CONNECTS_TO = "connects_to"
    TRIGGERS = "triggers"
    PRODUCES = "produces"
    CONSUMES = "consumes"
    MANAGES = "manages"
    DESCRIBES = "describes"
    RELATED_TO = "related_to"
    PART_OF = "part_of"
    USED_BY = "used_by"
    DEFINED_IN = "defined_in"
    CUSTOM = "custom"


class GraphEntity(BaseModel):
    """A normalized entity in the knowledge graph.

    After extraction from source text and normalization (dedup, merge,
    canonical name resolution), entities are ready for Neptune loading.
    """

    entity_id: str = Field(..., description="Stable ID: sha256(entity_type + canonical_name)")
    name: str = Field(default="", description="Original extracted name (pre-normalization)")
    canonical_name: str = Field(..., description="Normalized display name")
    entity_type: EntityType = Field(default=EntityType.UNKNOWN)
    description: str = Field(default="", description="Entity description from extraction")

    # Alternative names (for search/matching)
    aliases: list[str] = Field(default_factory=list, description="Alternative names found in sources")
    name_ja: str = Field(default="", description="Japanese name (if applicable)")
    name_en: str = Field(default="", description="English name (if applicable)")

    # Graph properties
    properties: dict[str, str] = Field(
        default_factory=dict,
        description="Additional typed properties (e.g. version, schema, url)",
    )

    # Provenance
    source_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk IDs where this entity was mentioned",
    )
    source_document_ids: list[str] = Field(
        default_factory=list,
        description="Document IDs containing this entity",
    )
    extraction_count: int = Field(default=1, ge=1, description="Times extracted across all chunks")

    # Quality
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model_name: str = Field(default="", description="LLM model used for extraction")
    is_normalized: bool = Field(default=False, description="Whether normalization pass completed")
    is_reviewed: bool = Field(default=False, description="Whether quality review passed")

    # Metadata
    acl: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)


class GraphRelation(BaseModel):
    """A normalized relation between two entities.

    Relations are directional edges in the knowledge graph, linking
    a source entity to a target entity with a typed relationship.
    """

    relation_id: str = Field(
        ...,
        description="Stable ID: sha256(source_entity_id + relation_type + target_entity_id)",
    )
    source_entity_id: str = Field(..., description="Source entity ID (from_entity_id)")
    target_entity_id: str = Field(..., description="Target entity ID (to_entity_id)")
    relation_type: RelationType = Field(default=RelationType.RELATED_TO)
    relation_label: str = Field(default="", description="Human-readable relation label")
    description: str = Field(default="", description="Relation context/description")

    # Graph properties
    weight: float = Field(default=1.0, ge=0.0, description="Relation strength/frequency")
    properties: dict[str, str] = Field(default_factory=dict, description="Additional edge properties")

    # Provenance
    source_chunk_id: str = Field(default="", description="Primary chunk where relation was found")
    source_chunk_ids: list[str] = Field(
        default_factory=list,
        description="All chunk IDs where this relation was found",
    )
    evidence_id: str = Field(default="", description="Primary evidence record ID")
    evidence_text: str = Field(default="", description="Original text supporting this relation")

    # Quality
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model_name: str = Field(default="")
    is_normalized: bool = Field(default=False)
    is_reviewed: bool = Field(default=False)

    # Metadata
    acl: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)

    @property
    def from_entity_id(self) -> str:
        """Alias for source_entity_id."""
        return self.source_entity_id

    @property
    def to_entity_id(self) -> str:
        """Alias for target_entity_id."""
        return self.target_entity_id


class EvidenceRecord(BaseModel):
    """Links a graph element (entity or relation) back to its source text.

    Evidence records enable citation and traceability — every graph fact
    can be traced to the exact chunk and document it came from.
    """

    evidence_id: str = Field(..., description="Stable ID: sha256(entity_or_relation_id + chunk_id)")
    entity_id: Optional[str] = Field(default=None, description="Entity this evidence supports")
    relation_id: Optional[str] = Field(default=None, description="Relation this evidence supports")

    # Source
    source_chunk_id: str = Field(..., description="Chunk containing the evidence")
    document_id: str = Field(...)
    source_uri: str = Field(default="")

    # Evidence content
    evidence_text: str = Field(..., description="Exact text span supporting the graph element")
    context_text: str = Field(default="", description="Surrounding context for readability")
    page: Optional[int] = Field(default=None)
    section_title: str = Field(default="")

    # Quality
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model_name: str = Field(default="")

    # Metadata
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def text(self) -> str:
        """Alias for evidence_text (required by Phase 6 spec)."""
        return self.evidence_text
