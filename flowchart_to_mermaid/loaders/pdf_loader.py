"""PDF document loader using PyMuPDF."""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from flowchart_to_mermaid.config import ConvertConfig

logger = logging.getLogger(__name__)


class PDFLoader:
    """Load and render PDF pages to high-resolution images."""

    def __init__(self, config: ConvertConfig):
        self.config = config

    def load(self) -> list[dict]:
        """Load PDF and render each page as a PNG image.

        Returns list of dicts with keys: page_index, width, height, image_path, pdf_page.
        """
        pdf_path = self.config.input_path
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = pymupdf.open(str(pdf_path))
        pages = []

        for i, page in enumerate(doc):
            zoom = self.config.render_zoom
            mat = pymupdf.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Save rendered page
            img_path = self.config.pages_dir / f"page_{i+1:03d}.png"
            pix.save(str(img_path))

            page_info = {
                "page_index": i,
                "width": pix.width,
                "height": pix.height,
                "image_path": str(img_path),
                "pdf_width": page.rect.width,
                "pdf_height": page.rect.height,
                "zoom": zoom,
            }
            pages.append(page_info)
            logger.info(f"Page {i+1}: {pix.width}x{pix.height} -> {img_path}")

        doc.close()
        return pages
