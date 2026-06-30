"""Pydantic models for the parsing pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FileType(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"
    IMAGE = "image"
    MERMAID = "mermaid"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class S3File(BaseModel):
    key: str
    size: int
    file_type: FileType
    local_path: Optional[str] = None


class WorkManifest(BaseModel):
    s3_prefix: str
    files: list[S3File] = Field(default_factory=list)
    excel_files: list[S3File] = Field(default_factory=list)
    ground_truth_files: dict[str, S3File] = Field(default_factory=dict)


class SheetInfo(BaseModel):
    index: int
    name: str
    rows: int
    cols: int
    has_shapes: bool = False
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0


class SheetPDF(BaseModel):
    sheet_info: SheetInfo
    pdf_path: str
    page_size: tuple[float, float] = (0.0, 0.0)
    pages: int = 1
    paper_label: str = ""


class SheetImages(BaseModel):
    sheet_info: SheetInfo
    full_image_path: str
    page_image_paths: list[str] = Field(default_factory=list)
    tile_paths: list[str] = Field(default_factory=list)
    vlm_ready_path: str = ""
    width_px: int = 0
    height_px: int = 0
    dpi_used: int = 150
    page_count: int = 1
    rendering_strategy: str = "single_page"


class ParseResult(BaseModel):
    sheet_info: SheetInfo
    markdown: str
    mermaid: Optional[str] = None
    images: Optional[SheetImages] = None
    chunk_count: int = 0
