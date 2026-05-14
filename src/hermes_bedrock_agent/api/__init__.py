"""API layer — FastAPI routes for query, graph visualization, and ingestion.

Modules:
- routes_query: POST /query endpoint
- routes_graph: GET /graph/subgraph, /graph/mermaid, /graph/reactflow
- routes_ingestion: GET /ingestion/status, POST /ingestion/dry-run
"""

from hermes_bedrock_agent.api.routes_graph import (
    GraphVisualizationService,
    router as graph_router,
    set_graph_service,
)
from hermes_bedrock_agent.api.routes_ingestion import router as ingestion_router
from hermes_bedrock_agent.api.routes_query import (
    QueryService,
    router as query_router,
    set_query_service,
)

__all__ = [
    "GraphVisualizationService",
    "QueryService",
    "graph_router",
    "ingestion_router",
    "query_router",
    "set_graph_service",
    "set_query_service",
]
