"""Debug renderer: generates overlay images for inspection."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from flowchart_to_mermaid.graph.models import FlowNode, FlowEdge, FlowGroup, TextBlock

logger = logging.getLogger(__name__)


class DebugRenderer:
    """Generate debug overlay images for visual inspection."""

    def render_nodes_overlay(
        self, image_path: Path, nodes: list[FlowNode], output_path: Path
    ) -> None:
        """Render node bounding boxes and labels on the image."""
        img = cv2.imread(str(image_path))
        if img is None:
            return

        for node in nodes:
            if not node.bbox:
                continue
            x1, y1, x2, y2 = [int(v) for v in node.bbox]

            # Color by type
            colors = {
                "terminator": (180, 0, 180),
                "decision": (0, 0, 255),
                "api": (255, 128, 0),
                "file": (128, 128, 128),
                "loop": (0, 180, 0),
                "exception": (0, 0, 200),
                "process": (0, 200, 0),
                "unknown": (100, 100, 100),
            }
            color = colors.get(node.type.value, (0, 200, 0))
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

            # Node ID label
            cv2.putText(img, f"{node.id}:{node.type.value}",
                       (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

        cv2.imwrite(str(output_path), img)
        logger.info(f"Nodes overlay: {output_path}")

    def render_edges_overlay(
        self, image_path: Path, nodes: list[FlowNode], edges: list[FlowEdge],
        output_path: Path
    ) -> None:
        """Render edge connections between nodes."""
        img = cv2.imread(str(image_path))
        if img is None:
            return

        # Build node center map
        node_centers = {}
        for node in nodes:
            if node.bbox:
                cx = int((node.bbox[0] + node.bbox[2]) / 2)
                cy = int((node.bbox[1] + node.bbox[3]) / 2)
                node_centers[node.id] = (cx, cy)

        for edge in edges:
            if edge.source in node_centers and edge.target in node_centers:
                start = node_centers[edge.source]
                end = node_centers[edge.target]

                color = (0, 255, 255) if edge.inferred else (255, 0, 0)
                thickness = 1 if edge.uncertain else 2
                cv2.arrowedLine(img, start, end, color, thickness, tipLength=0.02)

        cv2.imwrite(str(output_path), img)
        logger.info(f"Edges overlay: {output_path}")
