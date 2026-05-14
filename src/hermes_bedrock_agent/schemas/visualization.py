"""Visualization data models for graph rendering.

Covers subgraph query results, Mermaid generation, and React Flow export.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LayoutAlgorithm(str, Enum):
    """Graph layout algorithms."""

    FORCE_DIRECTED = "force_directed"
    HIERARCHICAL = "hierarchical"
    CIRCULAR = "circular"
    DAGRE = "dagre"


class VisualizationNode(BaseModel):
    """A node in a visualization subgraph.

    Maps to a GraphEntity but with layout/rendering properties.
    """

    node_id: str = Field(..., description="Entity ID in the knowledge graph")
    label: str = Field(..., description="Display label")
    entity_type: str = Field(default="unknown")
    description: str = Field(default="")

    # Visual properties
    color: str = Field(default="", description="Hex color code for rendering")
    size: float = Field(default=1.0, ge=0.1, description="Relative node size")
    icon: str = Field(default="", description="Icon identifier")

    # Layout (populated after layout computation)
    x: Optional[float] = Field(default=None, description="X position")
    y: Optional[float] = Field(default=None, description="Y position")

    # Metadata
    properties: dict[str, str] = Field(default_factory=dict)
    degree: int = Field(default=0, ge=0, description="Number of connections")


class VisualizationEdge(BaseModel):
    """An edge in a visualization subgraph.

    Maps to a GraphRelation with rendering properties.
    """

    edge_id: str = Field(..., description="Relation ID in the knowledge graph")
    source_id: str = Field(..., description="Source node ID")
    target_id: str = Field(..., description="Target node ID")
    label: str = Field(default="", description="Edge label (relation type)")
    relation_type: str = Field(default="related_to")

    # Visual properties
    color: str = Field(default="", description="Hex color code")
    width: float = Field(default=1.0, ge=0.1, description="Edge thickness")
    style: str = Field(default="solid", description="Line style: solid, dashed, dotted")
    animated: bool = Field(default=False, description="Animated edge (React Flow)")

    # Metadata
    weight: float = Field(default=1.0, ge=0.0)
    properties: dict[str, str] = Field(default_factory=dict)


class SubgraphResult(BaseModel):
    """Result of a subgraph query for visualization.

    Contains nodes, edges, and metadata about the query that produced them.
    Can be exported to Mermaid, React Flow JSON, or other formats.
    """

    # Query info
    query: str = Field(default="", description="Original query or entity name")
    center_entity_id: Optional[str] = Field(default=None, description="Central entity of the subgraph")
    max_hops: int = Field(default=2, ge=1, description="Traversal depth")

    # Graph data
    nodes: list[VisualizationNode] = Field(default_factory=list)
    edges: list[VisualizationEdge] = Field(default_factory=list)

    # Layout
    layout_algorithm: LayoutAlgorithm = Field(default=LayoutAlgorithm.FORCE_DIRECTED)
    layout_computed: bool = Field(default=False)

    # Export formats (populated on demand)
    mermaid_code: str = Field(default="", description="Mermaid diagram source")
    reactflow_json: str = Field(default="", description="React Flow JSON export")

    # Metadata
    node_count: int = Field(default=0)
    edge_count: int = Field(default=0)
    cypher_query: str = Field(default="", description="Cypher query used")
    query_time_ms: Optional[int] = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: object) -> None:
        """Compute counts after init."""
        if self.node_count == 0:
            self.node_count = len(self.nodes)
        if self.edge_count == 0:
            self.edge_count = len(self.edges)

    @property
    def is_empty(self) -> bool:
        return len(self.nodes) == 0
