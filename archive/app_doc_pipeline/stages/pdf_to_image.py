"""Stage 3: PDF → PNG images with adaptive DPI + tile generation."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image

from ..config import PipelineConfig, config as _default_config
from ..models import SheetImages, SheetPDF
from ..utils.image_ops import generate_tiles, needs_tiling, resize_to_max, Image

logger = logging.getLogger(__name__)

# Reset PIL safety limit (Excel sheets can be very large)
Image.MAX_IMAGE_PIXELS = 500_000_000

# Sheets wider than this (mm) get reduced DPI to stay under pixel limits
_EXTREME_WIDTH_MM = 3000.0
_EXTREME_DPI = 36
_WIDE_DPI = 72    # intermediate wide sheets


def _choose_dpi(sheet_pdf: SheetPDF, cfg: PipelineConfig) -> int:
    """Pick a DPI that keeps the rendered image manageable."""
    pw_mm = sheet_pdf.sheet_info.page_width_pt / 2.8346  # pt → mm
    if pw_mm >= _EXTREME_WIDTH_MM:
        return _EXTREME_DPI
    if pw_mm >= cfg.pdf_wide_threshold_mm:
        return _WIDE_DPI
    return cfg.pdf_default_dpi


def render_pdf_to_image(
    sheet_pdf: SheetPDF,
    output_dir: str,
    cfg: Optional[PipelineConfig] = None,
) -> SheetImages:
    """Render the first page of sheet_pdf.pdf_path to PNG.

    Also generates tiles if the image is too large for the VLM API.
    """
    cfg = cfg or _default_config
    os.makedirs(output_dir, exist_ok=True)

    from pdf2image import convert_from_path  # type: ignore

    safe_name = f"sheet_{sheet_pdf.sheet_info.index:02d}"
    dpi = _choose_dpi(sheet_pdf, cfg)

    logger.info(
        "  Rendering %s at %d DPI…", Path(sheet_pdf.pdf_path).name, dpi
    )

    pages = convert_from_path(sheet_pdf.pdf_path, dpi=dpi, first_page=1, last_page=1)
    if not pages:
        raise RuntimeError(f"pdf2image returned no pages for {sheet_pdf.pdf_path}")

    img: Image.Image = pages[0]
    w, h = img.size

    # Save full-res PNG
    full_path = os.path.join(output_dir, f"{safe_name}.png")
    img.save(full_path, format="PNG")
    logger.info("    Full image: %dx%d px → %s", w, h, full_path)

    # VLM-ready copy (max 3000px on longest side for API input)
    vlm_img = resize_to_max(img, cfg.vlm_max_image_px)
    vlm_path = os.path.join(output_dir, f"{safe_name}_vlm.png")
    vlm_img.save(vlm_path, format="PNG")

    # Tile generation for large sheets
    tile_paths: list[str] = []
    if needs_tiling(img, max_dim=4000):
        tile_dir = os.path.join(output_dir, "tiles", safe_name)
        tile_paths = generate_tiles(
            img,
            tile_size=cfg.vlm_tile_size,
            overlap=cfg.vlm_tile_overlap,
            output_dir=tile_dir,
            prefix="tile",
        )
        logger.info("    Tiles: %d generated in %s", len(tile_paths), tile_dir)

    return SheetImages(
        sheet_info=sheet_pdf.sheet_info,
        full_image_path=full_path,
        tile_paths=tile_paths,
        vlm_ready_path=vlm_path,
        width_px=w,
        height_px=h,
        dpi_used=dpi,
    )


def render_all_sheets(
    sheet_pdfs: list[SheetPDF],
    output_dir: str,
    cfg: Optional[PipelineConfig] = None,
) -> list[SheetImages]:
    """Render all sheets in a workbook. Skips sheets with empty pdf_path."""
    cfg = cfg or _default_config
    results: list[SheetImages] = []

    for sp in sheet_pdfs:
        if not sp.pdf_path or not os.path.exists(sp.pdf_path):
            logger.warning("  Skipping sheet %d — no PDF", sp.sheet_info.index)
            continue
        try:
            si = render_pdf_to_image(sp, output_dir=output_dir, cfg=cfg)
            results.append(si)
        except Exception as e:
            logger.error("  Sheet %d render failed: %s", sp.sheet_info.index, e)

    return results
