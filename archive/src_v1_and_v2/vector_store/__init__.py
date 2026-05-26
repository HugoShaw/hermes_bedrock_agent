"""Vector store layer — backend-agnostic vector retrieval.

Provides:
- VectorStoreBackend: abstract interface
- LanceDBStore: local vector store (default)
- OpenSearchStore: remote OpenSearch adapter
- create_vector_store(): factory function based on config

Usage:
    from hermes_bedrock_agent.vector_store import create_vector_store
    store = create_vector_store()  # reads VECTOR_STORE_BACKEND from env
"""

from __future__ import annotations

from typing import Optional

from hermes_bedrock_agent.vector_store.base import (
    VectorSearchResult,
    VectorStoreBackend,
    VectorStoreRecord,
)


def create_vector_store(
    *,
    backend: Optional[str] = None,
    **kwargs,
) -> VectorStoreBackend:
    """Factory function to create a vector store backend.

    Reads VECTOR_STORE_BACKEND from settings if not provided.

    Args:
        backend: Override backend selection ('lancedb' or 'opensearch').
        **kwargs: Backend-specific configuration.

    Returns:
        Configured VectorStoreBackend instance.
    """
    if backend is None:
        import os
        backend = os.getenv("VECTOR_STORE_BACKEND", "lancedb")

    if backend == "lancedb":
        from hermes_bedrock_agent.vector_store.lancedb_store import LanceDBStore

        return LanceDBStore(
            db_path=kwargs.get("db_path", ""),
            collection=kwargs.get("collection", ""),
            distance=kwargs.get("distance", "cosine"),
            rrf_k=kwargs.get("rrf_k", 60),
        ) if kwargs.get("db_path") else LanceDBStore()

    elif backend == "opensearch":
        from hermes_bedrock_agent.vector_store.opensearch_store import OpenSearchStore

        opensearch_client = kwargs.get("opensearch_client")
        if opensearch_client is None:
            raise ValueError(
                "opensearch_client is required when backend='opensearch'. "
                "Pass an OpenSearchClient instance."
            )
        return OpenSearchStore(
            opensearch_client,
            index_name=kwargs.get("index_name", "enterprise-graphrag"),
            vector_field=kwargs.get("vector_field", "embedding"),
            text_field=kwargs.get("text_field", "text"),
        )

    else:
        raise ValueError(
            f"Unknown vector store backend: '{backend}'. "
            f"Supported: 'lancedb', 'opensearch'"
        )


__all__ = [
    "VectorStoreBackend",
    "VectorStoreRecord",
    "VectorSearchResult",
    "LanceDBStore",
    "OpenSearchStore",
    "create_vector_store",
]
