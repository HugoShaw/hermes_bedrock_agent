"""Pydantic schemas for chunks, graph entities, and retrieval results."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    chunk_id: str
    content: str
    chunk_type: str  # overview|flowchart|mapping_table|data_condition|business_rule|api_spec|cross_sheet_summary
    sheet_index: int
    sheet_name: str
    workbook_name: str
    source_pdf_s3_path: str
    source_excel_s3_path: str
    source_markdown_s3_path: str
    related_sheets: list[int] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    embedding_text: str
    project_id: str = ""


class EmbeddedChunk(Chunk):
    embedding: list[float] = Field(default_factory=list)


class GraphNode(BaseModel):
    node_id: str
    label: str  # System|API|Field|Sheet|MappingRule|BusinessRule|DataFlow
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence_pdf_s3_path: str = ""


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    relationship: str  # MAPS_TO|CALLS_API|TRANSFORMS|FLOWS_TO|DEFINED_IN|HAS_CONDITION
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence_pdf_s3_path: str = ""


class RetrievedChunk(BaseModel):
    chunk_id: str
    content: str
    chunk_type: str
    sheet_index: int
    sheet_name: str
    score: float
    source_pdf_s3_path: str
    source_excel_s3_path: str
    project_id: str = ""


class GraphContext(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class QAResponse(BaseModel):
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)
    graph_context: Optional[GraphContext] = None
    # Graph guidance status: "strong", "weak", "none", "disabled", "error"
    guidance_status: str = "none"


class QAAnswerResponse(QAResponse):
    answer: str = ""
    graph_context_text: str = ""
    evidence_images_used: list[str] = Field(default_factory=list)
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
