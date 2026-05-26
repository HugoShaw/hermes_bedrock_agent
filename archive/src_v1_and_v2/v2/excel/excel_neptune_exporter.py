"""
Excel Neptune exporter — extends base V2 exporter with Excel-specific
metadata on evidence chunk nodes (sheet_name, cell_range, workbook_name).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.neptune_cypher_exporter import (
    NeptuneCypherExporter,
    escape_cypher_string,
    format_property_value,
    safe_label,
    truncate_string,
    MAX_TEXT_PREVIEW_LENGTH,
)

logger = logging.getLogger(__name__)


class ExcelNeptuneCypherExporter(NeptuneCypherExporter):
    """Neptune Cypher exporter with Excel-specific enhancements.

    Extends the base exporter to:
    - Include sheet_name, cell_range, workbook_name on EvidenceChunk nodes
    - Include Excel-specific properties on graph nodes (sheet_name, system, etc.)
    - Add workbook/sheet context to node descriptions
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _build_node_props(self, node: dict[str, Any]) -> dict[str, Any]:
        """Build node properties with Excel-specific fields."""
        props = super()._build_node_props(node)

        # Add Excel-specific properties from node.properties
        node_props = node.get('properties', {})
        excel_fields = [
            'sheet_name', 'system', 'parent_message', 'operation',
            'data_type', 'length', 'required', 'variable',
            'field_no', 'function_type', 'item_type', 'source',
            'row_number', 'remarks_preview',
        ]
        for field in excel_fields:
            val = node_props.get(field)
            if val and val not in ('', None, 'None'):
                props[field] = truncate_string(str(val), 200)

        # source_cell_refs as compact string
        refs = node_props.get('source_cell_refs')
        if refs and isinstance(refs, dict):
            refs_str = ', '.join(f'{k}:{v}' for k, v in list(refs.items())[:10])
            props['source_cell_refs'] = truncate_string(refs_str, 200)

        return props

    def _build_chunk_props(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """Build chunk properties with Excel-specific metadata."""
        props = super()._build_chunk_props(chunk)

        # Add Excel-specific fields from chunk metadata
        metadata = chunk.get('metadata', {})
        excel_chunk_fields = [
            'sheet_name', 'sheet_index', 'workbook_name', 'workbook_id',
            'cell_range', 'table_region_id', 'guessed_sheet_type',
            'row_number', 'parser',
        ]
        for field in excel_chunk_fields:
            val = metadata.get(field)
            if val and val not in ('', None, 'None'):
                props[field] = truncate_string(str(val), 200)

        return props

    def _build_edge_props(self, edge: dict[str, Any]) -> dict[str, Any]:
        """Build edge properties with Excel-specific fields."""
        props = super()._build_edge_props(edge)

        # Add cross-layer link metadata if present
        edge_props = edge.get('properties', {})
        cross_layer_fields = [
            'semantic_relation', 'link_strategy', 'confidence_reason',
            'sheet_name', 'semantic_layer',
        ]
        for field in cross_layer_fields:
            val = edge_props.get(field)
            if val and val not in ('', None, 'None'):
                props[field] = truncate_string(str(val), 200)

        return props
