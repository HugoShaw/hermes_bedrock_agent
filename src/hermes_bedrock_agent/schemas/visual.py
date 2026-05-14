"""Visual content data models — VLM-parsed images, diagrams, tables.

VisualBlock represents structured output from Vision Language Model parsing
of images, PDF page screenshots, architecture diagrams, flowcharts, and tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VisualType(str, Enum):
    """Types of visual content."""

    DIAGRAM = "diagram"
    ARCHITECTURE = "architecture"
    FLOWCHART = "flowchart"
    SEQUENCE_DIAGRAM = "sequence_diagram"
    ER_DIAGRAM = "er_diagram"
    TABLE = "table"
    CHART = "chart"
    FORM = "form"
    PAGE_SCREENSHOT = "page_screenshot"
    PHOTOGRAPH = "photograph"
    UI_MOCKUP = "ui_mockup"
    LOGO = "logo"
    UNKNOWN = "unknown"


class VisualBlock(BaseModel):
    """Structured output from VLM parsing of a visual element.

    Each image/page/diagram produces one VisualBlock containing the VLM's
    interpretation as structured text, plus metadata for traceability.
    """

    # Identity
    visual_id: str = Field(..., description="Stable ID: sha256(document_id + page + image_id)")
    document_id: str = Field(..., description="Parent document ID")
    source_uri: str = Field(default="", description="S3 URI of the image or parent PDF")
    page: int = Field(default=1, description="Page number in source document")
    image_id: str = Field(default="", description="Image identifier within document")

    # Classification
    visual_type: VisualType = Field(default=VisualType.UNKNOWN)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="VLM confidence")

    # VLM-extracted content
    visual_summary: str = Field(default="", description="Brief description of what the image shows")
    extracted_text: str = Field(default="", description="All readable text extracted from the image")
    table_markdown: str = Field(default="", description="Markdown table if table detected")
    diagram_nodes: list[str] = Field(default_factory=list, description="Node/entity labels in diagrams")
    diagram_edges: list[str] = Field(default_factory=list, description="Edge/connection descriptions")
    detected_entities: list[str] = Field(default_factory=list, description="Named entities detected")

    # Image data
    image_base64: str = Field(default="", description="Base64-encoded image data")
    image_format: str = Field(default="", description="Image format (png, jpeg, gif, webp)")
    width: int = Field(default=0, ge=0, description="Image width in pixels")
    height: int = Field(default=0, ge=0, description="Image height in pixels")
    bbox: Optional[list[float]] = Field(
        default=None,
        description="Bounding box [x1, y1, x2, y2] normalized 0-1",
    )

    # Processing metadata
    model_name: str = Field(default="", description="VLM model used for parsing")
    content_hash: str = Field(default="", description="SHA-256 of source image bytes")
    acl: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_structured_content(self) -> bool:
        """Check if VLM produced structured extraction."""
        return bool(self.extracted_text.strip() or self.table_markdown.strip())

    @property
    def combined_text(self) -> str:
        """Get all text content for embedding/chunking."""
        parts = []
        if self.visual_summary:
            parts.append(self.visual_summary)
        if self.extracted_text:
            parts.append(self.extracted_text)
        if self.table_markdown:
            parts.append(self.table_markdown)
        return "\n\n".join(parts)
