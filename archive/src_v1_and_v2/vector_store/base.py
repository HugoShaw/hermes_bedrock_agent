"""Vector store base interface — unified abstraction for text/vector retrieval backends.

Provides:
- VectorStoreBackend: abstract base class defining the unified interface
- VectorSearchResult: standardized result model
- VectorStoreRecord: input record for upsert

All backends (LanceDB, OpenSearch, etc.) implement this interface.
Retrieval layer depends ONLY on this interface, never on a specific backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VectorStoreRecord:
    """A single record to upsert into the vector store.

    Maps to DocumentChunk + embedding.
    """

    chunk_id: str
    document_id: str
    text: str
    embedding: list[float]
    source_uri: str = ""
    source_type: str = ""
    page: Optional[int] = None
    section_title: str = ""
    visual_block_ids: list[str] = field(default_factory=list)
    acl: list[str] = field(default_factory=list)
    content_hash: str = ""
    embedding_model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorSearchResult:
    """A single search result from the vector store.

    Unified format for all backends.
    """

    chunk_id: str
    document_id: str
    text: str
    source_uri: str = ""
    source_type: str = ""
    page: Optional[int] = None
    section_title: str = ""
    visual_block_ids: list[str] = field(default_factory=list)
    acl: list[str] = field(default_factory=list)
    score: float = 0.0
    distance: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStoreBackend(ABC):
    """Abstract base class for vector store backends.

    All backends (LanceDB, OpenSearch, etc.) must implement this interface.
    The retrieval layer depends ONLY on this interface.
    """

    @abstractmethod
    def upsert_chunks(self, records: list[VectorStoreRecord]) -> int:
        """Insert or update chunk records.

        Args:
            records: List of VectorStoreRecord to upsert.

        Returns:
            Number of records successfully upserted.
        """
        ...

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Vector similarity search.

        Args:
            query_embedding: Query vector.
            top_k: Number of results to return.
            filters: Optional metadata filters.

        Returns:
            Ranked list of VectorSearchResult.
        """
        ...

    @abstractmethod
    def keyword_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Keyword/full-text search.

        Args:
            query: Text query string.
            top_k: Number of results.
            filters: Optional metadata filters.

        Returns:
            Ranked list of VectorSearchResult.
        """
        ...

    @abstractmethod
    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Hybrid search combining vector + keyword results.

        Args:
            query: Text query string.
            query_embedding: Query vector.
            top_k: Number of results.
            filters: Optional metadata filters.

        Returns:
            Fused and ranked list of VectorSearchResult.
        """
        ...

    @abstractmethod
    def count(self) -> int:
        """Return total number of records in the store."""
        ...

    @abstractmethod
    def delete_collection(self) -> bool:
        """Delete the entire collection/table.

        Returns:
            True if deletion was successful.
        """
        ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Check backend health/connectivity.

        Returns:
            Dict with at minimum: {"healthy": bool, "backend": str, ...}
        """
        ...
