"""Pydantic models for the graph pipeline."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PipelineNode(BaseModel):
    id: str
    labels: str = "Entity"
    name: str
    display_name: str = ""
    description: str = ""
    project_name: str
    project_id: str
    workbook_name: str = ""
    sheet_name: str = ""
    source_file: str = ""
    evidence_text: str = ""
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    review_status: Literal["verified", "pending", "rejected"] = "pending"
    view_scope: Literal["core", "detail", "evidence"] = "core"
    entity_type: str = "Unknown"
    layer: str = "project"
    category: str = ""
    importance: int = 1
    flow_node_kind: str = ""
    parent_function_id: str = ""
    sequence_no: str = ""
    properties_text: str = ""
    aliases_text: str = ""
    sheet_type: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.display_name:
            self.display_name = self.name


class PipelineEdge(BaseModel):
    id: str
    start_id: str
    end_id: str
    type: str
    project_name: str
    project_id: str
    source_file: str = ""
    evidence_text: str = ""
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    review_status: Literal["verified", "pending", "rejected"] = "pending"
    view_scope: Literal["core", "detail", "evidence"] = "core"
    link_method: str = "explicit_text"
    layer: str = "project"
    edge_label: str = ""
    condition_text: str = ""
    branch_label: str = ""
    sequence_no: str = ""


# ── Raw extraction models (LLM output, before normalization) ──────────────────

class RawNode(BaseModel):
    """LLM-extracted node before normalization."""
    id: str
    labels: str = ""
    name: str = ""
    display_name: str = ""
    description: str = ""
    entity_type: str = "Unknown"
    layer: str = "project"
    category: str = ""
    evidence_text: str = ""
    confidence: float = 0.75
    review_status: str = "pending"
    importance: int = 1
    view_scope: str = "core"
    flow_node_kind: str = ""
    parent_function_id: str = ""
    sequence_no: str = ""
    properties_text: str = ""
    # source metadata (filled in by extractor)
    project_name: str = ""
    project_id: str = ""
    workbook_name: str = ""
    sheet_name: str = ""
    sheet_type: str = ""
    source_file: str = ""


class RawEdge(BaseModel):
    """LLM-extracted edge before normalization."""
    from_id: str
    to_id: str
    type: str = "RELATED_TO"
    edge_label: str = ""
    condition_text: str = ""
    branch_label: str = ""
    evidence_text: str = ""
    confidence: float = 0.75
    link_method: str = "explicit_text"
    review_status: str = "pending"
    sequence_no: str = ""
    layer: str = "project"
    # source metadata
    project_name: str = ""
    project_id: str = ""
    workbook_name: str = ""
    sheet_name: str = ""
    source_file: str = ""


class ExtractionResult(BaseModel):
    """Output from a single LLM extraction call."""
    source_file: str
    workbook_name: str
    sheet_name: str
    sheet_type: str = ""
    nodes: list[RawNode] = Field(default_factory=list)
    edges: list[RawEdge] = Field(default_factory=list)
    error: Optional[str] = None


# ── Pipeline result ───────────────────────────────────────────────────────────

class PipelineResult(BaseModel):
    project_id: str
    project_name: str
    nodes: list[PipelineNode] = Field(default_factory=list)
    edges: list[PipelineEdge] = Field(default_factory=list)
    output_dir: str = ""
    load_stats: dict = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    # v3.1 extended stats
    files_processed: int = 0
    display_nodes_count: int = 0
    display_edges_count: int = 0
    candidate_links_count: int = 0
    review_tasks_count: int = 0
    has_p0: bool = False

    @property
    def summary(self) -> dict:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "display_nodes": self.display_nodes_count,
            "display_edges": self.display_edges_count,
            "files_processed": self.files_processed,
            "candidate_links": self.candidate_links_count,
            "review_tasks": self.review_tasks_count,
            "has_p0": self.has_p0,
            "validation_errors": len(self.validation_errors),
            "load_stats": self.load_stats,
            "output_dir": self.output_dir,
        }
