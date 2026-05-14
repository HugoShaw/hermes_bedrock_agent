"""Graph visualization API routes — subgraph, mermaid, reactflow.

Calls visualization modules. Does NOT access Neptune directly.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


# Response models
class SubgraphResponse(BaseModel):
    """Subgraph query response."""

    success: bool = True
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    center_entity: str = ""
    depth: int = 2
    error: Optional[str] = None


class MermaidResponse(BaseModel):
    """Mermaid export response."""

    success: bool = True
    mermaid_code: str = ""
    node_count: int = 0
    edge_count: int = 0
    error: Optional[str] = None


class ReactFlowResponse(BaseModel):
    """React Flow export response."""

    success: bool = True
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    error: Optional[str] = None


class GraphVisualizationService:
    """Service layer for graph visualization operations.

    Wraps SubgraphQueryService, MermaidGenerator, ReactFlowExporter.
    Can be mocked for testing.
    """

    def __init__(
        self,
        subgraph_service=None,
        mermaid_generator=None,
        reactflow_exporter=None,
        layout_engine=None,
    ):
        self._subgraph = subgraph_service
        self._mermaid = mermaid_generator
        self._reactflow = reactflow_exporter
        self._layout = layout_engine

    def query_subgraph(
        self,
        center_entity: str,
        depth: int = 2,
        max_nodes: int = 50,
        node_types: Optional[list[str]] = None,
        edge_types: Optional[list[str]] = None,
        exclude_node_types: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Query a bounded subgraph."""
        if not self._subgraph:
            from hermes_bedrock_agent.visualization.subgraph_query import (
                SubgraphQueryService,
            )
            self._subgraph = SubgraphQueryService(mock_mode=True)

        result = self._subgraph.query_subgraph(
            center_entity=center_entity,
            depth=depth,
            max_nodes=max_nodes,
            node_types=node_types,
            edge_types=edge_types,
            exclude_node_types=exclude_node_types,
        )

        return {
            "nodes": [n.model_dump() for n in result.nodes],
            "edges": [e.model_dump() for e in result.edges],
            "node_count": result.node_count,
            "edge_count": result.edge_count,
            "center_entity": center_entity,
            "depth": depth,
        }

    def generate_mermaid(
        self,
        center_entity: str,
        depth: int = 2,
        max_nodes: int = 30,
        direction: str = "LR",
        diagram_type: str = "flowchart",
    ) -> dict[str, Any]:
        """Generate Mermaid diagram for a subgraph."""
        if not self._subgraph:
            from hermes_bedrock_agent.visualization.subgraph_query import (
                SubgraphQueryService,
            )
            self._subgraph = SubgraphQueryService(mock_mode=True)

        if not self._mermaid:
            from hermes_bedrock_agent.visualization.mermaid_generator import (
                MermaidGenerator,
            )
            self._mermaid = MermaidGenerator()

        subgraph = self._subgraph.query_subgraph(
            center_entity=center_entity,
            depth=depth,
            max_nodes=max_nodes,
        )

        if diagram_type == "impact":
            code = self._mermaid.generate_impact_map(
                subgraph, center_label=center_entity, direction=direction
            )
        elif diagram_type == "dependency":
            code = self._mermaid.generate_dependency_map(
                subgraph, center_label=center_entity, direction=direction
            )
        else:
            code = self._mermaid.generate_flowchart(
                subgraph, direction=direction, max_nodes=max_nodes
            )

        return {
            "mermaid_code": code,
            "node_count": subgraph.node_count,
            "edge_count": subgraph.edge_count,
        }

    def export_reactflow(
        self,
        center_entity: str,
        depth: int = 2,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        """Export subgraph as React Flow JSON."""
        if not self._subgraph:
            from hermes_bedrock_agent.visualization.subgraph_query import (
                SubgraphQueryService,
            )
            self._subgraph = SubgraphQueryService(mock_mode=True)

        if not self._layout:
            from hermes_bedrock_agent.visualization.graph_layout import (
                GraphLayoutEngine,
            )
            self._layout = GraphLayoutEngine()

        if not self._reactflow:
            from hermes_bedrock_agent.visualization.reactflow_exporter import (
                ReactFlowExporter,
            )
            self._reactflow = ReactFlowExporter()

        subgraph = self._subgraph.query_subgraph(
            center_entity=center_entity,
            depth=depth,
            max_nodes=max_nodes,
        )

        # Compute layout
        subgraph = self._layout.compute_layout(subgraph)

        # Export
        return self._reactflow.export(subgraph)


# Dependency injection
_graph_service: Optional[GraphVisualizationService] = None


def get_graph_service() -> GraphVisualizationService:
    """Get graph visualization service."""
    if _graph_service is None:
        return GraphVisualizationService()
    return _graph_service


def set_graph_service(service: GraphVisualizationService) -> None:
    """Set graph visualization service (for app startup or testing)."""
    global _graph_service
    _graph_service = service


@router.get("/subgraph", response_model=SubgraphResponse)
async def get_subgraph(
    center_entity: str = Query(..., description="Center entity ID or name"),
    depth: int = Query(default=2, ge=1, le=5, description="Traversal depth"),
    max_nodes: int = Query(default=50, ge=1, le=200, description="Max nodes"),
    node_types: Optional[str] = Query(default=None, description="Comma-separated node types"),
    exclude_types: Optional[str] = Query(default=None, description="Comma-separated types to exclude"),
    service: GraphVisualizationService = Depends(get_graph_service),
) -> SubgraphResponse:
    """Query a bounded subgraph centered on an entity."""
    try:
        node_type_list = node_types.split(",") if node_types else None
        exclude_list = exclude_types.split(",") if exclude_types else None

        result = service.query_subgraph(
            center_entity=center_entity,
            depth=depth,
            max_nodes=max_nodes,
            node_types=node_type_list,
            exclude_node_types=exclude_list,
        )
        return SubgraphResponse(
            success=True,
            nodes=result["nodes"],
            edges=result["edges"],
            node_count=result["node_count"],
            edge_count=result["edge_count"],
            center_entity=center_entity,
            depth=depth,
        )
    except Exception as e:
        logger.error(f"Subgraph query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mermaid", response_model=MermaidResponse)
async def get_mermaid(
    center_entity: str = Query(..., description="Center entity ID or name"),
    depth: int = Query(default=2, ge=1, le=5),
    max_nodes: int = Query(default=30, ge=1, le=100),
    direction: str = Query(default="LR", description="LR or TD"),
    diagram_type: str = Query(default="flowchart", description="flowchart, impact, dependency"),
    service: GraphVisualizationService = Depends(get_graph_service),
) -> MermaidResponse:
    """Generate Mermaid diagram for a subgraph."""
    try:
        result = service.generate_mermaid(
            center_entity=center_entity,
            depth=depth,
            max_nodes=max_nodes,
            direction=direction,
            diagram_type=diagram_type,
        )
        return MermaidResponse(
            success=True,
            mermaid_code=result["mermaid_code"],
            node_count=result["node_count"],
            edge_count=result["edge_count"],
        )
    except Exception as e:
        logger.error(f"Mermaid generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reactflow", response_model=ReactFlowResponse)
async def get_reactflow(
    center_entity: str = Query(..., description="Center entity ID or name"),
    depth: int = Query(default=2, ge=1, le=5),
    max_nodes: int = Query(default=50, ge=1, le=200),
    service: GraphVisualizationService = Depends(get_graph_service),
) -> ReactFlowResponse:
    """Export subgraph as React Flow JSON."""
    try:
        result = service.export_reactflow(
            center_entity=center_entity,
            depth=depth,
            max_nodes=max_nodes,
        )
        return ReactFlowResponse(
            success=True,
            nodes=result.get("nodes", []),
            edges=result.get("edges", []),
            metadata=result.get("metadata", {}),
        )
    except Exception as e:
        logger.error(f"React Flow export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
