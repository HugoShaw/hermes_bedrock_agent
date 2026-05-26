"""Entity normalization — deduplication, alias merging, canonical form.

Provides:
- EntityNormalizer
- normalize_name(): canonical name normalization
- build_entity_id(): stable ID generation
- merge_aliases(): combine alias lists
- deduplicate_entities(): merge entities with same type + canonical_name
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.graph import EntityType, GraphEntity

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class NormalizerConfig(BaseModel):
    """Configuration for entity normalization."""

    lowercase_names: bool = Field(default=True)
    strip_whitespace: bool = Field(default=True)
    collapse_spaces: bool = Field(default=True)
    merge_aliases: bool = Field(default=True)
    min_name_length: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------


def normalize_name(name: str, *, config: Optional[NormalizerConfig] = None) -> str:
    """Normalize entity name to canonical form.

    Steps:
    1. Strip whitespace
    2. Collapse multiple spaces
    3. Lowercase (if configured)
    4. Remove leading/trailing punctuation artifacts
    """
    cfg = config or NormalizerConfig()
    result = name

    if cfg.strip_whitespace:
        result = result.strip()

    if cfg.collapse_spaces:
        result = re.sub(r"\s+", " ", result)

    if cfg.lowercase_names:
        result = result.lower()

    # Remove leading/trailing quotes and dots
    result = result.strip("\"'`.,;:")

    return result


def build_entity_id(entity_type: str, canonical_name: str) -> str:
    """Generate stable entity_id from type + canonical_name.

    Same type + canonical_name always produces same ID.
    """
    raw = f"{entity_type}:{canonical_name}".lower()
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"ent_{h}"


def merge_aliases(existing: list[str], new: list[str]) -> list[str]:
    """Merge two alias lists, preserving uniqueness and order."""
    seen = set()
    merged = []
    for alias in existing + new:
        normalized = alias.strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            merged.append(normalized)
    return merged


# ---------------------------------------------------------------------------
# EntityNormalizer
# ---------------------------------------------------------------------------


class EntityNormalizer:
    """Normalizes and deduplicates extracted entities.

    Groups entities by (entity_type, canonical_name) and merges:
    - source_chunk_ids (union)
    - aliases (union)
    - descriptions (longest wins)
    - confidence (max)
    - extraction_count (sum)
    """

    def __init__(self, config: Optional[NormalizerConfig] = None):
        self.config = config or NormalizerConfig()

    def normalize_entity(self, entity: GraphEntity) -> GraphEntity:
        """Normalize a single entity's name and rebuild ID."""
        canonical = normalize_name(entity.name or entity.canonical_name, config=self.config)

        if not canonical or len(canonical) < self.config.min_name_length:
            canonical = entity.canonical_name  # Fallback to existing

        entity_id = build_entity_id(entity.entity_type.value, canonical)

        # Collect aliases (original name + existing aliases)
        aliases = list(entity.aliases)
        if entity.name and entity.name.lower() != canonical:
            aliases = merge_aliases([entity.name], aliases)

        return entity.model_copy(update={
            "entity_id": entity_id,
            "canonical_name": canonical,
            "aliases": aliases,
            "is_normalized": True,
        })

    def deduplicate_entities(self, entities: list[GraphEntity]) -> list[GraphEntity]:
        """Merge entities with the same (entity_type, canonical_name).

        Returns deduplicated list with merged source_chunk_ids, aliases, etc.
        """
        # First normalize all entities
        normalized = [self.normalize_entity(e) for e in entities]

        # Group by (entity_type, canonical_name)
        groups: dict[str, list[GraphEntity]] = defaultdict(list)
        for ent in normalized:
            key = f"{ent.entity_type.value}:{ent.canonical_name}"
            groups[key].append(ent)

        # Merge each group
        merged: list[GraphEntity] = []
        for key, group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                merged.append(self._merge_group(group))

        logger.info(
            f"Normalized {len(entities)} entities → {len(merged)} unique "
            f"({len(entities) - len(merged)} merged)"
        )
        return merged

    def _merge_group(self, group: list[GraphEntity]) -> GraphEntity:
        """Merge multiple entities into one."""
        base = group[0]

        # Merge source_chunk_ids
        all_chunk_ids = []
        all_doc_ids = []
        all_aliases = list(base.aliases)
        best_description = base.description
        max_confidence = base.confidence
        total_count = 0

        for ent in group:
            all_chunk_ids.extend(ent.source_chunk_ids)
            all_doc_ids.extend(ent.source_document_ids)
            all_aliases = merge_aliases(all_aliases, ent.aliases)
            if len(ent.description) > len(best_description):
                best_description = ent.description
            max_confidence = max(max_confidence, ent.confidence)
            total_count += ent.extraction_count

        # Deduplicate chunk/doc IDs
        unique_chunk_ids = list(dict.fromkeys(all_chunk_ids))
        unique_doc_ids = list(dict.fromkeys(all_doc_ids))

        return base.model_copy(update={
            "source_chunk_ids": unique_chunk_ids,
            "source_document_ids": unique_doc_ids,
            "aliases": all_aliases,
            "description": best_description,
            "confidence": max_confidence,
            "extraction_count": total_count,
        })
