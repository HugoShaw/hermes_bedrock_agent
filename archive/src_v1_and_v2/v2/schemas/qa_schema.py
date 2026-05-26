"""
V2 QA Debug schema — QADebugRecord.

Used by the QA Terminal V2 debug mode to capture full diagnostic
information about each query-answer cycle.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class QADebugRecord(BaseModel):
    """Captures full diagnostic information for a single QA interaction.

    The QA Terminal V2 in debug mode populates all fields to show:
    - Query classification
    - Retrieval paths taken
    - Matched entities from each graph layer
    - Graph traversal paths
    - Evidence chunks used
    - Final answer and context size

    This enables transparency and explainability of the V2 retrieval pipeline.
    """

    query: str = Field(..., description="Original user query text")
    detected_intent: str = Field(default="unknown", description="Classified query intent")
    primary_path: str = Field(default="vector_evidence", description="Primary retrieval path used")
    secondary_paths: list[str] = Field(default_factory=list, description="Secondary retrieval paths used")
    matched_business_entities: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Business graph entities matched (name, label, confidence)"
    )
    matched_implementation_entities: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Implementation graph entities matched (name, label, confidence)"
    )
    graph_paths: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Graph traversal paths found (source → relation → target chains)"
    )
    evidence_chunks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Evidence chunks used for answer (chunk_id, chunk_type, score, text_preview)"
    )
    final_context_size: int = Field(default=0, ge=0, description="Total characters in assembled context")
    answer: str | None = Field(default=None, description="Generated answer text")
    latency_ms: int = Field(default=0, ge=0, description="Total response latency in milliseconds")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of this QA interaction"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional debug metadata")

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "QADebugRecord":
        """Deserialize from a single JSONL line."""
        return cls.model_validate_json(line.strip())

    def summary(self) -> str:
        """Return a human-readable summary for terminal display."""
        lines = [
            f"Query: {self.query}",
            f"Intent: {self.detected_intent} (path: {self.primary_path})",
            f"Business entities: {len(self.matched_business_entities)}",
            f"Implementation entities: {len(self.matched_implementation_entities)}",
            f"Graph paths: {len(self.graph_paths)}",
            f"Evidence chunks: {len(self.evidence_chunks)}",
            f"Context size: {self.final_context_size} chars",
            f"Latency: {self.latency_ms} ms",
        ]
        if self.answer:
            preview = self.answer[:200] + "..." if len(self.answer) > 200 else self.answer
            lines.append(f"Answer: {preview}")
        return "\n".join(lines)
