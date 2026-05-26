"""Stage 2: Excel → per-sheet PDF via LibreOffice UNO.

Must be called with /usr/bin/python3 — UNO bindings only work with system Python.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from ..config import PipelineConfig, config as _default_config
from ..models import SheetInfo, SheetPDF
from ..utils.libreoffice import connect, open_document

logger = logging.getLogger(__name__)


# ── Paper sizing ──────────────────────────────────────────────────────────────

def _get_paper_config(max_col: int, max_row: int) -> tuple[int, int, bool, int, int]:
    """Return (width_mm, height_mm, landscape, scale_x, scale_y)."""
    if max_col <= 20 and max_row <= 50:
        return 1190, 841, True, 1, 1   # A3 landscape, fit both
    elif max_col <= 20:
        return 594, 841, False, 1, 0   # A1 portrait, fit width only
    elif max_col <= 50:
        return 841, 594, True, 1, 0    # A1 landscape, fit width
    elif max_col <= 100:
        return 1189, 841, True, 1, 0   # A0 landscape, fit width
    else:
        return 3000, 2000, True, 1, 0  # Very wide custom, fit width


# ── Per-sheet export ──────────────────────────────────────────────────────────

def _export_sheet(doc, sheet_idx: int, output_path: str, max_col: int, max_row: int) -> Optional[dict]:
    """Export a single sheet to PDF. Returns metadata dict or None on failure."""
    import uno
    from com.sun.star.beans import PropertyValue

    sheets = doc.getSheets()
    sheet = sheets.getByIndex(sheet_idx)
    controller = doc.getCurrentController()
    controller.setActiveSheet(sheet)

    pw_mm, ph_mm, landscape, stx, sty = _get_paper_config(max_col, max_row)

    page_style_name = sheet.getPropertyValue("PageStyle")
    page_styles = doc.getStyleFamilies().getByName("PageStyles")
    ps = page_styles.getByName(page_style_name)

    try:
        ps.setPropertyValue("IsLandscape", landscape)
        ps.setPropertyValue("Width", pw_mm * 100)   # hundredths of mm
        ps.setPropertyValue("Height", ph_mm * 100)
        ps.setPropertyValue("TopMargin", 500)
        ps.setPropertyValue("BottomMargin", 500)
        ps.setPropertyValue("LeftMargin", 500)
        ps.setPropertyValue("RightMargin", 500)
        ps.setPropertyValue("ScaleToPages", 0)
        ps.setPropertyValue("ScaleToPagesX", stx)
        ps.setPropertyValue("ScaleToPagesY", sty)
    except Exception as e:
        logger.warning("    Page style warning for sheet %d: %s", sheet_idx, e)

    output_url = uno.systemPathToFileUrl(output_path)
    filter_data = (
        PropertyValue(Name="Selection", Value=sheet),
        PropertyValue(Name="IsSkipEmptyPages", Value=False),
        PropertyValue(Name="MaxImageResolution", Value=300),
    )
    export_props = (
        PropertyValue(Name="FilterName", Value="calc_pdf_Export"),
        PropertyValue(
            Name="FilterData",
            Value=uno.Any("[]com.sun.star.beans.PropertyValue", filter_data),
        ),
        PropertyValue(Name="Overwrite", Value=True),
    )

    doc.storeToURL(output_url, export_props)

    if not os.path.exists(output_path):
        return None

    # Count pages via pdfinfo
    pages = 1
    try:
        r = subprocess.run(
            ["pdfinfo", output_path],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.splitlines():
            if "Pages:" in line:
                pages = int(line.split(":")[1].strip())
    except Exception:
        pass

    # Get page size in points from pdfinfo
    pw_pt, ph_pt = float(pw_mm * 2.8346), float(ph_mm * 2.8346)  # mm → pt approx
    try:
        for line in r.stdout.splitlines():
            if "Page size:" in line:
                parts = line.split(":")[1].strip().split()
                if len(parts) >= 3:
                    pw_pt = float(parts[0])
                    ph_pt = float(parts[2])
    except Exception:
        pass

    return {
        "path": output_path,
        "pages": pages,
        "paper": f"{pw_mm}x{ph_mm}mm",
        "landscape": landscape,
        "scale": f"X={stx},Y={sty}",
        "page_width_pt": pw_pt,
        "page_height_pt": ph_pt,
    }


# ── Sheet metadata ─────────────────────────────────────────────────────────────

def _has_shapes(sheet) -> bool:
    try:
        draw_page = sheet.getDrawPage()
        return draw_page.getCount() > 0
    except Exception:
        return False


def _get_sheet_info(doc, sheet_idx: int) -> tuple[str, int, int, bool]:
    """Return (name, max_col, max_row, has_shapes)."""
    sheets = doc.getSheets()
    sheet = sheets.getByIndex(sheet_idx)
    name = sheet.getName()
    cursor = sheet.createCursor()
    cursor.gotoStartOfUsedArea(False)
    cursor.gotoEndOfUsedArea(True)
    addr = cursor.getRangeAddress()
    max_col = addr.EndColumn + 1
    max_row = addr.EndRow + 1
    return name, max_col, max_row, _has_shapes(sheet)


# ── Public API ────────────────────────────────────────────────────────────────

def convert_excel_to_pdfs(
    xlsx_path: str,
    output_dir: str,
    cfg: Optional[PipelineConfig] = None,
) -> list[SheetPDF]:
    """Convert every sheet in xlsx_path to a separate PDF in output_dir.

    Returns a list of SheetPDF objects and writes export_manifest.json.
    Raises RuntimeError if LibreOffice is unreachable.
    """
    cfg = cfg or _default_config
    os.makedirs(output_dir, exist_ok=True)

    desktop = connect(host=cfg.libreoffice_host, port=cfg.libreoffice_port)
    doc = open_document(desktop, os.path.abspath(xlsx_path))

    sheets = doc.getSheets()
    n_sheets = sheets.getCount()
    logger.info("Workbook has %d sheets: %s", n_sheets, xlsx_path)

    results: list[SheetPDF] = []
    raw_results: list[dict] = []

    for i in range(n_sheets):
        name, max_col, max_row, has_shapes = _get_sheet_info(doc, i)
        safe_name = f"sheet_{i + 1:02d}"
        pdf_path = os.path.join(output_dir, f"{safe_name}.pdf")

        logger.info("  [%02d/%d] %s (%dc x %dr)…", i + 1, n_sheets, name, max_col, max_row)

        meta = _export_sheet(doc, i, pdf_path, max_col, max_row)

        sheet_info = SheetInfo(
            index=i + 1,
            name=name,
            rows=max_row,
            cols=max_col,
            has_shapes=has_shapes,
        )

        if meta:
            sheet_info = sheet_info.model_copy(
                update={
                    "page_width_pt": meta.get("page_width_pt", 0.0),
                    "page_height_pt": meta.get("page_height_pt", 0.0),
                }
            )
            sp = SheetPDF(
                sheet_info=sheet_info,
                pdf_path=pdf_path,
                page_size=(meta["page_width_pt"], meta["page_height_pt"]),
                pages=meta["pages"],
                paper_label=meta["paper"],
            )
            logger.info("    → OK (%d pg, %s)", meta["pages"], meta["paper"])
        else:
            sp = SheetPDF(sheet_info=sheet_info, pdf_path="", pages=0)
            logger.warning("    → FAILED")

        results.append(sp)
        raw_results.append({
            "index": i + 1,
            "name": name,
            "safe_name": safe_name,
            "cols": max_col,
            "rows": max_row,
            **(meta or {"status": "failed"}),
        })

    doc.close(True)

    manifest_path = os.path.join(output_dir, "export_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(raw_results, f, indent=2, ensure_ascii=False)

    ok = sum(1 for r in results if r.pdf_path)
    logger.info("Exported %d/%d sheets → %s", ok, n_sheets, output_dir)
    return results
