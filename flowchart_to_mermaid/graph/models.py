"""Data models for the flowchart-to-mermaid pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TextSource(str, Enum):
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    MANUAL = "manual"


class ShapeType(str, Enum):
    PROCESS = "process"
    DECISION = "decision"
    TERMINATOR = "terminator"
    ANNOTATION = "annotation"
    GROUP = "group"
    LINE = "line"
    UNKNOWN = "unknown"


class NodeType(str, Enum):
    PROCESS = "process"
    DECISION = "decision"
    TERMINATOR = "terminator"
    API = "api"
    FILE = "file"
    LOOP = "loop"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


class UncertaintyType(str, Enum):
    EDGE = "edge"
    NODE = "node"
    GROUP = "group"
    LABEL = "label"


class TextBlock(BaseModel):
    """A text element extracted from the source document."""
    id: str
    text: str
    bbox: list[float] = Field(description="[x1, y1, x2, y2]")
    confidence: float = 1.0
    source: TextSource = TextSource.PDF_TEXT
    font_size: Optional[float] = None
    color: Optional[str] = None


class Shape(BaseModel):
    """A geometric shape detected in the image."""
    id: str
    type: ShapeType = ShapeType.UNKNOWN
    bbox: list[float] = Field(description="[x1, y1, x2, y2]")
    fill_color: Optional[str] = None
    stroke_color: Optional[str] = None
    confidence: float = 0.5
    is_dashed: bool = False


class FlowNode(BaseModel):
    """A node in the flow graph."""
    id: str
    label: str
    type: NodeType = NodeType.PROCESS
    bbox: list[float] = Field(default_factory=list, description="[x1, y1, x2, y2]")
    group_id: Optional[str] = None
    source_text_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.9
    uncertain: bool = False


class FlowEdge(BaseModel):
    """An edge (connection) between nodes."""
    id: str
    source: str
    target: str
    label: Optional[str] = None
    path: list[list[float]] = Field(default_factory=list, description="[[x,y], ...]")
    confidence: float = 0.8
    uncertain: bool = False
    inferred: bool = False


class FlowGroup(BaseModel):
    """A grouping of nodes (subgraph)."""
    id: str
    label: str
    bbox: list[float] = Field(default_factory=list, description="[x1, y1, x2, y2]")
    node_ids: list[str] = Field(default_factory=list)
    parent_group_id: Optional[str] = None
    confidence: float = 0.9


class UncertainPoint(BaseModel):
    """A point of uncertainty requiring human review."""
    type: UncertaintyType
    message: str
    related_ids: list[str] = Field(default_factory=list)
    suggested_review_image: Optional[str] = None


class PageFlow(BaseModel):
    """Flow data for a single page."""
    page_index: int = 0
    width: int = 0
    height: int = 0
    text_blocks: list[TextBlock] = Field(default_factory=list)
    shapes: list[Shape] = Field(default_factory=list)
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)
    groups: list[FlowGroup] = Field(default_factory=list)
    uncertain_points: list[UncertainPoint] = Field(default_factory=list)


class FlowDocument(BaseModel):
    """Complete flow document with all pages."""
    source_file: str = ""
    source_type: str = "pdf"
    pages: list[PageFlow] = Field(default_factory=list)
    direction: str = "TD"
    metadata: dict = Field(default_factory=dict)
