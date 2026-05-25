"""Pydantic models for all doc_pipeline data structures."""

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
    index: int          # 1-based
    name: str
    rows: int
    cols: int
    has_shapes: bool = False
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0


class SheetPDF(BaseModel):
    sheet_info: SheetInfo
    pdf_path: str
    page_size: tuple[float, float] = (0.0, 0.0)   # width, height in points
    pages: int = 1
    paper_label: str = ""


class SheetImages(BaseModel):
    sheet_info: SheetInfo
    full_image_path: str
    tile_paths: list[str] = Field(default_factory=list)
    vlm_ready_path: str = ""
    width_px: int = 0
    height_px: int = 0
    dpi_used: int = 150


class ChunkType(str, Enum):
    OVERVIEW = "overview"
    MAPPING_TABLE = "mapping_table"
    BUSINESS_RULE = "business_rule"
    API_SPEC = "api_spec"
    FLOWCHART = "flowchart"
    DATA_CONDITION = "data_condition"
    CROSS_SHEET_SUMMARY = "cross_sheet_summary"


class Chunk(BaseModel):
    id: str
    text: str
    embedding_text: str
    chunk_type: str
    sheet_index: int
    sheet_name: str
    workbook_name: str
    source_pdf_s3_path: str
    source_excel_s3_path: str
    source_markdown_s3_path: str
    systems: str = ""           # pipe-separated
    apis: str = ""              # pipe-separated
    related_sheets: str = ""    # pipe-separated


class ParseResult(BaseModel):
    sheet_info: SheetInfo
    markdown: str
    mermaid: Optional[str] = None
    images: Optional[SheetImages] = None
    chunk_count: int = 0


class IngestStats(BaseModel):
    workbook_name: str
    chunks_total: int = 0
    lancedb_added: int = 0
    neptune_nodes: int = 0
    neptune_edges: int = 0
    neptune_errors: int = 0
