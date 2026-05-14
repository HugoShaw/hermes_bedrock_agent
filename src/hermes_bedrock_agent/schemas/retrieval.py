"""Retrieval and generation data models.

Covers the hybrid retrieval pipeline:
- Text evidence (from OpenSearch)
- Graph evidence (from Neptune traversal)
- Fused context (merged results)
- Answer generation output
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RetrievalSource(str, Enum):
    """Source of a retrieval result."""

    OPENSEARCH_TEXT = "opensearch_text"
    OPENSEARCH_VECTOR = "opensearch_vector"
    NEPTUNE_GRAPH = "neptune_graph"
    BEDROCK_KB = "bedrock_kb"


class TextEvidence(BaseModel):
    """A text-based retrieval result from OpenSearch or Bedrock KB.

    Represents a chunk retrieved via text/vector search, with its
    relevance score and source traceability.
    """

    evidence_id: str = Field(..., description="Unique evidence identifier")
    chunk_id: str = Field(..., description="Source chunk ID")
    document_id: str = Field(...)
    source_uri: str = Field(default="")

    # Content
    content: str = Field(..., description="Retrieved text content")
    section_title: str = Field(default="")
    page: Optional[int] = Field(default=None)

    # Retrieval metadata
    source: RetrievalSource = Field(default=RetrievalSource.OPENSEARCH_TEXT)
    score: float = Field(default=0.0, description="Relevance score (0-1 normalized)")
    rank: int = Field(default=0, ge=0, description="Position in retrieval results")

    # Traceability
    query_text: str = Field(default="", description="Query that produced this result")
    model_name: str = Field(default="", description="Embedding model (for vector search)")
    acl: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphEvidence(BaseModel):
    """A graph-based retrieval result from Neptune traversal.

    Represents entities, relations, or subgraph paths found via
    graph queries relevant to the user's question.
    """

    evidence_id: str = Field(..., description="Unique evidence identifier")
    entity_id: Optional[str] = Field(default=None, description="Primary entity found")
    relation_id: Optional[str] = Field(default=None, description="Relation traversed")

    # Content (human-readable representation)
    content: str = Field(..., description="Natural language description of graph evidence")
    path_description: str = Field(
        default="",
        description="Human-readable path (e.g. 'SystemA --calls--> ServiceB --reads--> TableC')",
    )

    # Graph structure
    entities_involved: list[str] = Field(default_factory=list, description="Entity IDs in this evidence")
    relations_involved: list[str] = Field(default_factory=list, description="Relation IDs traversed")
    hop_count: int = Field(default=0, ge=0, description="Graph traversal depth")

    # Retrieval metadata
    source: RetrievalSource = Field(default=RetrievalSource.NEPTUNE_GRAPH)
    score: float = Field(default=0.0, description="Relevance/centrality score")
    rank: int = Field(default=0, ge=0)
    cypher_query: str = Field(default="", description="Cypher query used")

    # Traceability
    source_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk IDs that provided evidence for the graph elements",
    )
    acl: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FusedContext(BaseModel):
    """Merged retrieval context combining text and graph evidence.

    Produced by the fusion stage, this is the complete context passed
    to the answer generation LLM.
    """

    query: str = Field(..., description="Original user query")
    text_evidence: list[TextEvidence] = Field(default_factory=list)
    graph_evidence: list[GraphEvidence] = Field(default_factory=list)
    fusion_strategy: str = Field(default="rrf", description="Strategy used to merge results")

    # Computed fields
    total_evidence_count: int = Field(default=0)
    total_token_estimate: int = Field(default=0, description="Estimated token count for context")

    # Metadata
    retrieval_time_ms: Optional[int] = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: object) -> None:
        """Compute derived fields after initialization."""
        if self.total_evidence_count == 0:
            self.total_evidence_count = len(self.text_evidence) + len(self.graph_evidence)


class Citation(BaseModel):
    """A citation linking an answer span to its source evidence."""

    citation_id: str = Field(default="")
    evidence_id: str = Field(..., description="Evidence record this cites")
    source_uri: str = Field(default="")
    document_id: str = Field(default="")
    chunk_id: str = Field(default="")
    page: Optional[int] = Field(default=None)
    section_title: str = Field(default="")
    quote: str = Field(default="", description="Relevant quote from the evidence")
    citation_type: RetrievalSource = Field(default=RetrievalSource.OPENSEARCH_TEXT)


class AnswerResult(BaseModel):
    """Final answer produced by the generation stage.

    Contains the generated answer text, citations, confidence,
    and full traceability back to source evidence.
    """

    query: str = Field(..., description="Original user query")
    answer: str = Field(..., description="Generated answer text")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Answer confidence score")

    # Citations
    citations: list[Citation] = Field(default_factory=list)

    # Context used
    context_token_count: int = Field(default=0)
    text_evidence_used: int = Field(default=0, description="Number of text evidence items used")
    graph_evidence_used: int = Field(default=0, description="Number of graph evidence items used")

    # Traceability (Phase 8 enhancement)
    used_chunk_ids: list[str] = Field(
        default_factory=list,
        description="All chunk_ids referenced (text + graph source_chunk_ids)",
    )
    used_graph_paths: list[str] = Field(
        default_factory=list,
        description="Graph path descriptions used in the answer",
    )
    insufficient_evidence: bool = Field(
        default=False,
        description="True if evidence was insufficient to answer fully",
    )

    # Generation metadata
    model_name: str = Field(default="", description="LLM used for generation")
    prompt_template: str = Field(default="", description="Prompt template version")
    generation_time_ms: Optional[int] = Field(default=None, ge=0)
    total_time_ms: Optional[int] = Field(default=None, ge=0, description="End-to-end query time")

    # Metadata
    metadata: dict = Field(default_factory=dict, description="Additional metadata (strategy, intent, etc.)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_citations(self) -> bool:
        return len(self.citations) > 0

    @property
    def citation_count(self) -> int:
        return len(self.citations)
