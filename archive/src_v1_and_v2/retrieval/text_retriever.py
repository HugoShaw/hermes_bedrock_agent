"""Text retriever — vector store-backed text/vector/hybrid search.

Provides:
- VectorStoreTextRetriever: backend-agnostic retriever via VectorStoreBackend
- OpenSearchTextRetriever: legacy OpenSearch-specific retriever (preserved)
- Both convert results to TextEvidence models

VectorStoreTextRetriever is the preferred interface for Phase 9+.
It works with any VectorStoreBackend (LanceDB, OpenSearch, etc.).
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.retrieval import RetrievalSource, TextEvidence

logger = get_logger(__name__)


class TextRetrieverConfig:
    """Configuration for text retrieval."""

    def __init__(
        self,
        *,
        index_name: str = "chunks",
        vector_field: str = "embedding",
        text_field: str = "text",
        top_k: int = 10,
        min_score: float = 0.0,
        hybrid_weight_vector: float = 0.7,
        hybrid_weight_text: float = 0.3,
    ):
        self.index_name = index_name
        self.vector_field = vector_field
        self.text_field = text_field
        self.top_k = top_k
        self.min_score = min_score
        self.hybrid_weight_vector = hybrid_weight_vector
        self.hybrid_weight_text = hybrid_weight_text


class VectorStoreTextRetriever:
    """Backend-agnostic text retriever via VectorStoreBackend interface.

    This is the preferred retriever for Phase 9+.
    Works with any backend: LanceDB (local), OpenSearch (remote), etc.

    Accepts a VectorStoreBackend instance via dependency injection.
    Converts VectorSearchResult → TextEvidence for the retrieval chain.
    """

    def __init__(
        self,
        vector_store,
        config: Optional[TextRetrieverConfig] = None,
    ):
        """Initialize with injected vector store backend.

        Args:
            vector_store: Instance implementing VectorStoreBackend interface.
            config: Retrieval configuration.
        """
        from hermes_bedrock_agent.vector_store.base import VectorStoreBackend

        if not isinstance(vector_store, VectorStoreBackend):
            raise TypeError(
                f"vector_store must implement VectorStoreBackend, "
                f"got {type(vector_store).__name__}"
            )
        self._store = vector_store
        self.config = config or TextRetrieverConfig()

    def vector_search(
        self,
        query_embedding: list[float],
        *,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
        query_text: str = "",
    ) -> list[TextEvidence]:
        """Perform vector similarity search.

        Args:
            query_embedding: Pre-computed query embedding vector.
            top_k: Number of results. Defaults to config.top_k.
            filters: Optional metadata filters.
            query_text: Original query text (for traceability).

        Returns:
            List of TextEvidence objects ranked by vector similarity.
        """
        k = top_k or self.config.top_k

        try:
            results = self._store.search(
                query_embedding, top_k=k, filters=filters
            )
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

        return self._convert_results(
            results,
            source=RetrievalSource.OPENSEARCH_VECTOR,
            query_text=query_text,
        )

    def keyword_search(
        self,
        query_text: str,
        *,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[TextEvidence]:
        """Perform keyword/full-text search.

        Args:
            query_text: Search query string.
            top_k: Number of results. Defaults to config.top_k.
            filters: Optional metadata filters.

        Returns:
            List of TextEvidence objects ranked by keyword relevance.
        """
        k = top_k or self.config.top_k

        try:
            results = self._store.keyword_search(
                query_text, top_k=k, filters=filters
            )
        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")
            return []

        return self._convert_results(
            results,
            source=RetrievalSource.OPENSEARCH_TEXT,
            query_text=query_text,
        )

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: Optional[list[float]] = None,
        *,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[TextEvidence]:
        """Perform hybrid search combining vector + keyword.

        Args:
            query_text: Search query string.
            query_embedding: Pre-computed query embedding (optional).
            top_k: Number of results. Defaults to config.top_k.
            filters: Optional metadata filters.

        Returns:
            Merged and re-ranked TextEvidence list.
        """
        k = top_k or self.config.top_k

        if not query_embedding:
            return self.keyword_search(query_text, top_k=k, filters=filters)

        try:
            results = self._store.hybrid_search(
                query_text, query_embedding, top_k=k, filters=filters
            )
        except Exception as e:
            logger.warning(f"Hybrid search failed: {e}")
            return []

        return self._convert_results(
            results,
            source=RetrievalSource.OPENSEARCH_VECTOR,
            query_text=query_text,
        )

    def _convert_results(
        self,
        results,
        *,
        source: RetrievalSource,
        query_text: str = "",
    ) -> list[TextEvidence]:
        """Convert VectorSearchResult list to TextEvidence list."""
        from hermes_bedrock_agent.vector_store.base import VectorSearchResult

        evidence_list = []
        for rank, result in enumerate(results):
            if not result.chunk_id:
                continue

            if result.score < self.config.min_score:
                continue

            evidence_id = hashlib.sha256(
                f"{result.chunk_id}:{source.value}:{query_text}".encode()
            ).hexdigest()[:16]

            evidence = TextEvidence(
                evidence_id=f"te_{evidence_id}",
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                source_uri=result.source_uri,
                content=result.text,
                section_title=result.section_title,
                page=result.page,
                source=source,
                score=result.score,
                rank=rank,
                query_text=query_text,
                acl=result.acl,
            )
            evidence_list.append(evidence)

        return evidence_list


class OpenSearchTextRetriever:
    """OpenSearch-based text/vector/hybrid retriever.

    Accepts an opensearch_client (from clients/opensearch_client.py)
    via dependency injection. Never creates its own client.
    """

    def __init__(
        self,
        opensearch_client,
        config: Optional[TextRetrieverConfig] = None,
    ):
        """Initialize with injected OpenSearch client.

        Args:
            opensearch_client: Instance of OpenSearchClient from clients/.
            config: Retrieval configuration.
        """
        self._client = opensearch_client
        self.config = config or TextRetrieverConfig()

    def vector_search(
        self,
        query_embedding: list[float],
        *,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
        query_text: str = "",
    ) -> list[TextEvidence]:
        """Perform kNN vector search on OpenSearch.

        Args:
            query_embedding: Pre-computed query embedding vector.
            top_k: Number of results. Defaults to config.top_k.
            filters: Optional OpenSearch filter (e.g. ACL, source_type).
            query_text: Original query text (for traceability).

        Returns:
            List of TextEvidence objects ranked by vector similarity.
        """
        k = top_k or self.config.top_k

        try:
            results = self._client.knn_search(
                vector=query_embedding,
                k=k,
                field=self.config.vector_field,
                index_name=self.config.index_name,
                filters=filters,
            )
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

        return self._parse_results(
            results,
            source=RetrievalSource.OPENSEARCH_VECTOR,
            query_text=query_text,
        )

    def keyword_search(
        self,
        query_text: str,
        *,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[TextEvidence]:
        """Perform BM25 keyword search on OpenSearch.

        Args:
            query_text: Search query string.
            top_k: Number of results. Defaults to config.top_k.
            filters: Optional OpenSearch filter.

        Returns:
            List of TextEvidence objects ranked by BM25 score.
        """
        k = top_k or self.config.top_k

        body = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {self.config.text_field: query_text}}
                    ],
                }
            },
            "size": k,
        }

        if filters:
            body["query"]["bool"]["filter"] = filters

        try:
            results = self._client.search(
                body=body,
                index_name=self.config.index_name,
            )
        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")
            return []

        return self._parse_results(
            results,
            source=RetrievalSource.OPENSEARCH_TEXT,
            query_text=query_text,
        )

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: Optional[list[float]] = None,
        *,
        top_k: Optional[int] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[TextEvidence]:
        """Perform hybrid search combining vector + keyword results.

        Uses weighted scoring to combine vector similarity and BM25.
        If no embedding is provided, falls back to keyword-only search.

        Args:
            query_text: Search query string.
            query_embedding: Pre-computed query embedding (optional).
            top_k: Number of results. Defaults to config.top_k.
            filters: Optional OpenSearch filter.

        Returns:
            Merged and re-ranked TextEvidence list.
        """
        k = top_k or self.config.top_k

        # Keyword results
        keyword_results = self.keyword_search(query_text, top_k=k, filters=filters)

        if not query_embedding:
            return keyword_results[:k]

        # Vector results
        vector_results = self.vector_search(
            query_embedding, top_k=k, filters=filters, query_text=query_text
        )

        # Merge with weighted scoring
        return self._merge_results(
            vector_results,
            keyword_results,
            top_k=k,
        )

    def _merge_results(
        self,
        vector_results: list[TextEvidence],
        keyword_results: list[TextEvidence],
        *,
        top_k: int = 10,
    ) -> list[TextEvidence]:
        """Merge vector and keyword results using weighted scoring.

        Deduplicates by chunk_id, combines scores with configured weights.
        """
        scored: dict[str, tuple[float, TextEvidence]] = {}

        # Score vector results
        for i, ev in enumerate(vector_results):
            rank_score = 1.0 / (i + 1)
            weighted = rank_score * self.config.hybrid_weight_vector
            if ev.chunk_id in scored:
                old_score, old_ev = scored[ev.chunk_id]
                scored[ev.chunk_id] = (old_score + weighted, old_ev)
            else:
                scored[ev.chunk_id] = (weighted, ev)

        # Score keyword results
        for i, ev in enumerate(keyword_results):
            rank_score = 1.0 / (i + 1)
            weighted = rank_score * self.config.hybrid_weight_text
            if ev.chunk_id in scored:
                old_score, old_ev = scored[ev.chunk_id]
                scored[ev.chunk_id] = (old_score + weighted, old_ev)
            else:
                scored[ev.chunk_id] = (weighted, ev)

        # Sort by combined score
        sorted_results = sorted(scored.values(), key=lambda x: x[0], reverse=True)

        # Update ranks and return
        output = []
        for rank, (score, ev) in enumerate(sorted_results[:top_k]):
            updated = ev.model_copy(update={"rank": rank, "score": score})
            output.append(updated)

        return output

    def _parse_results(
        self,
        results: dict[str, Any],
        *,
        source: RetrievalSource,
        query_text: str = "",
    ) -> list[TextEvidence]:
        """Parse OpenSearch response into TextEvidence list."""
        evidence_list = []
        hits = results.get("hits", {}).get("hits", [])

        for rank, hit in enumerate(hits):
            src = hit.get("_source", {})
            score = hit.get("_score", 0.0) or 0.0

            # Skip below min_score
            if score < self.config.min_score:
                continue

            chunk_id = src.get("chunk_id", "")
            if not chunk_id:
                continue

            evidence_id = hashlib.sha256(
                f"{chunk_id}:{source.value}:{query_text}".encode()
            ).hexdigest()[:16]

            evidence = TextEvidence(
                evidence_id=f"te_{evidence_id}",
                chunk_id=chunk_id,
                document_id=src.get("document_id", ""),
                source_uri=src.get("source_uri", ""),
                content=src.get(self.config.text_field, src.get("text", "")),
                section_title=src.get("section_title", ""),
                page=src.get("page"),
                source=source,
                score=score,
                rank=rank,
                query_text=query_text,
                acl=src.get("acl", []),
            )
            evidence_list.append(evidence)

        return evidence_list
