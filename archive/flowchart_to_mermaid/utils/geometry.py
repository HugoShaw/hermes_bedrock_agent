"""Geometry utilities for bbox calculations."""

from __future__ import annotations

from typing import Optional


def bbox_center(bbox: list[float]) -> tuple[float, float]:
    """Get center point of a bbox [x1, y1, x2, y2]."""
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def bbox_area(bbox: list[float]) -> float:
    """Calculate area of a bbox."""
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def bbox_contains(outer: list[float], inner: list[float]) -> bool:
    """Check if outer bbox fully contains inner bbox."""
    return (
        outer[0] <= inner[0] and outer[1] <= inner[1]
        and outer[2] >= inner[2] and outer[3] >= inner[3]
    )


def bbox_overlap(bbox1: list[float], bbox2: list[float]) -> float:
    """Calculate overlap area between two bboxes."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def bbox_distance(bbox1: list[float], bbox2: list[float]) -> float:
    """Calculate minimum distance between two bboxes."""
    # Center-to-center distance
    cx1, cy1 = bbox_center(bbox1)
    cx2, cy2 = bbox_center(bbox2)
    return ((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2) ** 0.5
