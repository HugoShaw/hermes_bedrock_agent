"""
Excel schemas for V2 workbook profiling and evidence extraction.

Defines Pydantic models for workbook, sheet, table region, row, and cell records.
These are independent from the V2 graph schemas and serve as intermediate
representations between raw Excel data and evidence chunks.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


# Allowed sheet type classifications
ALLOWED_SHEET_TYPES = {
    "business_process_sheet",
    "field_mapping_sheet",
    "api_interface_sheet",
    "data_dictionary_sheet",
    "code_master_sheet",
    "business_rule_sheet",
    "test_case_sheet",
    "screen_definition_sheet",
    "system_config_sheet",
    "operation_sheet",
    "unknown_sheet",
}


class ExcelWorkbookRecord(BaseModel):
    """Represents a single Excel workbook in the V2 pipeline."""

    workbook_id: str = Field(..., description="Unique workbook identifier")
    dataset: str = Field(default="sample_20260519", description="Dataset name")
    run_id: str = Field(default="sample_20260519_excel_v1", description="Run identifier")
    source_path: str = Field(..., description="S3 key or local file path")
    file_name: str = Field(..., description="Filename without path")
    file_extension: str = Field(..., description="File extension (.xlsx, .xlsm, .xls)")
    sheet_count: int = Field(default=0, description="Total number of sheets")
    visible_sheet_count: int = Field(default=0, description="Number of visible sheets")
    hidden_sheet_count: int = Field(default=0, description="Number of hidden sheets")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @staticmethod
    def generate_id(source_path: str, dataset: str) -> str:
        """Generate deterministic workbook_id from source_path and dataset."""
        raw = f"wb:{dataset}:{source_path}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "ExcelWorkbookRecord":
        return cls.model_validate_json(line.strip())


class ExcelSheetRecord(BaseModel):
    """Represents a single sheet within an Excel workbook."""

    sheet_id: str = Field(..., description="Unique sheet identifier")
    workbook_id: str = Field(..., description="Parent workbook identifier")
    sheet_name: str = Field(..., description="Sheet tab name")
    sheet_index: int = Field(..., description="0-based sheet index")
    visible: bool = Field(default=True, description="Whether sheet is visible")
    max_row: int = Field(default=0, description="Maximum row number with data")
    max_column: int = Field(default=0, description="Maximum column number with data")
    non_empty_cell_count: int = Field(default=0, description="Count of non-empty cells")
    merged_cell_ranges: list[str] = Field(default_factory=list, description="List of merged cell range strings")
    has_formula: bool = Field(default=False, description="Whether sheet contains formulas")
    has_comments: bool = Field(default=False, description="Whether sheet contains comments")
    guessed_sheet_type: str = Field(default="unknown_sheet", description="Inferred sheet type")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Sheet type confidence")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("guessed_sheet_type")
    @classmethod
    def validate_sheet_type(cls, v: str) -> str:
        if v not in ALLOWED_SHEET_TYPES:
            return "unknown_sheet"
        return v

    @staticmethod
    def generate_id(workbook_id: str, sheet_name: str, sheet_index: int) -> str:
        """Generate deterministic sheet_id."""
        raw = f"sh:{workbook_id}:{sheet_name}:{sheet_index}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "ExcelSheetRecord":
        return cls.model_validate_json(line.strip())


class ExcelTableRegion(BaseModel):
    """Represents a detected table region within a sheet."""

    table_region_id: str = Field(..., description="Unique table region identifier")
    workbook_id: str = Field(..., description="Parent workbook identifier")
    sheet_id: str = Field(..., description="Parent sheet identifier")
    sheet_name: str = Field(..., description="Sheet tab name")
    cell_range: str = Field(..., description="Cell range string (e.g. B3:H42)")
    header_rows: list[int] = Field(default_factory=list, description="Row numbers that are headers")
    data_start_row: int | None = Field(default=None, description="First data row number")
    data_end_row: int | None = Field(default=None, description="Last data row number")
    columns: list[str] = Field(default_factory=list, description="Detected column names")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Detection confidence")
    region_type: str = Field(default="unknown_table", description="Table region type")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @staticmethod
    def generate_id(sheet_id: str, cell_range: str) -> str:
        """Generate deterministic table_region_id."""
        raw = f"tr:{sheet_id}:{cell_range}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "ExcelTableRegion":
        return cls.model_validate_json(line.strip())


class ExcelRowRecord(BaseModel):
    """Represents a normalized row from a table region."""

    row_id: str = Field(..., description="Unique row identifier")
    workbook_id: str = Field(..., description="Parent workbook identifier")
    sheet_id: str = Field(..., description="Parent sheet identifier")
    table_region_id: str | None = Field(default=None, description="Parent table region identifier")
    sheet_name: str = Field(..., description="Sheet tab name")
    row_number: int = Field(..., description="1-based row number in the sheet")
    values: dict[str, Any] = Field(default_factory=dict, description="Column name -> value mapping")
    normalized_values: dict[str, str] = Field(default_factory=dict, description="Column name -> string value")
    source_cell_refs: dict[str, str] = Field(default_factory=dict, description="Column name -> cell reference")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @staticmethod
    def generate_id(sheet_id: str, row_number: int, table_region_id: str | None = None) -> str:
        """Generate deterministic row_id."""
        raw = f"row:{sheet_id}:{table_region_id or 'none'}:{row_number}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "ExcelRowRecord":
        return cls.model_validate_json(line.strip())


class ExcelCellEvidence(BaseModel):
    """Represents a single cell for evidence sampling."""

    cell_id: str = Field(..., description="Unique cell identifier")
    workbook_id: str = Field(..., description="Parent workbook identifier")
    sheet_id: str = Field(..., description="Parent sheet identifier")
    sheet_name: str = Field(..., description="Sheet tab name")
    cell_ref: str = Field(..., description="Cell reference (e.g. B3)")
    value: str | None = Field(default=None, description="Cell display value")
    formula: str | None = Field(default=None, description="Cell formula if present")
    comment: str | None = Field(default=None, description="Cell comment if present")
    merged_parent: str | None = Field(default=None, description="Parent merged cell reference")
    style_hint: dict[str, Any] = Field(default_factory=dict, description="Style hints (bold, bg color, etc.)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @staticmethod
    def generate_id(sheet_id: str, cell_ref: str) -> str:
        """Generate deterministic cell_id."""
        raw = f"cell:{sheet_id}:{cell_ref}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "ExcelCellEvidence":
        return cls.model_validate_json(line.strip())
