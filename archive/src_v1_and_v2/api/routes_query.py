"""Query API routes — POST /query endpoint.

Calls retrieval → context_builder → answer_generator.
Does NOT access OpenSearch/Neptune/Bedrock directly — delegates to service layer.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.retrieval import AnswerResult

logger = get_logger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


# Request/Response models
class QueryRequest(BaseModel):
    """Query request body."""

    question: str = Field(..., min_length=1, max_length=2000, description="User question")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results per retriever")
    graph_depth: int = Field(default=2, ge=1, le=5, description="Graph traversal depth")
    strategy: str = Field(
        default="auto",
        description="Retrieval strategy: auto, text, graph, hybrid, kb",
    )
    filters: dict = Field(default_factory=dict, description="Optional filters (acl, date, type)")
    user_acl: list[str] = Field(default_factory=list, description="User ACL tags for filtering")


class QueryResponse(BaseModel):
    """Query response envelope."""

    success: bool = True
    data: Optional[AnswerResult] = None
    error: Optional[str] = None


class QueryService:
    """Service layer that orchestrates retrieval → generation.

    Injected into the route handler. Can be replaced with mock for testing.
    """

    def __init__(
        self,
        intent_router=None,
        text_retriever=None,
        graph_retriever=None,
        kb_retriever=None,
        fusion_func=None,
        context_builder=None,
        answer_generator=None,
    ):
        self._intent_router = intent_router
        self._text_retriever = text_retriever
        self._graph_retriever = graph_retriever
        self._kb_retriever = kb_retriever
        self._fusion_func = fusion_func
        self._context_builder = context_builder
        self._answer_generator = answer_generator

    async def execute_query(self, request: QueryRequest) -> AnswerResult:
        """Execute the full query pipeline.

        Steps:
        1. Classify intent
        2. Retrieve from text/graph/kb based on strategy
        3. Fuse results
        4. Generate answer
        """
        from hermes_bedrock_agent.retrieval.fusion import FusionConfig, fuse_evidence
        from hermes_bedrock_agent.retrieval.intent_router import (
            RetrievalStrategy,
            classify_intent,
        )
        from hermes_bedrock_agent.schemas.retrieval import FusedContext

        # Step 1: Classify intent (or use explicit strategy)
        if request.strategy == "auto":
            intent_result = classify_intent(request.question)
            strategy = intent_result.strategy
        else:
            strategy_map = {
                "text": RetrievalStrategy.TEXT,
                "graph": RetrievalStrategy.GRAPH,
                "hybrid": RetrievalStrategy.HYBRID,
                "kb": RetrievalStrategy.KB_OPTIONAL,
            }
            strategy = strategy_map.get(request.strategy, RetrievalStrategy.HYBRID)

        # Step 2: Retrieve
        text_evidence = []
        graph_evidence = []

        if strategy in (RetrievalStrategy.TEXT, RetrievalStrategy.HYBRID, RetrievalStrategy.KB_OPTIONAL):
            if self._text_retriever:
                text_evidence = self._text_retriever.search(
                    query=request.question,
                    top_k=request.top_k,
                )

        if strategy in (RetrievalStrategy.GRAPH, RetrievalStrategy.HYBRID):
            if self._graph_retriever:
                graph_evidence = self._graph_retriever.retrieve_graph_context(
                    query=request.question,
                    max_hops=request.graph_depth,
                )

        if strategy == RetrievalStrategy.KB_OPTIONAL and self._kb_retriever:
            kb_evidence = self._kb_retriever.retrieve(
                query=request.question,
                top_k=request.top_k,
            )
            text_evidence.extend(kb_evidence)

        # Step 3: Fuse
        fusion_func = self._fusion_func or fuse_evidence
        fused = fusion_func(
            text_evidence=text_evidence,
            graph_evidence=graph_evidence,
        )

        # Step 4: Generate answer
        if self._answer_generator:
            result = self._answer_generator.generate_answer(
                question=request.question,
                fused_context=fused,
            )
            result.metadata = {
                "strategy": strategy.value if hasattr(strategy, "value") else str(strategy),
                "filters": request.filters,
            }
            return result

        # Fallback: return context without generation
        return AnswerResult(
            query=request.question,
            answer="[No answer generator configured]",
            text_evidence_used=len(text_evidence),
            graph_evidence_used=len(graph_evidence),
            metadata={"strategy": str(strategy)},
        )


# Dependency injection placeholder
_query_service: Optional[QueryService] = None


def get_query_service() -> QueryService:
    """Get the query service instance (dependency injection)."""
    if _query_service is None:
        return QueryService()
    return _query_service


def set_query_service(service: QueryService) -> None:
    """Set the query service instance (for app startup or testing)."""
    global _query_service
    _query_service = service


@router.post("", response_model=QueryResponse)
async def query_endpoint(
    request: QueryRequest,
    service: QueryService = Depends(get_query_service),
) -> QueryResponse:
    """Execute a hybrid GraphRAG query.

    Performs intent classification, retrieval, fusion, and answer generation.
    """
    try:
        result = await service.execute_query(request)
        return QueryResponse(success=True, data=result)
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
