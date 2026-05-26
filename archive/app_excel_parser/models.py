"""Data models for Excel parser."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CellBlock:
    """A block of cell content from a sheet."""
    sheet_name: str
    start_row: int
    start_col: int
    end_row: int
    end_col: int
    data: list[list[str]] = field(default_factory=list)
    is_table: bool = False
    markdown: str = ""


@dataclass
class ExcelShape:
    """A shape object extracted from Excel OOXML drawing."""
    sheet_name: str
    shape_id: str
    name: str
    text: str
    geometry: Optional[str] = None
    from_row: Optional[int] = None
    from_col: Optional[int] = None
    to_row: Optional[int] = None
    to_col: Optional[int] = None
    from_row_off: int = 0
    from_col_off: int = 0
    to_row_off: int = 0
    to_col_off: int = 0
    fill_color: Optional[str] = None
    line_color: Optional[str] = None
    # Computed center position (EMU)
    center_x: float = 0.0
    center_y: float = 0.0
    # Absolute position from xfrm transform (EMU)
    xfrm_x: int = 0
    xfrm_y: int = 0
    xfrm_cx: int = 0  # width in EMU
    xfrm_cy: int = 0  # height in EMU

    @property
    def x(self) -> float:
        """Left edge X in EMU. Prefers xfrm, fallback to col-based."""
        if self.xfrm_x:
            return float(self.xfrm_x)
        return (self.from_col or 0) * 609600 + self.from_col_off

    @property
    def y(self) -> float:
        """Top edge Y in EMU. Prefers xfrm, fallback to row-based."""
        if self.xfrm_y:
            return float(self.xfrm_y)
        return (self.from_row or 0) * 190500 + self.from_row_off

    @property
    def width(self) -> float:
        """Width in EMU. Prefers xfrm_cx, fallback to col-based."""
        if self.xfrm_cx:
            return float(self.xfrm_cx)
        cols = (self.to_col or 0) - (self.from_col or 0)
        return cols * 609600 + (self.to_col_off - self.from_col_off) if cols > 0 else 0.0

    @property
    def height(self) -> float:
        """Height in EMU. Prefers xfrm_cy, fallback to row-based."""
        if self.xfrm_cy:
            return float(self.xfrm_cy)
        rows = (self.to_row or 0) - (self.from_row or 0)
        return rows * 190500 + (self.to_row_off - self.from_row_off) if rows > 0 else 0.0

    @property
    def mermaid_shape(self) -> str:
        """Determine Mermaid node shape based on geometry."""
        geo = (self.geometry or "").lower()
        txt = (self.text or "").lower()
        if "terminator" in geo:
            return "stadium"  # ([...])
        elif "decision" in geo or "diamond" in geo:
            return "diamond"  # {...}
        elif "document" in geo:
            return "doc"
        elif "data" in geo or "parallelogram" in geo:
            return "parallelogram"
        elif "predefinedprocess" in geo or "predefined" in geo:
            return "subroutine"  # [[...]]
        elif any(k in txt for k in ["判定", "確認", "場合", "分岐", "条件"]):
            return "diamond"
        else:
            return "rect"  # [...]


@dataclass
class ExcelConnector:
    """A connector object extracted from Excel OOXML drawing."""
    sheet_name: str
    connector_id: str
    name: str
    start_shape_id: Optional[str] = None
    end_shape_id: Optional[str] = None
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None
    # Positional data for position-based inference
    from_row: Optional[int] = None
    from_col: Optional[int] = None
    to_row: Optional[int] = None
    to_col: Optional[int] = None
    from_row_off: int = 0
    from_col_off: int = 0
    to_row_off: int = 0
    to_col_off: int = 0
    label: Optional[str] = None
    line_style: Optional[str] = None
    has_arrow: bool = True
    # Whether connection was inferred by position
    inferred: bool = False


@dataclass
class ExcelPicture:
    """A picture object extracted from Excel OOXML drawing."""
    sheet_name: str
    picture_id: str
    name: str
    media_path: str
    relationship_id: str
    from_row: Optional[int] = None
    from_col: Optional[int] = None
    output_path: str = ""


@dataclass
class ExcelGroup:
    """A group of shapes."""
    sheet_name: str
    group_id: str
    name: str
    child_shape_ids: list[str] = field(default_factory=list)
    child_connector_ids: list[str] = field(default_factory=list)


@dataclass
class SheetData:
    """All parsed data for one sheet."""
    name: str
    max_row: int = 0
    max_col: int = 0
    cell_blocks: list[CellBlock] = field(default_factory=list)
    shapes: list[ExcelShape] = field(default_factory=list)
    connectors: list[ExcelConnector] = field(default_factory=list)
    pictures: list[ExcelPicture] = field(default_factory=list)
    groups: list[ExcelGroup] = field(default_factory=list)
    has_drawing: bool = False
    merged_cells: list[str] = field(default_factory=list)

    @property
    def sheet_name(self) -> str:
        """Alias for backward compatibility."""
        return self.name

    @property
    def cells(self) -> list[CellBlock]:
        """Alias for backward compatibility."""
        return self.cell_blocks


@dataclass
class WorkbookData:
    """Complete parsed workbook data."""
    source_path: str
    sheets: list[SheetData] = field(default_factory=list)
