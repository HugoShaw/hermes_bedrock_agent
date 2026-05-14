"""Pydantic data models shared across all pipeline stages.

All core schemas are re-exported here for convenient imports:
    from hermes_bedrock_agent.schemas import SourceDocument, DocumentChunk, GraphEntity
"""

from hermes_bedrock_agent.schemas.chunk import (
    ChunkEmbedding,
    ChunkType,
    DocumentChunk,
)
from hermes_bedrock_agent.schemas.document import (
    DocumentSection,
    DocumentStatus,
    NormalizedDocument,
    SourceDocument,
    SourceType,
)
from hermes_bedrock_agent.schemas.graph import (
    EntityType,
    EvidenceRecord,
    GraphEntity,
    GraphRelation,
    RelationType,
)
from hermes_bedrock_agent.schemas.retrieval import (
    AnswerResult,
    Citation,
    FusedContext,
    GraphEvidence,
    RetrievalSource,
    TextEvidence,
)
from hermes_bedrock_agent.schemas.visual import (
    VisualBlock,
    VisualType,
)
from hermes_bedrock_agent.schemas.visualization import (
    LayoutAlgorithm,
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)

__all__ = [
    # Document
    "SourceDocument",
    "NormalizedDocument",
    "DocumentSection",
    "SourceType",
    "DocumentStatus",
    # Visual
    "VisualBlock",
    "VisualType",
    # Chunk
    "DocumentChunk",
    "ChunkEmbedding",
    "ChunkType",
    # Graph
    "GraphEntity",
    "GraphRelation",
    "EvidenceRecord",
    "EntityType",
    "RelationType",
    # Retrieval
    "TextEvidence",
    "GraphEvidence",
    "FusedContext",
    "AnswerResult",
    "Citation",
    "RetrievalSource",
    # Visualization
    "VisualizationNode",
    "VisualizationEdge",
    "SubgraphResult",
    "LayoutAlgorithm",
]
