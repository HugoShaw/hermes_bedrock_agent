"""Graph extraction — LLM-based entity/relation extraction from chunks.

Provides:
- GraphExtractor: calls Bedrock Claude to extract entities + relations
- MockGraphExtractor: deterministic fake extraction for testing
- build_extraction_prompt(): builds the LLM prompt
- parse_llm_json_response(): parses LLM JSON with code fence handling

Business logic lives HERE. LLM calls go through clients/bedrock_client.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.chunk import DocumentChunk
from hermes_bedrock_agent.schemas.graph import (
    EntityType,
    EvidenceRecord,
    GraphEntity,
    GraphRelation,
    RelationType,
)
from hermes_bedrock_agent.utils.hashing import content_hash

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ExtractorConfig(BaseModel):
    """Configuration for graph extraction."""

    model_id: str = Field(default="anthropic.claude-sonnet-4-20250514")
    max_tokens: int = Field(default=4096, ge=256)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    batch_size: int = Field(default=5, ge=1)
    max_retries: int = Field(default=3, ge=1)
    # Quality constraints
    max_entities_per_chunk: int = Field(default=8, ge=1)
    max_relations_per_chunk: int = Field(default=12, ge=1)
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Extraction result container
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Result of extracting graph elements from a single chunk."""

    entities: list[GraphEntity] = Field(default_factory=list)
    relations: list[GraphRelation] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    chunk_id: str = ""
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are an enterprise knowledge graph extraction expert.
Given the following text chunk from a technical document, extract:
1. Named entities (systems, modules, tables, APIs, processes, people, organizations, concepts, etc.)
2. Relations between entities (calls, depends_on, contains, reads_from, writes_to, etc.)

IMPORTANT CONSTRAINTS:
- Extract at most 8 entities and 12 relations per chunk.
- Only extract entities with business significance. DO NOT extract:
  * Temporary variables, SQL aliases, local variables (i, j, x, temp, result)
  * Generic programming constructs (String, Integer, Object, List, Map)
  * Internal function names with no business meaning
- For code/SQL chunks, prioritize: API, Controller, Service, Class, Method, Table, Column, Batch, Job, Config, ExternalSystem
- For document/text chunks, prioritize: BusinessObject, BusinessProcess, ProcessStep, BusinessRule, Role, System, DataObject, Concept
- Only include entities and relations where confidence >= 0.75

For each entity provide:
- name: the exact name as it appears
- entity_type: one of [system, module, table, column, api, process, document, person, organization, role, term, concept, file, service, database, screen, field, event, rule]
- description: brief description if available
- confidence: 0.0-1.0

For each relation provide:
- from_entity: source entity name
- to_entity: target entity name
- relation_type: one of [belongs_to, contains, depends_on, calls, reads_from, writes_to, references, inherits, implements, connects_to, triggers, produces, consumes, manages, describes, related_to, part_of, used_by, defined_in]
- description: brief description of the relation
- confidence: 0.0-1.0
- evidence_text: the exact quote supporting this relation

Respond in JSON format only:
```json
{{
  "entities": [
    {{"name": "...", "entity_type": "...", "description": "...", "confidence": 0.9}}
  ],
  "relations": [
    {{"from_entity": "...", "to_entity": "...", "relation_type": "...", "description": "...", "confidence": 0.8, "evidence_text": "..."}}
  ]
}}
```

CHUNK TEXT:
---
{chunk_text}
---

SOURCE: {source_uri} (page: {page}, section: {section_title})
"""


def build_extraction_prompt(chunk: DocumentChunk) -> str:
    """Build the extraction prompt for a chunk."""
    return EXTRACTION_PROMPT.format(
        chunk_text=chunk.content,
        source_uri=chunk.source_uri or "unknown",
        page=chunk.page or "N/A",
        section_title=chunk.section_title or "N/A",
    )


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------


def parse_llm_json_response(response_text: str) -> dict[str, Any]:
    """Parse LLM JSON response, handling code fences and common issues.

    Handles:
    - ```json ... ``` code fences
    - ``` ... ``` without json tag
    - Direct JSON
    - Trailing commas (basic cleanup)
    """
    text = response_text.strip()

    # Strip code fences
    code_fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    match = re.search(code_fence_pattern, text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    # Try to find JSON object if text has preamble
    if not text.startswith("{"):
        brace_start = text.find("{")
        if brace_start >= 0:
            text = text[brace_start:]

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM JSON response: {e}\nText: {text[:200]}") from e


# ---------------------------------------------------------------------------
# Base extractor
# ---------------------------------------------------------------------------


class BaseGraphExtractor(ABC):
    """Abstract base for graph extractors."""

    def __init__(self, config: Optional[ExtractorConfig] = None):
        self.config = config or ExtractorConfig()

    @abstractmethod
    def extract_chunk(self, chunk: DocumentChunk) -> ExtractionResult:
        """Extract entities and relations from a single chunk."""
        ...

    def extract_chunks(self, chunks: list[DocumentChunk]) -> list[ExtractionResult]:
        """Extract from multiple chunks."""
        results = []
        for chunk in chunks:
            try:
                result = self.extract_chunk(chunk)
                results.append(result)
            except Exception as e:
                logger.error(f"Extraction failed for chunk {chunk.chunk_id}: {e}")
                results.append(ExtractionResult(
                    chunk_id=chunk.chunk_id,
                    errors=[str(e)],
                ))
        logger.info(f"Extracted from {len(results)}/{len(chunks)} chunks")
        return results


# ---------------------------------------------------------------------------
# Bedrock-based extractor
# ---------------------------------------------------------------------------


class GraphExtractor(BaseGraphExtractor):
    """LLM-based graph extractor using Bedrock Claude.

    Calls bedrock_client.converse() to extract entities/relations.
    """

    def __init__(
        self,
        config: Optional[ExtractorConfig] = None,
        bedrock_client=None,
    ):
        super().__init__(config)
        self._bedrock_client = bedrock_client

    @property
    def bedrock_client(self):
        if self._bedrock_client is None:
            from hermes_bedrock_agent.clients.bedrock_client import get_bedrock_client
            self._bedrock_client = get_bedrock_client()
        return self._bedrock_client

    def extract_chunk(self, chunk: DocumentChunk) -> ExtractionResult:
        """Extract graph from chunk via Bedrock Claude."""
        prompt = build_extraction_prompt(chunk)

        response = self.bedrock_client.converse(
            model_id=self.config.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inference_config={
                "maxTokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            },
        )

        # Extract text from response
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])
        response_text = ""
        for block in content_blocks:
            if "text" in block:
                response_text += block["text"]

        if not response_text:
            return ExtractionResult(chunk_id=chunk.chunk_id, errors=["Empty LLM response"])

        try:
            parsed = parse_llm_json_response(response_text)
        except ValueError as e:
            return ExtractionResult(chunk_id=chunk.chunk_id, errors=[str(e)])

        return self._build_result(parsed, chunk)

    def _build_result(self, parsed: dict, chunk: DocumentChunk) -> ExtractionResult:
        """Convert parsed JSON to ExtractionResult with quality filtering."""
        result = _build_extraction_result(parsed, chunk, self.config.model_id)

        # Apply confidence filter
        min_conf = self.config.min_confidence
        result.entities = [e for e in result.entities if e.confidence >= min_conf]
        result.relations = [r for r in result.relations if r.confidence >= min_conf]
        result.evidence = [ev for ev in result.evidence if ev.confidence >= min_conf]

        # Apply max entities/relations per chunk
        if len(result.entities) > self.config.max_entities_per_chunk:
            # Sort by confidence descending, keep top N
            result.entities.sort(key=lambda e: e.confidence, reverse=True)
            result.entities = result.entities[:self.config.max_entities_per_chunk]

        if len(result.relations) > self.config.max_relations_per_chunk:
            result.relations.sort(key=lambda r: r.confidence, reverse=True)
            result.relations = result.relations[:self.config.max_relations_per_chunk]

        # Filter out noise entities (temporary variables, SQL aliases, etc.)
        result.entities = [e for e in result.entities if not _is_noise_entity(e)]

        # Re-filter relations to only include those referencing remaining entities
        kept_entity_ids = {e.entity_id for e in result.entities}
        result.relations = [
            r for r in result.relations
            if r.source_entity_id in kept_entity_ids or r.target_entity_id in kept_entity_ids
        ]

        return result


# ---------------------------------------------------------------------------
# Mock extractor
# ---------------------------------------------------------------------------


class MockGraphExtractor(BaseGraphExtractor):
    """Deterministic mock extractor for testing.

    Generates fake entities/relations from chunk metadata. No LLM calls.
    """

    def extract_chunk(self, chunk: DocumentChunk) -> ExtractionResult:
        """Generate deterministic fake graph from chunk."""
        # Generate entity from chunk content
        entity_name = f"Entity_from_{chunk.chunk_id[:8]}"
        entity_id = _make_entity_id("concept", entity_name)

        entity = GraphEntity(
            entity_id=entity_id,
            name=entity_name,
            canonical_name=entity_name.lower().replace("_", " "),
            entity_type=EntityType.CONCEPT,
            description=f"Mock entity from chunk {chunk.chunk_id}",
            source_chunk_ids=[chunk.chunk_id],
            confidence=0.85,
            model_name="mock-extractor",
        )

        # Generate a second entity if content is long enough
        entities = [entity]
        relations = []
        evidence = []

        if len(chunk.content) > 50:
            entity2_name = f"Target_from_{chunk.chunk_id[:8]}"
            entity2_id = _make_entity_id("system", entity2_name)
            entity2 = GraphEntity(
                entity_id=entity2_id,
                name=entity2_name,
                canonical_name=entity2_name.lower().replace("_", " "),
                entity_type=EntityType.SYSTEM,
                description=f"Mock target entity from chunk {chunk.chunk_id}",
                source_chunk_ids=[chunk.chunk_id],
                confidence=0.8,
                model_name="mock-extractor",
            )
            entities.append(entity2)

            # Relation
            rel_id = _make_relation_id(entity_id, "depends_on", entity2_id)
            relation = GraphRelation(
                relation_id=rel_id,
                source_entity_id=entity_id,
                target_entity_id=entity2_id,
                relation_type=RelationType.DEPENDS_ON,
                description="Mock dependency relation",
                source_chunk_id=chunk.chunk_id,
                source_chunk_ids=[chunk.chunk_id],
                confidence=0.75,
                model_name="mock-extractor",
            )
            relations.append(relation)

            # Evidence
            ev_id = _make_evidence_id(rel_id, chunk.chunk_id)
            ev = EvidenceRecord(
                evidence_id=ev_id,
                relation_id=rel_id,
                source_chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_uri=chunk.source_uri,
                evidence_text=chunk.content[:100],
                page=chunk.page,
                section_title=chunk.section_title,
                confidence=0.75,
                model_name="mock-extractor",
            )
            evidence.append(ev)

        return ExtractionResult(
            entities=entities,
            relations=relations,
            evidence=evidence,
            chunk_id=chunk.chunk_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_noise_entity(entity: GraphEntity) -> bool:
    """Check if an entity is likely noise (temp vars, aliases, etc.).

    Filters out:
    - Single-character names (e.g., 'i', 'j', 'x')
    - SQL aliases (e.g., 'A', 'B', 'T1')
    - Java/code local vars (camelCase single words < 4 chars)
    - Pure numbers
    - Common noise patterns
    """
    name = entity.name.strip()
    lower = name.lower()

    # Too short
    if len(name) <= 2:
        return True

    # Pure numbers
    if name.isdigit():
        return True

    # SQL alias patterns: single letter or letter+digit
    import re
    if re.match(r'^[A-Za-z]\d?$', name):
        return True

    # Common code noise
    noise_patterns = {
        'args', 'argv', 'ctx', 'err', 'tmp', 'temp', 'var', 'val',
        'obj', 'str', 'num', 'int', 'bool', 'null', 'none', 'self',
        'this', 'super', 'new', 'void', 'return', 'true', 'false',
        'string', 'integer', 'object', 'list', 'map', 'set',
        'result', 'response', 'request', 'data', 'item', 'value',
        'key', 'index', 'count', 'size', 'length', 'type', 'name',
    }
    if lower in noise_patterns:
        return True

    return False


def _make_entity_id(entity_type: str, canonical_name: str) -> str:
    """Generate stable entity_id from type + canonical_name."""
    raw = f"{entity_type}:{canonical_name}".lower()
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"ent_{h}"


def _make_relation_id(source_id: str, rel_type: str, target_id: str) -> str:
    """Generate stable relation_id."""
    raw = f"{source_id}:{rel_type}:{target_id}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"rel_{h}"


def _make_evidence_id(element_id: str, chunk_id: str) -> str:
    """Generate stable evidence_id."""
    raw = f"{element_id}:{chunk_id}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"ev_{h}"


def _build_extraction_result(
    parsed: dict[str, Any],
    chunk: DocumentChunk,
    model_name: str = "",
) -> ExtractionResult:
    """Convert parsed LLM JSON to typed ExtractionResult."""
    entities: list[GraphEntity] = []
    relations: list[GraphRelation] = []
    evidence: list[EvidenceRecord] = []
    errors: list[str] = []

    # Parse entities
    for raw_ent in parsed.get("entities", []):
        try:
            name = raw_ent.get("name", "")
            etype_str = raw_ent.get("entity_type", "unknown")
            try:
                etype = EntityType(etype_str.lower())
            except ValueError:
                etype = EntityType.UNKNOWN

            canonical = name.strip().lower()
            eid = _make_entity_id(etype.value, canonical)

            entity = GraphEntity(
                entity_id=eid,
                name=name,
                canonical_name=canonical,
                entity_type=etype,
                description=raw_ent.get("description", ""),
                source_chunk_ids=[chunk.chunk_id],
                confidence=float(raw_ent.get("confidence", 0.5)),
                model_name=model_name,
            )
            entities.append(entity)
        except Exception as e:
            errors.append(f"Entity parse error: {e}")

    # Build entity name → id map for relations
    name_to_id = {}
    for ent in entities:
        name_to_id[ent.name.lower()] = ent.entity_id
        name_to_id[ent.canonical_name] = ent.entity_id

    # Parse relations
    for raw_rel in parsed.get("relations", []):
        try:
            from_name = raw_rel.get("from_entity", "").strip().lower()
            to_name = raw_rel.get("to_entity", "").strip().lower()
            rtype_str = raw_rel.get("relation_type", "related_to")

            try:
                rtype = RelationType(rtype_str.lower())
            except ValueError:
                rtype = RelationType.CUSTOM

            from_id = name_to_id.get(from_name, _make_entity_id("unknown", from_name))
            to_id = name_to_id.get(to_name, _make_entity_id("unknown", to_name))
            rid = _make_relation_id(from_id, rtype.value, to_id)

            ev_text = raw_rel.get("evidence_text", "")
            ev_id = _make_evidence_id(rid, chunk.chunk_id)

            relation = GraphRelation(
                relation_id=rid,
                source_entity_id=from_id,
                target_entity_id=to_id,
                relation_type=rtype,
                description=raw_rel.get("description", ""),
                source_chunk_id=chunk.chunk_id,
                source_chunk_ids=[chunk.chunk_id],
                evidence_id=ev_id,
                evidence_text=ev_text,
                confidence=float(raw_rel.get("confidence", 0.5)),
                model_name=model_name,
            )
            relations.append(relation)

            # Create evidence record
            if ev_text:
                ev = EvidenceRecord(
                    evidence_id=ev_id,
                    relation_id=rid,
                    source_chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    source_uri=chunk.source_uri,
                    evidence_text=ev_text,
                    page=chunk.page,
                    section_title=chunk.section_title,
                    confidence=float(raw_rel.get("confidence", 0.5)),
                    model_name=model_name,
                )
                evidence.append(ev)
        except Exception as e:
            errors.append(f"Relation parse error: {e}")

    return ExtractionResult(
        entities=entities,
        relations=relations,
        evidence=evidence,
        chunk_id=chunk.chunk_id,
        errors=errors,
    )
