"""Hybrid retrieval — text search, graph traversal, KB retrieval, fusion.

Modules:
- intent_router: classify question intent → retrieval strategy
- text_retriever: OpenSearch vector/keyword/hybrid search
- graph_retriever: Neptune entity/relation/path retrieval
- bedrock_kb_retriever: optional Bedrock Knowledge Base retrieval
- fusion: merge and deduplicate evidence from multiple sources
- context_builder: build structured LLM context from fused evidence
"""

from hermes_bedrock_agent.retrieval.bedrock_kb_retriever import (
    BedrockKBRetriever,
    KBRetrieverConfig,
)
from hermes_bedrock_agent.retrieval.context_builder import (
    ContextBuilder,
    ContextBuilderConfig,
)
from hermes_bedrock_agent.retrieval.fusion import (
    FusionConfig,
    FusionStrategy,
    fuse_evidence,
)
from hermes_bedrock_agent.retrieval.graph_retriever import (
    GraphRetrieverConfig,
    NeptuneGraphRetriever,
)
from hermes_bedrock_agent.retrieval.query_entity_extractor import (
    EntityIndex,
    EntityMention,
    QueryEntityExtractor,
    QueryExtractionResult,
    QueryLanguage,
    build_graph_search_terms,
)
from hermes_bedrock_agent.retrieval.intent_router import (
    IntentClassification,
    IntentType,
    RetrievalStrategy,
    classify_intent,
)
from hermes_bedrock_agent.retrieval.text_retriever import (
    OpenSearchTextRetriever,
    TextRetrieverConfig,
)

__all__ = [
    # Intent router
    "classify_intent",
    "IntentClassification",
    "IntentType",
    "RetrievalStrategy",
    # Text retriever
    "OpenSearchTextRetriever",
    "TextRetrieverConfig",
    # Graph retriever
    "NeptuneGraphRetriever",
    "GraphRetrieverConfig",
    # Query entity extractor (Phase 10A)
    "QueryEntityExtractor",
    "QueryExtractionResult",
    "QueryLanguage",
    "EntityIndex",
    "EntityMention",
    "build_graph_search_terms",
    # Bedrock KB retriever
    "BedrockKBRetriever",
    "KBRetrieverConfig",
    # Fusion
    "fuse_evidence",
    "FusionConfig",
    "FusionStrategy",
    # Context builder
    "ContextBuilder",
    "ContextBuilderConfig",
]
