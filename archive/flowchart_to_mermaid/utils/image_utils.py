"""Image utilities for cropping and processing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class ImageCropper:
    """Generate multiple crops of an image for review and analysis."""

    def generate_crops(self, image_path: Path, output_dir: Path) -> list[dict]:
        """Generate standard set of crops from an image.

        Returns list of dicts with keys: name, path, bbox.
        """
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Cannot read image: {image_path}")
            return []

        h, w = img.shape[:2]
        output_dir.mkdir(parents=True, exist_ok=True)

        page_name = Path(image_path).stem
        crops = []

        # Full image
        full_path = output_dir / f"{page_name}_full.png"
        cv2.imwrite(str(full_path), img)
        crops.append({"name": "full", "path": str(full_path), "bbox": [0, 0, w, h]})

        # Content bbox (non-white region)
        content_bbox = self._find_content_bbox(img)
        if content_bbox:
            cx1, cy1, cx2, cy2 = content_bbox
            content_img = img[cy1:cy2, cx1:cx2]
            content_path = output_dir / f"{page_name}_content_bbox.png"
            cv2.imwrite(str(content_path), content_img)
            crops.append({
                "name": "content_bbox",
                "path": str(content_path),
                "bbox": content_bbox,
            })
        else:
            content_bbox = [0, 0, w, h]

        # Generate grid crops from content area
        cx1, cy1, cx2, cy2 = content_bbox
        cw = cx2 - cx1
        ch = cy2 - cy1

        # Define crop regions
        regions = {
            "top_left": (cx1, cy1, cx1 + cw // 3, cy1 + ch // 2),
            "left": (cx1, cy1 + ch // 4, cx1 + cw // 3, cy1 + 3 * ch // 4),
            "mid_left": (cx1 + cw // 6, cy1, cx1 + cw // 2, cy1 + ch),
            "mid_center": (cx1 + cw // 4, cy1, cx1 + 3 * cw // 4, cy1 + ch),
            "center_right": (cx1 + cw // 2, cy1, cx1 + 5 * cw // 6, cy1 + ch),
            "right": (cx1 + 2 * cw // 3, cy1, cx2, cy1 + ch),
            "bottom_left": (cx1, cy1 + ch // 2, cx1 + cw // 3, cy2),
            "bottom": (cx1, cy1 + 2 * ch // 3, cx2, cy2),
        }

        for name, (rx1, ry1, rx2, ry2) in regions.items():
            rx1, ry1 = max(0, int(rx1)), max(0, int(ry1))
            rx2, ry2 = min(w, int(rx2)), min(h, int(ry2))

            if rx2 <= rx1 or ry2 <= ry1:
                continue

            crop_img = img[ry1:ry2, rx1:rx2]
            crop_path = output_dir / f"{page_name}_{name}.png"
            cv2.imwrite(str(crop_path), crop_img)
            crops.append({
                "name": name,
                "path": str(crop_path),
                "bbox": [rx1, ry1, rx2, ry2],
            })

        logger.info(f"Generated {len(crops)} crops from {image_path}")
        return crops

    def _find_content_bbox(self, img: np.ndarray) -> Optional[list[int]]:
        """Find bounding box of non-white content."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Threshold to find non-white pixels
        _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)

        # Find bounding rect of all non-white pixels
        coords = cv2.findNonZero(thresh)
        if coords is None:
            return None

        x, y, w, h = cv2.boundingRect(coords)

        # Add padding
        pad = 20
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(img.shape[1], x + w + pad)
        y2 = min(img.shape[0], y + h + pad)

        return [x1, y1, x2, y2]


def generate_text_overlay(
    image_path: Path, text_blocks: list, output_path: Path
) -> None:
    """Generate debug overlay showing extracted text blocks."""
    img = cv2.imread(str(image_path))
    if img is None:
        return

    for tb in text_blocks:
        x1, y1, x2, y2 = [int(v) for v in tb.bbox]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 1)
        # Draw text (limited to ASCII for OpenCV)
        label = tb.text[:20]
        cv2.putText(img, f"[{tb.id}]", (x1, y1 - 3),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 200, 0), 1)

    cv2.imwrite(str(output_path), img)
    logger.info(f"Text overlay saved: {output_path}")
