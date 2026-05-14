"""Low-level OpenSearch client wrapper.

Handles connection, index management, bulk loading, and search operations.
Does NOT contain retrieval ranking logic, fusion, or query interpretation.

Note: opensearch-py is an optional dependency. This module degrades gracefully
if not installed (raises ImportError on instantiation).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.configs.settings import OpenSearchSettings, get_settings

logger = get_logger(__name__)


class OpenSearchClient:
    """Low-level OpenSearch operations — index, bulk, search.

    Supports both OpenSearch Serverless (AOSS) and managed OpenSearch domains.
    Uses AWS SigV4 authentication by default.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        index_name: Optional[str] = None,
        region: Optional[str] = None,
        use_serverless: Optional[bool] = None,
        os_client: Optional[Any] = None,
    ) -> None:
        """Initialize OpenSearch client.

        Args:
            endpoint: OpenSearch endpoint URL. If None, read from settings.
            index_name: Default index name. If None, read from settings.
            region: AWS region. If None, read from settings.
            use_serverless: Whether endpoint is AOSS. If None, read from settings.
            os_client: Optional pre-built OpenSearch client (for testing/mocking).
        """
        settings = get_settings().opensearch
        self._endpoint = endpoint or settings.endpoint
        self._index_name = index_name or settings.index_name
        self._region = region or settings.region
        self._use_serverless = use_serverless if use_serverless is not None else settings.use_serverless
        self._provided_client = os_client
        self._client: Optional[Any] = os_client

    @property
    def client(self) -> Any:
        """Lazily create OpenSearch client with SigV4 auth."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def index_name(self) -> str:
        return self._index_name

    @property
    def is_configured(self) -> bool:
        return bool(self._endpoint)

    def _create_client(self) -> Any:
        """Create OpenSearch client with AWS SigV4 signing."""
        try:
            from opensearchpy import OpenSearch, RequestsHttpConnection
        except ImportError as exc:
            raise ImportError(
                "opensearch-py is required for OpenSearch integration. "
                "Install with: uv pip install opensearch-py"
            ) from exc

        if not self._endpoint:
            raise OpenSearchClientError(
                "OPENSEARCH_ENDPOINT not configured. Set it in .env.",
                code="NotConfigured",
            )

        try:
            import boto3
            from requests_aws4auth import AWS4Auth

            credentials = boto3.Session().get_credentials()
            service = "aoss" if self._use_serverless else "es"
            auth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                self._region,
                service,
                session_token=credentials.token,
            )
        except ImportError:
            # Fall back to no auth (for local OpenSearch / testing)
            auth = None

        # Strip protocol if present for host parsing
        host = self._endpoint.replace("https://", "").replace("http://", "").rstrip("/")

        return OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=30,
        )

    def create_index(
        self,
        index_name: Optional[str] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create an index with the given settings/mappings.

        Args:
            index_name: Index name (defaults to self.index_name).
            body: Index settings and mappings dict.

        Returns:
            OpenSearch create index response.

        Raises:
            OpenSearchClientError: On failure.
        """
        name = index_name or self._index_name
        try:
            if self.client.indices.exists(index=name):
                logger.info("Index '%s' already exists", name)
                return {"acknowledged": True, "already_exists": True}
            response = self.client.indices.create(index=name, body=body or {})
            logger.info("Created index '%s'", name)
            return response
        except Exception as exc:
            raise OpenSearchClientError(f"Failed to create index '{name}': {exc}") from exc

    def bulk_index(
        self,
        documents: list[dict[str, Any]],
        index_name: Optional[str] = None,
        id_field: str = "chunk_id",
    ) -> dict[str, Any]:
        """Bulk index documents.

        Args:
            documents: List of document dicts to index.
            index_name: Target index (defaults to self.index_name).
            id_field: Field to use as document _id.

        Returns:
            Bulk response summary with success/error counts.

        Raises:
            OpenSearchClientError: On bulk failure.
        """
        name = index_name or self._index_name
        try:
            from opensearchpy.helpers import bulk

            actions = []
            for doc in documents:
                action = {
                    "_index": name,
                    "_id": doc.get(id_field, ""),
                    "_source": doc,
                }
                actions.append(action)

            success, errors = bulk(self.client, actions, raise_on_error=False)
            result = {"success_count": success, "error_count": len(errors) if errors else 0}
            if errors:
                result["errors"] = errors[:5]  # Only first 5 for logging
                logger.warning("Bulk index had %d errors", len(errors))
            return result
        except Exception as exc:
            raise OpenSearchClientError(f"Bulk index failed: {exc}") from exc

    def search(
        self,
        query_body: dict[str, Any],
        index_name: Optional[str] = None,
        size: int = 10,
    ) -> dict[str, Any]:
        """Execute a search query.

        Args:
            query_body: OpenSearch query DSL body.
            index_name: Index to search (defaults to self.index_name).
            size: Maximum results to return.

        Returns:
            OpenSearch search response.

        Raises:
            OpenSearchClientError: On search failure.
        """
        name = index_name or self._index_name
        try:
            response = self.client.search(
                index=name,
                body=query_body,
                size=size,
            )
            return response
        except Exception as exc:
            raise OpenSearchClientError(f"Search failed: {exc}") from exc

    def knn_search(
        self,
        vector: list[float],
        field: str = "vector",
        k: int = 10,
        index_name: Optional[str] = None,
        filter_query: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a k-NN vector search.

        Args:
            vector: Query embedding vector.
            field: Vector field name in the index.
            k: Number of nearest neighbors to return.
            index_name: Index to search.
            filter_query: Optional filter to apply alongside kNN.

        Returns:
            OpenSearch search response with scored hits.

        Raises:
            OpenSearchClientError: On search failure.
        """
        name = index_name or self._index_name
        knn_query: dict[str, Any] = {
            "knn": {
                field: {
                    "vector": vector,
                    "k": k,
                }
            }
        }
        if filter_query:
            knn_query["knn"][field]["filter"] = filter_query

        body = {"query": knn_query, "size": k}
        return self.search(body, index_name=name, size=k)

    def delete_index(self, index_name: Optional[str] = None) -> dict[str, Any]:
        """Delete an index.

        Args:
            index_name: Index to delete (defaults to self.index_name).

        Returns:
            Delete response.
        """
        name = index_name or self._index_name
        try:
            if not self.client.indices.exists(index=name):
                return {"acknowledged": True, "not_found": True}
            return self.client.indices.delete(index=name)
        except Exception as exc:
            raise OpenSearchClientError(f"Delete index failed: {exc}") from exc

    def ping(self) -> bool:
        """Check if OpenSearch is reachable."""
        if not self.is_configured:
            return False
        try:
            return self.client.ping()
        except Exception:
            return False


class OpenSearchClientError(Exception):
    """Raised when an OpenSearch operation fails."""

    def __init__(self, message: str, code: str = "Unknown") -> None:
        super().__init__(message)
        self.code = code
