"""Simple sheet classifier - categorizes sheets by content type.

Categories:
- text_table: cells only, no visual objects
- visual: many shapes/connectors, few cells
- mixed: both cells and visual objects
- empty: no content
"""
import logging
from .models import SheetData

logger = logging.getLogger(__name__)


def classify_sheets(sheets: list[SheetData]) -> list[dict]:
    """Classify each sheet and return classification metadata.

    Returns list of dicts with:
        sheet_name, classification, cell_count, shape_count,
        connector_count, picture_count, strategy
    """
    results = []
    for sheet in sheets:
        cell_count = sum(
            sum(1 for c in row if c)
            for block in sheet.cell_blocks
            for row in block.data
        )
        shape_count = len(sheet.shapes)
        connector_count = len(sheet.connectors)
        picture_count = len(sheet.pictures)

        visual_count = shape_count + connector_count + picture_count

        # Classification logic
        if cell_count == 0 and visual_count == 0:
            classification = "empty"
            strategy = "skip"
        elif visual_count == 0:
            classification = "text_table"
            strategy = "cell_markdown"
        elif cell_count <= 5 and visual_count > 5:
            classification = "visual"
            strategy = "ooxml + screenshot + claude + mermaid"
        elif visual_count > 0 and cell_count > 5:
            classification = "mixed"
            strategy = "cell_markdown + screenshot + claude"
        elif visual_count > 0:
            classification = "visual"
            strategy = "ooxml + screenshot + claude + mermaid"
        else:
            classification = "text_table"
            strategy = "cell_markdown"

        results.append({
            "sheet_name": sheet.name,
            "classification": classification,
            "cell_count": cell_count,
            "shape_count": shape_count,
            "connector_count": connector_count,
            "picture_count": picture_count,
            "strategy": strategy,
        })
        logger.info(
            f"  Sheet '{sheet.name}': {classification} "
            f"(cells={cell_count}, shapes={shape_count}, "
            f"connectors={connector_count}, pictures={picture_count})"
        )

    return results
