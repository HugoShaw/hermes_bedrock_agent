"""
Excel Visual Schema — data models for visual object extraction and analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Allowed object types
VISUAL_OBJECT_TYPES = [
    "sheet_image",
    "embedded_image",
    "shape",
    "textbox",
    "connector",
    "arrow",
    "chart",
    "group",
    "smartart",
    "drawing_xml",
    "unknown_visual",
]

# Allowed sheet types for visual analysis
VISUAL_SHEET_TYPES = [
    "flowchart_sheet",
    "overview_sheet",
    "diagram_sheet",
    "screenshot_sheet",
    "chart_sheet",
    "mixed_visual_sheet",
    "text_only_sheet",
    "data_table_sheet",
]


@dataclass
class ExcelVisualWorkbookRecord:
    workbook_id: str = ""
    workbook_name: str = ""
    source_path: str = ""
    dataset: str = ""
    run_id: str = ""
    sheet_count: int = 0
    visual_sheet_count: int = 0
    image_count: int = 0
    chart_count: int = 0
    drawing_object_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExcelVisualSheetRecord:
    sheet_visual_id: str = ""
    workbook_id: str = ""
    workbook_name: str = ""
    sheet_id: str = ""
    sheet_name: str = ""
    sheet_index: int = 0
    has_visual_objects: bool = False
    has_images: bool = False
    has_charts: bool = False
    has_shapes: bool = False
    has_drawings: bool = False
    has_sheet_image: bool = False
    sheet_image_path: str = ""
    object_count: int = 0
    image_count: int = 0
    chart_count: int = 0
    shape_count: int = 0
    connector_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExcelVisualObjectRecord:
    visual_object_id: str = ""
    workbook_id: str = ""
    workbook_name: str = ""
    sheet_id: str = ""
    sheet_name: str = ""
    sheet_index: int = 0
    object_type: str = "unknown_visual"
    object_name: str = ""
    anchor_from_cell: str = ""
    anchor_to_cell: str = ""
    anchor_range: str = ""
    text: str = ""
    alt_text: str = ""
    description: str = ""
    shape_type: str = ""
    chart_type: str = ""
    image_path: str = ""
    relationship_id: str = ""
    xml_path: str = ""
    raw_xml_snippet: str = ""
    extraction_method: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    dataset: str = ""


@dataclass
class BedrockVisualAnalysisRecord:
    analysis_id: str = ""
    workbook_id: str = ""
    workbook_name: str = ""
    sheet_id: str = ""
    sheet_name: str = ""
    visual_object_id: str = ""
    image_path: str = ""
    analysis_target_type: str = ""
    model_id: str = ""
    prompt_version: str = "v1"
    language: str = "ja"
    summary: str = ""
    detected_text: list[str] = field(default_factory=list)
    detected_objects: list[dict[str, Any]] = field(default_factory=list)
    flowchart_steps: list[dict[str, Any]] = field(default_factory=list)
    diagram_nodes: list[dict[str, Any]] = field(default_factory=list)
    diagram_edges: list[dict[str, Any]] = field(default_factory=list)
    business_terms: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    api_names: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_response: str = ""
    run_id: str = ""
    dataset: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
