"""FastAPI application — main entry point for the Enterprise GraphRAG API.

Registers all routers and provides the health endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel, Field

from hermes_bedrock_agent.api.routes_graph import router as graph_router
from hermes_bedrock_agent.api.routes_ingestion import router as ingestion_router
from hermes_bedrock_agent.api.routes_query import router as query_router

app = FastAPI(
    title="Enterprise Hybrid GraphRAG",
    description=(
        "Hybrid retrieval-augmented generation combining text search (OpenSearch), "
        "graph traversal (Neptune), and Bedrock Knowledge Bases."
    ),
    version="0.8.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str = "0.8.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    components: dict = Field(default_factory=dict)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        components={
            "api": "up",
            "retrieval": "configured",
            "generation": "configured",
            "visualization": "configured",
        },
    )


# Register routers
app.include_router(query_router)
app.include_router(graph_router)
app.include_router(ingestion_router)


def create_app() -> FastAPI:
    """Factory function for creating the FastAPI app.

    Use this for custom configuration or testing.
    """
    return app
