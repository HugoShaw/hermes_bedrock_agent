"""OCR extraction (optional, uses pytesseract if available)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from flowchart_to_mermaid.graph.models import TextBlock, TextSource

logger = logging.getLogger(__name__)

# Check if pytesseract is available
_TESSERACT_AVAILABLE = False
try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    pass


def is_ocr_available() -> bool:
    """Check if OCR is available."""
    return _TESSERACT_AVAILABLE


class OCRExtractor:
    """Extract text from images using OCR (pytesseract)."""

    def __init__(self, lang: str = "jpn+eng"):
        self.lang = lang
        if not _TESSERACT_AVAILABLE:
            logger.warning("pytesseract not installed. OCR will be unavailable.")

    def extract(self, image_path: Path) -> list[TextBlock]:
        """Extract text blocks from an image using OCR.

        Returns empty list if pytesseract is not available.
        """
        if not _TESSERACT_AVAILABLE:
            logger.warning("OCR skipped: pytesseract not installed")
            return []

        import cv2
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Cannot read image: {image_path}")
            return []

        try:
            data = pytesseract.image_to_data(
                img, lang=self.lang, output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return []

        blocks = []
        n = len(data["text"])
        block_idx = 0

        for i in range(n):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])

            if not text or conf < 30:  # Skip low-confidence or empty
                continue

            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]

            block_idx += 1
            blocks.append(TextBlock(
                id=f"ocr_{block_idx:03d}",
                text=text,
                bbox=[float(x), float(y), float(x + w), float(y + h)],
                confidence=conf / 100.0,
                source=TextSource.OCR,
            ))

        logger.info(f"OCR extracted {len(blocks)} text blocks from {image_path}")
        return blocks
