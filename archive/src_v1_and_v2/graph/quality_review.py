"""Graph quality review — validates and filters entities/relations.

Provides:
- GraphQualityReviewer
- ReviewResult: accepted / rejected / pending classification
- Validation functions for entity_types, relation_types, source_chunk_id,
  confidence filtering, self-loops, missing evidence

Loads allowed types from configs/graph_schema.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.graph import (
    EntityType,
    EvidenceRecord,
    GraphEntity,
    GraphRelation,
    RelationType,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration / Schema loading
# ---------------------------------------------------------------------------


class QualityConfig(BaseModel):
    """Quality review configuration."""

    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    pending_min: float = Field(default=0.3, ge=0.0, le=1.0)
    pending_max: float = Field(default=0.5, ge=0.0, le=1.0)
    allowed_node_labels: list[str] = Field(default_factory=list)
    allowed_relation_types: list[str] = Field(default_factory=list)
    reject_self_loops: bool = Field(default=True)
    require_source_chunk_id: bool = Field(default=True)


def load_graph_schema(schema_path: Optional[Path] = None) -> QualityConfig:
    """Load graph schema from YAML config file.

    Falls back to defaults if file doesn't exist.
    """
    if schema_path and schema_path.exists():
        with open(schema_path) as f:
            data = yaml.safe_load(f) or {}

        node_labels = data.get("node_labels", [])
        relation_types = data.get("relation_types", [])
        min_conf = data.get("min_confidence", 0.5)
        pending_range = data.get("pending_confidence_range", {})

        return QualityConfig(
            min_confidence=min_conf,
            pending_min=pending_range.get("min", 0.3),
            pending_max=pending_range.get("max", 0.5),
            allowed_node_labels=[l.lower() for l in node_labels],
            allowed_relation_types=[r.lower() for r in relation_types],
        )

    # Default: allow all defined enum values
    return QualityConfig(
        allowed_node_labels=[e.value for e in EntityType],
        allowed_relation_types=[r.value for r in RelationType],
    )


# ---------------------------------------------------------------------------
# Review result
# ---------------------------------------------------------------------------


class ReviewResult(BaseModel):
    """Result of quality review: classified into accepted/rejected/pending."""

    accepted_entities: list[GraphEntity] = Field(default_factory=list)
    rejected_entities: list[GraphEntity] = Field(default_factory=list)
    pending_entities: list[GraphEntity] = Field(default_factory=list)

    accepted_relations: list[GraphRelation] = Field(default_factory=list)
    rejected_relations: list[GraphRelation] = Field(default_factory=list)
    pending_relations: list[GraphRelation] = Field(default_factory=list)

    accepted_evidence: list[EvidenceRecord] = Field(default_factory=list)

    rejection_reasons: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# GraphQualityReviewer
# ---------------------------------------------------------------------------


class GraphQualityReviewer:
    """Validates and classifies graph elements.

    Classification rules:
    - ACCEPTED: passes all validations and confidence >= min_confidence
    - PENDING: passes structure validations but confidence in [pending_min, pending_max)
    - REJECTED: fails any structural validation OR confidence < pending_min
    """

    def __init__(self, config: Optional[QualityConfig] = None, schema_path: Optional[Path] = None):
        if config:
            self.config = config
        elif schema_path:
            self.config = load_graph_schema(schema_path)
        else:
            self.config = QualityConfig(
                allowed_node_labels=[e.value for e in EntityType],
                allowed_relation_types=[r.value for r in RelationType],
            )

    def review(
        self,
        entities: list[GraphEntity],
        relations: list[GraphRelation],
        evidence: list[EvidenceRecord],
    ) -> ReviewResult:
        """Review all graph elements and classify them."""
        result = ReviewResult()

        # Review entities
        for entity in entities:
            issues = self.validate_entity(entity)
            if issues:
                result.rejected_entities.append(entity)
                result.rejection_reasons[entity.entity_id] = issues
            elif self._is_pending_confidence(entity.confidence):
                result.pending_entities.append(entity)
            else:
                result.accepted_entities.append(entity)

        # Build accepted entity ID set for relation validation
        accepted_entity_ids = {e.entity_id for e in result.accepted_entities}
        accepted_entity_ids.update(e.entity_id for e in result.pending_entities)

        # Review relations
        for relation in relations:
            issues = self.validate_relation(relation)
            if issues:
                result.rejected_relations.append(relation)
                result.rejection_reasons[relation.relation_id] = issues
            elif self._is_pending_confidence(relation.confidence):
                result.pending_relations.append(relation)
            else:
                result.accepted_relations.append(relation)

        # Evidence passes through (associated with accepted/pending relations)
        accepted_rel_ids = {r.relation_id for r in result.accepted_relations}
        accepted_rel_ids.update(r.relation_id for r in result.pending_relations)
        for ev in evidence:
            if ev.relation_id in accepted_rel_ids or ev.entity_id in accepted_entity_ids:
                result.accepted_evidence.append(ev)

        logger.info(
            f"Quality review: "
            f"entities {len(result.accepted_entities)}A/{len(result.pending_entities)}P/"
            f"{len(result.rejected_entities)}R, "
            f"relations {len(result.accepted_relations)}A/{len(result.pending_relations)}P/"
            f"{len(result.rejected_relations)}R"
        )

        return result

    def validate_entity(self, entity: GraphEntity) -> list[str]:
        """Validate a single entity. Returns list of issues (empty = valid)."""
        issues = []

        # Check entity type
        if self.config.allowed_node_labels:
            if entity.entity_type.value not in self.config.allowed_node_labels:
                issues.append(
                    f"Unknown entity_type '{entity.entity_type.value}' "
                    f"not in allowed labels"
                )

        # Check confidence
        if entity.confidence < self.config.pending_min:
            issues.append(
                f"Confidence {entity.confidence:.2f} below minimum {self.config.pending_min}"
            )

        # Check name
        if not entity.canonical_name or not entity.canonical_name.strip():
            issues.append("Empty canonical_name")

        return issues

    def validate_relation(self, relation: GraphRelation) -> list[str]:
        """Validate a single relation. Returns list of issues (empty = valid)."""
        issues = []

        # Check relation type
        if self.config.allowed_relation_types:
            if relation.relation_type.value not in self.config.allowed_relation_types:
                issues.append(
                    f"Unknown relation_type '{relation.relation_type.value}' "
                    f"not in allowed types"
                )

        # Check source_chunk_id
        if self.config.require_source_chunk_id:
            if not relation.source_chunk_id:
                issues.append("Missing source_chunk_id")

        # Check self-loop
        if self.config.reject_self_loops:
            if relation.source_entity_id == relation.target_entity_id:
                issues.append(
                    f"Self-loop detected: {relation.source_entity_id} → {relation.target_entity_id}"
                )

        # Check confidence
        if relation.confidence < self.config.pending_min:
            issues.append(
                f"Confidence {relation.confidence:.2f} below minimum {self.config.pending_min}"
            )

        # Check entity IDs exist
        if not relation.source_entity_id:
            issues.append("Missing source_entity_id")
        if not relation.target_entity_id:
            issues.append("Missing target_entity_id")

        return issues

    def validate_entity_types(self, entities: list[GraphEntity]) -> list[GraphEntity]:
        """Filter entities with invalid types."""
        return [e for e in entities if e.entity_type.value in self.config.allowed_node_labels]

    def validate_relation_types(self, relations: list[GraphRelation]) -> list[GraphRelation]:
        """Filter relations with invalid types."""
        return [r for r in relations if r.relation_type.value in self.config.allowed_relation_types]

    def validate_source_chunk_id(self, relations: list[GraphRelation]) -> tuple[list[GraphRelation], list[GraphRelation]]:
        """Split relations by source_chunk_id presence."""
        valid = []
        invalid = []
        for r in relations:
            if r.source_chunk_id:
                valid.append(r)
            else:
                invalid.append(r)
        return valid, invalid

    def filter_by_confidence(
        self,
        relations: list[GraphRelation],
    ) -> tuple[list[GraphRelation], list[GraphRelation], list[GraphRelation]]:
        """Split relations into accepted/pending/rejected by confidence.

        Returns: (accepted, pending, rejected)
        """
        accepted = []
        pending = []
        rejected = []

        for r in relations:
            if r.confidence >= self.config.min_confidence:
                accepted.append(r)
            elif r.confidence >= self.config.pending_min:
                pending.append(r)
            else:
                rejected.append(r)

        return accepted, pending, rejected

    def detect_self_loop(self, relations: list[GraphRelation]) -> list[GraphRelation]:
        """Find relations where source == target (self-loops)."""
        return [r for r in relations if r.source_entity_id == r.target_entity_id]

    def detect_missing_evidence(
        self,
        relations: list[GraphRelation],
        evidence: list[EvidenceRecord],
    ) -> list[GraphRelation]:
        """Find relations without corresponding evidence records."""
        evidence_relation_ids = {ev.relation_id for ev in evidence if ev.relation_id}
        return [r for r in relations if r.relation_id not in evidence_relation_ids]

    def _is_pending_confidence(self, confidence: float) -> bool:
        """Check if confidence falls in the pending range."""
        return self.config.pending_min <= confidence < self.config.min_confidence
