"""Text extraction from PDF using PyMuPDF."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pymupdf

from flowchart_to_mermaid.graph.models import TextBlock, TextSource

logger = logging.getLogger(__name__)


class TextExtractor:
    """Extract text blocks from PDF pages using PyMuPDF."""

    def __init__(self, pdf_path: Path, zoom: int = 3):
        self.pdf_path = pdf_path
        self.zoom = zoom

    def extract_page(self, page_index: int) -> list[TextBlock]:
        """Extract text blocks from a specific PDF page.

        Returns TextBlocks with coordinates scaled to rendered image coordinates.
        """
        doc = pymupdf.open(str(self.pdf_path))
        page = doc[page_index]

        blocks = []
        # Use get_text("dict") for detailed text extraction
        page_dict = page.get_text("dict")

        block_idx = 0
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # text block type
                continue

            for line in block.get("lines", []):
                text_parts = []
                font_size = None
                for span in line.get("spans", []):
                    text_parts.append(span.get("text", ""))
                    if font_size is None:
                        font_size = span.get("size")

                text = "".join(text_parts).strip()
                if not text:
                    continue

                # Scale bbox to rendered image coordinates
                bbox = line.get("bbox", [0, 0, 0, 0])
                scaled_bbox = [
                    bbox[0] * self.zoom,
                    bbox[1] * self.zoom,
                    bbox[2] * self.zoom,
                    bbox[3] * self.zoom,
                ]

                block_idx += 1
                blocks.append(TextBlock(
                    id=f"txt_{block_idx:03d}",
                    text=text,
                    bbox=scaled_bbox,
                    confidence=1.0,
                    source=TextSource.PDF_TEXT,
                    font_size=font_size * self.zoom if font_size else None,
                ))

        doc.close()
        logger.info(f"Page {page_index}: extracted {len(blocks)} text blocks")
        return blocks

    def get_text_density(self, page_index: int) -> float:
        """Check text density to decide if OCR is needed.

        Returns ratio of text area to page area.
        """
        doc = pymupdf.open(str(self.pdf_path))
        page = doc[page_index]

        text = page.get_text("text")
        page_area = page.rect.width * page.rect.height

        # Rough estimate: each char covers ~100 sq units
        text_area = len(text.strip()) * 100
        density = text_area / page_area if page_area > 0 else 0

        doc.close()
        return min(density, 1.0)
