"""Stage 3: PDF → PNG images with adaptive DPI + tile generation."""

from __future__ import annotations

import logging
import os
from typing import Optional

from PIL import Image

from ..config import Config, config as _default_config
from .image_utils import generate_tiles, needs_tiling, resize_to_max
from .models import SheetImages, SheetPDF

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 500_000_000

_EXTREME_WIDTH_MM = 3000.0
_EXTREME_DPI = 36
_WIDE_DPI = 72


def _choose_dpi(sheet_pdf: SheetPDF, cfg: Config) -> int:
    pw_mm = sheet_pdf.sheet_info.page_width_pt / 2.8346
    if pw_mm >= _EXTREME_WIDTH_MM:
        return _EXTREME_DPI
    if pw_mm >= cfg.pdf_wide_threshold_mm:
        return _WIDE_DPI
    return cfg.pdf_default_dpi


def _determine_rendering_strategy(sheet_pdf: SheetPDF) -> str:
    cols = sheet_pdf.sheet_info.cols
    rows = sheet_pdf.sheet_info.rows
    if cols <= 8 and rows <= 15:
        return "small_sheet"
    if cols <= 15 and rows <= 30:
        return "small_sheet"
    if sheet_pdf.pages > 1:
        return "multi_page"
    return "single_page"


def render_pdf_to_image(
    sheet_pdf: SheetPDF,
    output_dir: str,
    cfg: Optional[Config] = None,
) -> SheetImages:
    """Render sheet_pdf to PNG(s). Supports multi-page PDFs and small-sheet optimization."""
    cfg = cfg or _default_config
    os.makedirs(output_dir, exist_ok=True)

    from pdf2image import convert_from_path  # type: ignore

    safe_name = f"sheet_{sheet_pdf.sheet_info.index:02d}"
    dpi = _choose_dpi(sheet_pdf, cfg)
    strategy = _determine_rendering_strategy(sheet_pdf)
    page_count = sheet_pdf.pages

    logger.info("  Rendering %s at %d DPI (strategy=%s, pages=%d)…",
                safe_name, dpi, strategy, page_count)

    all_page_imgs = convert_from_path(sheet_pdf.pdf_path, dpi=dpi)
    if not all_page_imgs:
        raise RuntimeError(f"pdf2image returned no pages for {sheet_pdf.pdf_path}")

    page_count = len(all_page_imgs)
    img: Image.Image = all_page_imgs[0]
    w, h = img.size

    full_path = os.path.join(output_dir, f"{safe_name}.png")
    img.save(full_path, format="PNG")
    logger.info("    Page 1 image: %dx%d px → %s", w, h, full_path)

    page_image_paths: list[str] = [full_path]
    for pg_idx in range(1, page_count):
        pg_img = all_page_imgs[pg_idx]
        pg_path = os.path.join(output_dir, f"{safe_name}_p{pg_idx + 1:02d}.png")
        pg_img.save(pg_path, format="PNG")
        page_image_paths.append(pg_path)
        logger.info("    Page %d image: %dx%d px → %s",
                    pg_idx + 1, pg_img.size[0], pg_img.size[1], pg_path)

    vlm_img = resize_to_max(img, cfg.vlm_max_image_px)
    vlm_path = os.path.join(output_dir, f"{safe_name}_vlm.png")
    vlm_img.save(vlm_path, format="PNG")

    tile_paths: list[str] = []
    # Tile when image is very large OR when sheet has shapes on large paper
    # (A0/A1 flowcharts need tiling even at 3000-4000px because text is dense)
    should_tile = needs_tiling(img, max_dim=4000)
    if not should_tile and sheet_pdf.sheet_info.has_shapes:
        # Force tiling for shape-heavy sheets on large paper (A1+: width > 1500pt ≈ 530mm)
        pw_pt = sheet_pdf.sheet_info.page_width_pt
        ph_pt = sheet_pdf.sheet_info.page_height_pt
        max_pt = max(pw_pt, ph_pt)
        if max_pt > 1500:  # A1 and larger
            should_tile = True
            logger.info("    Forcing tiling: has_shapes=True, paper=%.0fx%.0f pt (large format)",
                        pw_pt, ph_pt)

    if page_count == 1 and should_tile:
        tile_dir = os.path.join(output_dir, "tiles", safe_name)
        tile_paths = generate_tiles(
            img,
            tile_size=cfg.vlm_tile_size,
            overlap=cfg.vlm_tile_overlap,
            output_dir=tile_dir,
            prefix="tile",
        )
        logger.info("    Tiles: %d generated", len(tile_paths))

    return SheetImages(
        sheet_info=sheet_pdf.sheet_info,
        full_image_path=full_path,
        page_image_paths=page_image_paths,
        tile_paths=tile_paths,
        vlm_ready_path=vlm_path,
        width_px=w,
        height_px=h,
        dpi_used=dpi,
        page_count=page_count,
        rendering_strategy=strategy,
    )


def render_all_sheets(
    sheet_pdfs: list[SheetPDF],
    output_dir: str,
    cfg: Optional[Config] = None,
) -> list[SheetImages]:
    cfg = cfg or _default_config
    results: list[SheetImages] = []
    for sp in sheet_pdfs:
        if not sp.pdf_path or not os.path.exists(sp.pdf_path):
            logger.warning("  Skipping sheet %d — no PDF", sp.sheet_info.index)
            continue
        try:
            results.append(render_pdf_to_image(sp, output_dir=output_dir, cfg=cfg))
        except Exception as e:
            logger.error("  Sheet %d render failed: %s", sp.sheet_info.index, e)
    return results
