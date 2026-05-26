"""Image file loader."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from flowchart_to_mermaid.config import ConvertConfig

logger = logging.getLogger(__name__)


class ImageLoader:
    """Load and normalize image files (PNG, JPG, JPEG)."""

    SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

    def __init__(self, config: ConvertConfig):
        self.config = config

    def load(self) -> list[dict]:
        """Load image and save as normalized PNG.

        Returns list of dicts (single-element for images).
        """
        img_path = self.config.input_path
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {img_path}")

        suffix = img_path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image format: {suffix}")

        # Read and normalize
        img = cv2.imread(str(img_path))
        if img is None:
            raise ValueError(f"Failed to read image: {img_path}")

        h, w = img.shape[:2]

        # Save as standardized PNG
        out_path = self.config.pages_dir / "page_001.png"
        cv2.imwrite(str(out_path), img)

        page_info = {
            "page_index": 0,
            "width": w,
            "height": h,
            "image_path": str(out_path),
            "pdf_width": w,
            "pdf_height": h,
            "zoom": 1,
        }

        logger.info(f"Image loaded: {w}x{h} -> {out_path}")
        return [page_info]
