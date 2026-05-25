"""Shape detection using OpenCV contour analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from flowchart_to_mermaid.graph.models import Shape, ShapeType

logger = logging.getLogger(__name__)


class ShapeDetector:
    """Detect geometric shapes (rectangles, diamonds, rounded rects) in images."""

    def __init__(self, min_area: int = 800, max_area_ratio: float = 0.5):
        self.min_area = min_area
        self.max_area_ratio = max_area_ratio  # max fraction of page area

    def detect(self, image_path: Path) -> list[Shape]:
        """Detect shapes in an image.

        Returns list of Shape objects with type classification.
        """
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Cannot read image: {image_path}")
            return []

        h, w = img.shape[:2]
        page_area = h * w
        max_area = page_area * self.max_area_ratio

        # Convert to grayscale and apply edge detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply bilateral filter to reduce noise while keeping edges
        filtered = cv2.bilateralFilter(gray, 9, 75, 75)

        # Adaptive threshold for better shape detection
        thresh = cv2.adaptiveThreshold(
            filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )

        # Also try Canny edge detection
        edges = cv2.Canny(filtered, 50, 150)

        # Combine both approaches
        combined = cv2.bitwise_or(thresh, edges)

        # Dilate slightly to close gaps
        kernel = np.ones((2, 2), np.uint8)
        combined = cv2.dilate(combined, kernel, iterations=1)

        # Find contours
        contours, hierarchy = cv2.findContours(
            combined, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )

        shapes = []
        shape_idx = 0

        for i, contour in enumerate(contours):
            area = cv2.contourArea(contour)
            if area < self.min_area or area > max_area:
                continue

            # Get bounding rect
            x, y, cw, ch = cv2.boundingRect(contour)

            # Approximate the contour
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)

            # Classify shape
            shape_type = self._classify_shape(approx, contour, cw, ch)

            # Check if dashed (by examining edge continuity)
            is_dashed = self._check_dashed(gray, contour)

            shape_idx += 1
            shapes.append(Shape(
                id=f"shape_{shape_idx:03d}",
                type=shape_type,
                bbox=[float(x), float(y), float(x + cw), float(y + ch)],
                confidence=0.6,
                is_dashed=is_dashed,
            ))

        # Deduplicate overlapping shapes
        shapes = self._deduplicate(shapes)
        logger.info(f"Detected {len(shapes)} shapes in {image_path}")
        return shapes

    def _classify_shape(
        self, approx: np.ndarray, contour: np.ndarray,
        width: int, height: int
    ) -> ShapeType:
        """Classify shape based on polygon approximation."""
        n_vertices = len(approx)

        # Very few vertices and roughly square aspect ratio -> diamond
        if n_vertices == 4:
            # Check if it's a diamond (rotated square)
            aspect = width / max(height, 1)
            # Check angles - diamonds have vertices at top/bottom/left/right
            center_x = np.mean(approx[:, 0, 0])
            center_y = np.mean(approx[:, 0, 1])

            # Check if vertices are near the midpoints of edges (diamond pattern)
            top_bottom_aligned = False
            for pt in approx:
                px, py = pt[0]
                if abs(px - center_x) < width * 0.2:
                    if abs(py - center_y) > height * 0.3:
                        top_bottom_aligned = True
                        break

            if top_bottom_aligned and 0.7 < aspect < 1.8:
                return ShapeType.DECISION

            # Regular rectangle
            return ShapeType.PROCESS

        # Many vertices -> possibly rounded rect or ellipse
        if n_vertices >= 6:
            # Check circularity
            perimeter = cv2.arcLength(contour, True)
            area = cv2.contourArea(contour)
            if perimeter > 0:
                circularity = 4 * np.pi * area / (perimeter * perimeter)
                if circularity > 0.7:
                    return ShapeType.TERMINATOR

            # Check if it's a rounded rectangle
            rect_area = width * height
            if area > 0 and rect_area > 0:
                fill_ratio = area / rect_area
                if fill_ratio > 0.85:
                    return ShapeType.PROCESS

        return ShapeType.UNKNOWN

    def _check_dashed(self, gray: np.ndarray, contour: np.ndarray) -> bool:
        """Check if a contour appears to be dashed."""
        # Create a mask for the contour edge
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, 2)

        # Sample pixels along the contour
        edge_pixels = gray[mask > 0]
        if len(edge_pixels) < 20:
            return False

        # Dashed lines have alternating dark/light patterns
        # Check variance of edge pixels
        std = np.std(edge_pixels.astype(float))
        return std > 60

    def _deduplicate(self, shapes: list[Shape]) -> list[Shape]:
        """Remove overlapping shapes, keeping the one with higher confidence."""
        if not shapes:
            return shapes

        result = []
        used = set()

        for i, s1 in enumerate(shapes):
            if i in used:
                continue
            best = s1
            for j, s2 in enumerate(shapes[i+1:], start=i+1):
                if j in used:
                    continue
                if self._iou(s1.bbox, s2.bbox) > 0.5:
                    used.add(j)
                    if s2.confidence > best.confidence:
                        best = s2
            result.append(best)

        return result

    @staticmethod
    def _iou(bbox1: list[float], bbox2: list[float]) -> float:
        """Calculate Intersection over Union of two bboxes."""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def generate_overlay(self, image_path: Path, shapes: list[Shape], output_path: Path) -> None:
        """Generate debug overlay showing detected shapes."""
        img = cv2.imread(str(image_path))
        if img is None:
            return

        color_map = {
            ShapeType.PROCESS: (0, 255, 0),      # Green
            ShapeType.DECISION: (0, 0, 255),     # Red
            ShapeType.TERMINATOR: (255, 0, 0),   # Blue
            ShapeType.ANNOTATION: (255, 255, 0), # Cyan
            ShapeType.GROUP: (128, 0, 128),      # Purple
            ShapeType.LINE: (128, 128, 128),     # Gray
            ShapeType.UNKNOWN: (0, 128, 255),    # Orange
        }

        for shape in shapes:
            x1, y1, x2, y2 = [int(v) for v in shape.bbox]
            color = color_map.get(shape.type, (255, 255, 255))
            thickness = 1 if shape.is_dashed else 2
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)

            # Label
            label = f"{shape.type.value}({shape.confidence:.1f})"
            cv2.putText(img, label, (x1, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        cv2.imwrite(str(output_path), img)
        logger.info(f"Shape overlay saved: {output_path}")
