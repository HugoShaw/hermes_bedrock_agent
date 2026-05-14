"""OpenSearch vector store — adapter wrapping existing OpenSearch client.

Provides:
- OpenSearchStore: VectorStoreBackend implementation using OpenSearch
- Wraps existing clients/opensearch_client.py — no logic duplication
- Only adapts to the VectorStoreBackend interface

This is a thin adapter that delegates to the existing OpenSearchClient.
It does NOT reimplement OpenSearch logic.
"""

from __future__ import annotations

from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.vector_store.base import (
    VectorSearchResult,
    VectorStoreBackend,
    VectorStoreRecord,
)

logger = get_logger(__name__)


class OpenSearchStore(VectorStoreBackend):
    """OpenSearch adapter implementing VectorStoreBackend interface.

    Wraps the existing OpenSearchClient from clients/opensearch_client.py.
    All actual OpenSearch logic remains in that client — this is purely
    an interface adapter for backend-agnostic retrieval.

    Args:
        opensearch_client: Instance of OpenSearchClient from clients/.
        index_name: OpenSearch index name.
        vector_field: Field name for embeddings.
        text_field: Field name for text content.
    """

    def __init__(
        self,
        opensearch_client,
        *,
        index_name: str = "enterprise-graphrag",
        vector_field: str = "embedding",
        text_field: str = "text",
    ):
        self._client = opensearch_client
        self._index_name = index_name
        self._vector_field = vector_field
        self._text_field = text_field

    def upsert_chunks(self, records: list[VectorStoreRecord]) -> int:
        """Bulk upsert records to OpenSearch.

        Converts records to OpenSearch bulk format and delegates to client.
        """
        if not records:
            return 0

        actions = []
        for record in records:
            doc = {
                "chunk_id": record.chunk_id,
                "document_id": record.document_id,
                "text": record.text,
                self._vector_field: record.embedding,
                "source_uri": record.source_uri,
                "source_type": record.source_type,
                "page": record.page,
                "section_title": record.section_title,
                "visual_block_ids": record.visual_block_ids,
                "acl": record.acl,
                "content_hash": record.content_hash,
                "embedding_model": record.embedding_model,
            }
            doc.update(record.metadata)
            actions.append({"index": {"_index": self._index_name, "_id": record.chunk_id}})
            actions.append(doc)

        try:
            self._client.bulk(body=actions)
            return len(records)
        except Exception as e:
            logger.warning(f"OpenSearch bulk upsert failed: {e}")
            return 0

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Vector kNN search via OpenSearch."""
        try:
            results = self._client.knn_search(
                vector=query_embedding,
                k=top_k,
                field=self._vector_field,
                index_name=self._index_name,
                filters=filters,
            )
        except Exception as e:
            logger.warning(f"OpenSearch vector search failed: {e}")
            return []

        return self._parse_hits(results)

    def keyword_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """BM25 keyword search via OpenSearch."""
        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "must": [{"match": {self._text_field: query}}],
                }
            },
            "size": top_k,
        }

        if filters:
            body["query"]["bool"]["filter"] = filters

        try:
            results = self._client.search(body=body, index_name=self._index_name)
        except Exception as e:
            logger.warning(f"OpenSearch keyword search failed: {e}")
            return []

        return self._parse_hits(results)

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Hybrid search combining vector + keyword via RRF.

        Gets results from both paths and fuses with RRF.
        """
        vector_results = self.search(
            query_embedding, top_k=top_k, filters=filters
        )
        keyword_results = self.keyword_search(query, top_k=top_k, filters=filters)

        # RRF fusion
        rrf_k = 60
        scored: dict[str, tuple[float, VectorSearchResult]] = {}

        for rank, result in enumerate(vector_results):
            rrf_score = 1.0 / (rrf_k + rank + 1)
            scored[result.chunk_id] = (rrf_score, result)

        for rank, result in enumerate(keyword_results):
            rrf_score = 1.0 / (rrf_k + rank + 1)
            if result.chunk_id in scored:
                old_score, old_result = scored[result.chunk_id]
                scored[result.chunk_id] = (old_score + rrf_score, old_result)
            else:
                scored[result.chunk_id] = (rrf_score, result)

        sorted_results = sorted(scored.values(), key=lambda x: x[0], reverse=True)

        return [
            VectorSearchResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                text=r.text,
                source_uri=r.source_uri,
                source_type=r.source_type,
                page=r.page,
                section_title=r.section_title,
                visual_block_ids=r.visual_block_ids,
                acl=r.acl,
                score=score,
                distance=r.distance,
            )
            for score, r in sorted_results[:top_k]
        ]

    def count(self) -> int:
        """Return document count from OpenSearch index."""
        try:
            result = self._client.count(index_name=self._index_name)
            return result.get("count", 0)
        except Exception:
            return 0

    def delete_collection(self) -> bool:
        """Delete the OpenSearch index."""
        try:
            self._client.delete_index(index_name=self._index_name)
            return True
        except Exception as e:
            logger.warning(f"Failed to delete OpenSearch index: {e}")
            return False

    def health_check(self) -> dict[str, Any]:
        """Check OpenSearch connectivity."""
        try:
            info = self._client.info()
            return {
                "healthy": True,
                "backend": "opensearch",
                "index_name": self._index_name,
                "cluster_name": info.get("cluster_name", "unknown"),
            }
        except Exception as e:
            return {
                "healthy": False,
                "backend": "opensearch",
                "error": str(e),
            }

    def _parse_hits(self, results: dict[str, Any]) -> list[VectorSearchResult]:
        """Parse OpenSearch response hits into VectorSearchResult list."""
        output = []
        hits = results.get("hits", {}).get("hits", [])

        for rank, hit in enumerate(hits):
            src = hit.get("_source", {})
            score = hit.get("_score", 0.0) or 0.0

            chunk_id = src.get("chunk_id", "")
            if not chunk_id:
                continue

            output.append(VectorSearchResult(
                chunk_id=chunk_id,
                document_id=src.get("document_id", ""),
                text=src.get(self._text_field, src.get("text", "")),
                source_uri=src.get("source_uri", ""),
                source_type=src.get("source_type", ""),
                page=src.get("page"),
                section_title=src.get("section_title", ""),
                visual_block_ids=src.get("visual_block_ids", []),
                acl=src.get("acl", []),
                score=score,
            ))

        return output
