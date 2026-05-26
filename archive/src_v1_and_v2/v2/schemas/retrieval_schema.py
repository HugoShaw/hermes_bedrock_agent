"""
V2 Retrieval schemas — QueryIntent, RetrievalPlan, RetrievalResult, HybridContext.

These schemas support the V2 layer-aware retrieval pipeline:
- Query Router classifies intent and produces a RetrievalPlan
- Retrievers return RetrievalResult objects
- Hybrid Context Builder assembles structured HybridContext for answer generation
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


# Allowed intent classifications for V2 query routing
ALLOWED_INTENTS = {
    "definition",          # What is X? → Vector Evidence First
    "business_process",    # Explain the process → Business Graph First + Evidence
    "relationship",        # What relates to X? → Graph First + Evidence
    "dependency",          # What depends on X? → Graph First + Evidence
    "api_code_db",         # API/code/database questions → Implementation Graph First
    "impact_analysis",     # If X changes, what's affected? → Business + Implementation + Evidence
    "troubleshooting",     # How to fix/debug → Vector Evidence First + Graph Expansion
    "workflow_generation", # Generate workflow → Business Graph + Implementation Graph
    "evidence_coverage",   # Evidence coverage stats → Compute from JSONL metadata
    "unknown",             # Unclassified → Hybrid fallback
}

# Allowed retrieval paths
ALLOWED_RETRIEVAL_PATHS = {
    "vector_evidence",       # Vector similarity search in evidence store
    "business_graph",        # Business Semantic Graph traversal
    "implementation_graph",  # Implementation Graph traversal
    "hybrid",               # Combined multi-path retrieval
}


class QueryIntent(BaseModel):
    """Represents the classified intent of a user query.

    The Query Router produces this after analyzing the query text,
    language, and keywords to determine the best retrieval strategy.
    """

    query: str = Field(..., description="Original user query text")
    intent: str = Field(default="unknown", description="Classified intent type")
    language: str = Field(default="auto", description="Detected query language: ja, zh, en, mixed, auto")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Classification confidence")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional classification info (keywords, entities detected)")

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v: str) -> str:
        if v not in ALLOWED_INTENTS:
            # Fall back to unknown rather than raising — allow extensibility
            return "unknown"
        return v

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "QueryIntent":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())


class RetrievalPlan(BaseModel):
    """Represents the retrieval strategy planned for a query.

    Based on the classified intent, the Query Router produces a plan
    that determines which retrieval paths to execute and in what priority.
    """

    query: str = Field(..., description="Original user query text")
    intent: str = Field(default="unknown", description="Classified intent type")
    primary_path: str = Field(default="vector_evidence", description="Primary retrieval path")
    secondary_paths: list[str] = Field(default_factory=list, description="Secondary retrieval paths")
    need_business_graph: bool = Field(default=False, description="Whether to query Business Semantic Graph")
    need_implementation_graph: bool = Field(default=False, description="Whether to query Implementation Graph")
    need_vector_evidence: bool = Field(default=True, description="Whether to query Vector Evidence Store")
    need_graph_expansion: bool = Field(default=False, description="Whether to expand graph traversal beyond first hop")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional planning info")

    @field_validator("primary_path")
    @classmethod
    def validate_primary_path(cls, v: str) -> str:
        if v not in ALLOWED_RETRIEVAL_PATHS:
            raise ValueError(
                f"primary_path '{v}' is not allowed. "
                f"Allowed paths: {sorted(ALLOWED_RETRIEVAL_PATHS)}"
            )
        return v

    @field_validator("secondary_paths")
    @classmethod
    def validate_secondary_paths(cls, v: list[str]) -> list[str]:
        for path in v:
            if path not in ALLOWED_RETRIEVAL_PATHS:
                raise ValueError(
                    f"secondary path '{path}' is not allowed. "
                    f"Allowed paths: {sorted(ALLOWED_RETRIEVAL_PATHS)}"
                )
        return v

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "RetrievalPlan":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())


class RetrievalResult(BaseModel):
    """Represents the result from a single retrieval path.

    Each retriever (vector, business graph, implementation graph)
    returns a RetrievalResult with its matched items and relevance score.
    """

    source: str = Field(..., description="Source retrieval path: vector_evidence, business_graph, implementation_graph")
    items: list[dict[str, Any]] = Field(default_factory=list, description="Retrieved items (chunks, nodes, paths)")
    score: float | None = Field(default=None, description="Aggregate relevance score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Retrieval metadata (top_k, filters applied, etc.)")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in ALLOWED_RETRIEVAL_PATHS:
            raise ValueError(
                f"source '{v}' is not a valid retrieval path. "
                f"Allowed: {sorted(ALLOWED_RETRIEVAL_PATHS)}"
            )
        return v

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "RetrievalResult":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())


class HybridContext(BaseModel):
    """Represents the assembled hybrid context for answer generation.

    The Hybrid Context Builder produces this by combining results from
    all retrieval paths into a structured format:

    [Business Graph Context]
    [Implementation Graph Context]
    [Evidence Context]
    [Reasoning Constraints]
    """

    query: str = Field(..., description="Original user query")
    business_context: list[dict[str, Any]] = Field(default_factory=list, description="Business graph entities and relationships")
    implementation_context: list[dict[str, Any]] = Field(default_factory=list, description="Implementation graph entities and relationships")
    evidence_context: list[dict[str, Any]] = Field(default_factory=list, description="Evidence chunks with citations")
    reasoning_constraints: list[str] = Field(default_factory=list, description="Constraints for the answer generator")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Context assembly metadata (total_chars, source_counts)")

    @property
    def total_items(self) -> int:
        """Total number of context items across all sections."""
        return len(self.business_context) + len(self.implementation_context) + len(self.evidence_context)

    @property
    def total_chars(self) -> int:
        """Estimate total character count of all context."""
        total = 0
        for item in self.business_context + self.implementation_context + self.evidence_context:
            total += len(str(item))
        for constraint in self.reasoning_constraints:
            total += len(constraint)
        return total

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "HybridContext":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())
