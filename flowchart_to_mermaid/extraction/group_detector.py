"""Group/subgraph detection (dashed boxes, labeled regions)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from flowchart_to_mermaid.graph.models import FlowGroup, TextBlock

logger = logging.getLogger(__name__)


class GroupDetector:
    """Detect grouping boxes (dashed/solid large rectangles that contain nodes)."""

    def __init__(self, min_area_ratio: float = 0.01, max_area_ratio: float = 0.7):
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio

    def detect(
        self, image_path: Path, text_blocks: list[TextBlock]
    ) -> list[FlowGroup]:
        """Detect large grouping rectangles.

        Uses contour detection to find large boxes, then matches them
        with text blocks that contain group labels like '機能NoX：...'
        """
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Cannot read image: {image_path}")
            return []

        h, w = img.shape[:2]
        page_area = h * w
        min_area = page_area * self.min_area_ratio
        max_area = page_area * self.max_area_ratio

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Look for large rectangular contours
        # Use morphological operations to enhance boxes
        edges = cv2.Canny(gray, 30, 100)

        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(
            dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        groups = []
        group_idx = 0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue

            x, y, cw, ch = cv2.boundingRect(contour)

            # Must be reasonably rectangular
            rect_area = cw * ch
            if rect_area > 0 and area / rect_area < 0.5:
                continue

            # Must be larger than typical node boxes
            if cw < 150 or ch < 100:
                continue

            # Find matching label text
            label = self._find_group_label(
                [x, y, x + cw, y + ch], text_blocks
            )

            group_idx += 1
            groups.append(FlowGroup(
                id=f"group_{group_idx:03d}",
                label=label or f"Group {group_idx}",
                bbox=[float(x), float(y), float(x + cw), float(y + ch)],
                confidence=0.6 if label else 0.4,
            ))

        # Deduplicate overlapping groups
        groups = self._deduplicate_groups(groups)
        logger.info(f"Detected {len(groups)} groups in {image_path}")
        return groups

    def _find_group_label(
        self, bbox: list[float], text_blocks: list[TextBlock]
    ) -> Optional[str]:
        """Find a text block that could be this group's label.

        Looks for '機能No...' text near the top of the group bbox.
        """
        x1, y1, x2, y2 = bbox

        for tb in text_blocks:
            # Check if text is near the top of the group
            tx1, ty1, tx2, ty2 = tb.bbox
            # Text should be within or near the top edge of the group
            if tx1 >= x1 - 20 and tx2 <= x2 + 20:
                if abs(ty1 - y1) < 50:  # Near top edge
                    if "機能" in tb.text or "No" in tb.text:
                        return tb.text

        return None

    def _deduplicate_groups(self, groups: list[FlowGroup]) -> list[FlowGroup]:
        """Remove highly overlapping groups."""
        if len(groups) <= 1:
            return groups

        result = []
        used = set()

        # Sort by area (larger first)
        sorted_groups = sorted(
            enumerate(groups),
            key=lambda x: (x[1].bbox[2] - x[1].bbox[0]) * (x[1].bbox[3] - x[1].bbox[1]),
            reverse=True
        )

        for i, g1 in sorted_groups:
            if i in used:
                continue
            for j, g2 in sorted_groups:
                if j <= i or j in used:
                    continue
                if self._overlap_ratio(g1.bbox, g2.bbox) > 0.7:
                    used.add(j)
            result.append(g1)

        return result

    @staticmethod
    def _overlap_ratio(bbox1: list[float], bbox2: list[float]) -> float:
        """Calculate overlap ratio (intersection / smaller area)."""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        smaller = min(area1, area2)

        return intersection / smaller if smaller > 0 else 0.0

    def generate_overlay(
        self, image_path: Path, groups: list[FlowGroup], output_path: Path
    ) -> None:
        """Generate debug overlay showing detected groups."""
        img = cv2.imread(str(image_path))
        if img is None:
            return

        for group in groups:
            x1, y1, x2, y2 = [int(v) for v in group.bbox]
            cv2.rectangle(img, (x1, y1), (x2, y2), (128, 0, 128), 2)
            cv2.putText(img, group.label[:30], (x1 + 5, y1 + 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 0, 128), 1)

        cv2.imwrite(str(output_path), img)
        logger.info(f"Group overlay saved: {output_path}")
