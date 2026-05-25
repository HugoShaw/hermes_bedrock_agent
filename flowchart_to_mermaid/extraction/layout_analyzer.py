"""Layout analysis for determining flow direction."""

from __future__ import annotations

import logging
from pathlib import Path

from flowchart_to_mermaid.graph.models import TextBlock

logger = logging.getLogger(__name__)


class LayoutAnalyzer:
    """Analyze page layout to determine flow direction (TD vs LR)."""

    def analyze_direction(
        self, page_width: int, page_height: int, text_blocks: list[TextBlock]
    ) -> str:
        """Determine primary flow direction based on page aspect ratio and text layout.

        Returns 'TD' (top-down) or 'LR' (left-right).
        """
        aspect_ratio = page_width / max(page_height, 1)

        # Wide pages are typically LR
        if aspect_ratio > 1.5:
            return "LR"
        # Tall pages are typically TD
        elif aspect_ratio < 0.8:
            return "TD"

        # Ambiguous aspect ratio - analyze text distribution
        if not text_blocks:
            return "TD"  # Default

        # Check if text flows more horizontally or vertically
        x_positions = [tb.bbox[0] for tb in text_blocks]
        y_positions = [tb.bbox[1] for tb in text_blocks]

        x_spread = max(x_positions) - min(x_positions) if x_positions else 0
        y_spread = max(y_positions) - min(y_positions) if y_positions else 0

        if x_spread > y_spread * 1.3:
            return "LR"
        else:
            return "TD"
