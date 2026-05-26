"""Arrow and line detection using OpenCV."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from flowchart_to_mermaid.graph.models import Shape, ShapeType

logger = logging.getLogger(__name__)


class ArrowDetector:
    """Detect arrows and connections between shapes."""

    def __init__(self, min_line_length: int = 30, max_line_gap: int = 15):
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap

    def detect(self, image_path: Path) -> list[dict]:
        """Detect line segments that could be arrows.

        Returns list of dicts with keys: start, end, has_arrowhead, angle.
        """
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Cannot read image: {image_path}")
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Edge detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        # Hough Line Transform (probabilistic)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=50,
            minLineLength=self.min_line_length,
            maxLineGap=self.max_line_gap,
        )

        arrows = []
        if lines is None:
            logger.info("No lines detected")
            return arrows

        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))

            # Filter: keep primarily horizontal or vertical lines
            is_horizontal = abs(angle) < 20 or abs(angle) > 160
            is_vertical = 70 < abs(angle) < 110

            if not (is_horizontal or is_vertical):
                continue

            arrows.append({
                "start": [int(x1), int(y1)],
                "end": [int(x2), int(y2)],
                "length": float(length),
                "angle": float(angle),
                "is_horizontal": is_horizontal,
                "is_vertical": is_vertical,
            })

        logger.info(f"Detected {len(arrows)} line segments in {image_path}")
        return arrows

    def generate_overlay(self, image_path: Path, arrows: list[dict], output_path: Path) -> None:
        """Generate debug overlay showing detected arrows."""
        img = cv2.imread(str(image_path))
        if img is None:
            return

        for arrow in arrows:
            start = tuple(arrow["start"])
            end = tuple(arrow["end"])
            color = (0, 255, 255) if arrow.get("is_vertical") else (255, 0, 255)
            cv2.line(img, start, end, color, 2)
            cv2.circle(img, end, 4, (0, 0, 255), -1)  # Red dot at endpoint

        cv2.imwrite(str(output_path), img)
        logger.info(f"Arrow overlay saved: {output_path}")
