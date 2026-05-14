"""React Flow exporter — converts subgraph data to React Flow JSON format.

Provides:
- ReactFlowExporter: export nodes/edges with positions, labels, types, metadata
- Outputs JSON compatible with React Flow / XYFlow frontend components
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.visualization import (
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)

logger = get_logger(__name__)


# Node type → React Flow node type mapping
_RF_NODE_TYPES: dict[str, str] = {
    "system": "system",
    "module": "module",
    "business_process": "process",
    "process_step": "step",
    "data_source": "database",
    "table": "database",
    "api": "api",
    "service": "service",
    "unknown": "default",
}

# Node type → default color for React Flow styling
_RF_COLORS: dict[str, str] = {
    "system": "#4A90D9",
    "module": "#67B7DC",
    "business_process": "#6794DC",
    "process_step": "#8B67DC",
    "data_source": "#DC6788",
    "table": "#DC8B67",
    "api": "#67DC8B",
    "service": "#DCB767",
    "unknown": "#999999",
}


@dataclass
class ReactFlowConfig:
    """Configuration for React Flow export."""

    default_node_width: int = 180
    default_node_height: int = 60
    include_metadata: bool = True
    include_handles: bool = True
    edge_type: str = "smoothstep"  # smoothstep, straight, bezier, step
    animated_edges: bool = False
    lang: str = "en"  # zh | en | ja
    label_mode: str = "technical"  # technical | business | mixed


class ReactFlowExporter:
    """Exports SubgraphResult to React Flow JSON format.

    Produces a JSON structure with nodes[] and edges[] arrays,
    each containing position, label, type, and metadata suitable
    for rendering with React Flow / XYFlow.
    """

    def __init__(self, config: Optional[ReactFlowConfig] = None):
        self.config = config or ReactFlowConfig()

    def export(
        self,
        subgraph: SubgraphResult,
        *,
        include_positions: bool = True,
        i18n_data: Optional[dict[str, dict]] = None,
        lang: Optional[str] = None,
        label_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        """Export subgraph to React Flow JSON structure.

        Args:
            subgraph: SubgraphResult (ideally with layout computed).
            include_positions: Whether to include x/y positions.
            i18n_data: Optional mapping of entity_id/canonical → i18n fields.
            lang: Override language (zh/en/ja).
            label_mode: Override label mode (technical/business/mixed).

        Returns:
            Dict with 'nodes', 'edges', and 'metadata' keys.
        """
        use_lang = lang or self.config.lang
        use_label_mode = label_mode or self.config.label_mode

        rf_nodes = [
            self._export_node(node, include_positions, i18n_data, use_lang, use_label_mode)
            for node in subgraph.nodes
        ]
        rf_edges = [
            self._export_edge(edge, i18n_data, use_lang, use_label_mode)
            for edge in subgraph.edges
        ]

        result: dict[str, Any] = {
            "nodes": rf_nodes,
            "edges": rf_edges,
        }

        if self.config.include_metadata:
            result["metadata"] = {
                "query": subgraph.query,
                "center_entity_id": subgraph.center_entity_id,
                "max_hops": subgraph.max_hops,
                "node_count": subgraph.node_count,
                "edge_count": subgraph.edge_count,
                "layout_algorithm": subgraph.layout_algorithm.value,
                "layout_computed": subgraph.layout_computed,
            }

        return result

    def export_json(
        self,
        subgraph: SubgraphResult,
        *,
        indent: int = 2,
        include_positions: bool = True,
        i18n_data: Optional[dict[str, dict]] = None,
        lang: Optional[str] = None,
        label_mode: Optional[str] = None,
    ) -> str:
        """Export subgraph to React Flow JSON string.

        Args:
            subgraph: SubgraphResult to export.
            indent: JSON indentation level.
            include_positions: Whether to include positions.
            i18n_data: Optional mapping of entity_id/canonical → i18n fields.
            lang: Override language (zh/en/ja).
            label_mode: Override label mode (technical/business/mixed).

        Returns:
            JSON string ready for frontend consumption.
        """
        data = self.export(
            subgraph,
            include_positions=include_positions,
            i18n_data=i18n_data,
            lang=lang,
            label_mode=label_mode,
        )
        return json.dumps(data, indent=indent, ensure_ascii=False, default=str)

    def _export_node(
        self,
        node: VisualizationNode,
        include_positions: bool,
        i18n_data: Optional[dict[str, dict]] = None,
        lang: str = "en",
        label_mode: str = "technical",
    ) -> dict[str, Any]:
        """Convert a VisualizationNode to React Flow node format."""
        from hermes_bedrock_agent.visualization.mermaid_generator import resolve_i18n_label

        resolved_label = resolve_i18n_label(
            node.node_id, node.label,
            i18n_data=i18n_data,
            lang=lang,
            label_mode=label_mode,
        )

        rf_node: dict[str, Any] = {
            "id": node.node_id,
            "type": _RF_NODE_TYPES.get(node.entity_type, "default"),
            "data": {
                "label": resolved_label,
                "entityType": node.entity_type,
                "description": node.description,
            },
        }

        # Position
        if include_positions and node.x is not None and node.y is not None:
            rf_node["position"] = {"x": node.x, "y": node.y}
        else:
            rf_node["position"] = {"x": 0, "y": 0}

        # Style
        color = node.color or _RF_COLORS.get(node.entity_type, _RF_COLORS["unknown"])
        rf_node["style"] = {
            "background": color,
            "width": self.config.default_node_width,
            "height": self.config.default_node_height,
        }

        # Metadata
        if self.config.include_metadata and node.properties:
            rf_node["data"]["metadata"] = node.properties

        # Node size based on degree
        if node.degree > 0:
            rf_node["data"]["degree"] = node.degree

        return rf_node

    def _export_edge(
        self,
        edge: VisualizationEdge,
        i18n_data: Optional[dict[str, dict]] = None,
        lang: str = "en",
        label_mode: str = "technical",
    ) -> dict[str, Any]:
        """Convert a VisualizationEdge to React Flow edge format."""
        rf_edge: dict[str, Any] = {
            "id": edge.edge_id,
            "source": edge.source_id,
            "target": edge.target_id,
            "type": self.config.edge_type,
        }

        # Label — resolve via i18n if available
        if edge.label:
            resolved_label = edge.label
            if i18n_data and label_mode != "technical":
                from hermes_bedrock_agent.graph.i18n_enricher import (
                    BUILTIN_RELATION_I18N_MAP,
                )
                rel_key = edge.relation_type.lower() if edge.relation_type else ""
                if rel_key in BUILTIN_RELATION_I18N_MAP:
                    resolved_label = BUILTIN_RELATION_I18N_MAP[rel_key].get(
                        lang, edge.label
                    )
            rf_edge["label"] = resolved_label

        # Style
        style: dict[str, Any] = {}
        if edge.color:
            style["stroke"] = edge.color
        if edge.width != 1.0:
            style["strokeWidth"] = edge.width
        if edge.style == "dashed":
            style["strokeDasharray"] = "5 5"
        elif edge.style == "dotted":
            style["strokeDasharray"] = "2 2"
        if style:
            rf_edge["style"] = style

        # Animation
        if edge.animated or self.config.animated_edges:
            rf_edge["animated"] = True

        # Metadata
        if self.config.include_metadata:
            rf_edge["data"] = {
                "relationType": edge.relation_type,
                "weight": edge.weight,
            }
            if edge.properties:
                rf_edge["data"]["metadata"] = edge.properties

        return rf_edge
