"""Tests for clients/ module — fully mocked, no real AWS calls.

All boto3 clients are mocked. Tests validate:
- Client initialization from settings
- Method signatures and return types
- Error handling and wrapping
- Mock injection support
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from hermes_bedrock_agent.clients.bedrock_client import (
    BedrockClientError,
    BedrockRuntimeClient,
)
from hermes_bedrock_agent.clients.bedrock_kb_client import (
    BedrockKBClient,
    BedrockKBClientError,
    KBRetrievalResult,
)
from hermes_bedrock_agent.clients.neptune_client import (
    NeptuneClient,
    NeptuneClientError,
)
from hermes_bedrock_agent.clients.s3_client import (
    S3Client,
    S3ClientError,
    S3Object,
)


# ---------------------------------------------------------------------------
# BedrockRuntimeClient tests
# ---------------------------------------------------------------------------


class TestBedrockRuntimeClient:
    def _make_client(self) -> tuple[BedrockRuntimeClient, MagicMock]:
        mock_boto = MagicMock()
        client = BedrockRuntimeClient(region="us-east-1", boto_client=mock_boto)
        return client, mock_boto

    def test_init_with_mock(self):
        client, mock_boto = self._make_client()
        assert client.client is mock_boto

    def test_invoke_model_success(self):
        client, mock_boto = self._make_client()
        response_body = json.dumps({"content": [{"text": "Hello!"}]}).encode()
        mock_boto.invoke_model.return_value = {
            "body": BytesIO(response_body),
        }

        result = client.invoke_model(
            model_id="anthropic.claude-sonnet-4-20250514",
            body={"messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]},
        )

        assert result == {"content": [{"text": "Hello!"}]}
        mock_boto.invoke_model.assert_called_once()

    def test_invoke_model_client_error(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        mock_boto.invoke_model.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "InvokeModel",
        )

        with pytest.raises(BedrockClientError) as exc_info:
            client.invoke_model(model_id="test-model", body={})
        assert "ThrottlingException" in str(exc_info.value)
        assert exc_info.value.code == "ThrottlingException"

    def test_invoke_model_stream(self):
        client, mock_boto = self._make_client()
        mock_stream = MagicMock()
        mock_boto.invoke_model_with_response_stream.return_value = {
            "body": mock_stream,
        }

        result = client.invoke_model_stream(
            model_id="test-model",
            body={"messages": []},
        )

        assert result is mock_stream

    def test_converse_success(self):
        client, mock_boto = self._make_client()
        mock_boto.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Response"}]}},
            "stopReason": "end_turn",
        }

        result = client.converse(
            model_id="test-model",
            messages=[{"role": "user", "content": [{"text": "Hello"}]}],
            system=[{"text": "You are helpful"}],
            inference_config={"maxTokens": 1024},
        )

        assert result["stopReason"] == "end_turn"
        mock_boto.converse.assert_called_once()
        call_kwargs = mock_boto.converse.call_args[1]
        assert call_kwargs["modelId"] == "test-model"
        assert call_kwargs["system"] == [{"text": "You are helpful"}]


# ---------------------------------------------------------------------------
# S3Client tests
# ---------------------------------------------------------------------------


class TestS3Client:
    def _make_client(self) -> tuple[S3Client, MagicMock]:
        mock_boto = MagicMock()
        client = S3Client(bucket="test-bucket", region="us-east-1", boto_client=mock_boto)
        return client, mock_boto

    def test_init_with_mock(self):
        client, mock_boto = self._make_client()
        assert client.client is mock_boto
        assert client.bucket == "test-bucket"

    def test_list_objects(self):
        client, mock_boto = self._make_client()
        paginator = MagicMock()
        mock_boto.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "docs/readme.md", "Size": 1024, "LastModified": None, "ETag": '"abc123"'},
                    {"Key": "docs/guide.pdf", "Size": 2048, "LastModified": None, "ETag": '"def456"'},
                    {"Key": "docs/image.png", "Size": 512, "LastModified": None, "ETag": '"ghi789"'},
                    {"Key": "docs/folder/", "Size": 0, "LastModified": None, "ETag": '""'},
                ]
            }
        ]

        objects = client.list_objects(prefix="docs/")
        # Should skip the folder marker
        assert len(objects) == 3
        assert all(isinstance(o, S3Object) for o in objects)
        assert objects[0].uri == "s3://test-bucket/docs/readme.md"
        assert objects[0].extension == ".md"

    def test_list_objects_with_extension_filter(self):
        client, mock_boto = self._make_client()
        paginator = MagicMock()
        mock_boto.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "docs/readme.md", "Size": 1024, "LastModified": None, "ETag": '"abc"'},
                    {"Key": "docs/guide.pdf", "Size": 2048, "LastModified": None, "ETag": '"def"'},
                ]
            }
        ]

        objects = client.list_objects(prefix="docs/", extensions={".pdf"})
        assert len(objects) == 1
        assert objects[0].extension == ".pdf"

    def test_list_objects_max_keys(self):
        client, mock_boto = self._make_client()
        paginator = MagicMock()
        mock_boto.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": f"file_{i}.txt", "Size": 100, "LastModified": None, "ETag": f'"{i}"'}
                    for i in range(10)
                ]
            }
        ]

        objects = client.list_objects(max_keys=3)
        assert len(objects) == 3

    def test_download_bytes(self):
        client, mock_boto = self._make_client()
        mock_body = MagicMock()
        mock_body.read.return_value = b"file content here"
        mock_boto.get_object.return_value = {"Body": mock_body}

        data = client.download_bytes("docs/test.txt")
        assert data == b"file content here"
        mock_boto.get_object.assert_called_once_with(Bucket="test-bucket", Key="docs/test.txt")

    def test_download_bytes_error(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        mock_boto.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )

        with pytest.raises(S3ClientError):
            client.download_bytes("missing/key.txt")

    def test_object_exists_true(self):
        client, mock_boto = self._make_client()
        mock_boto.head_object.return_value = {"ContentLength": 100}
        assert client.object_exists("docs/test.txt") is True

    def test_object_exists_false(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        mock_boto.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not found"}},
            "HeadObject",
        )
        assert client.object_exists("missing.txt") is False

    def test_head_object(self):
        client, mock_boto = self._make_client()
        mock_boto.head_object.return_value = {"ContentLength": 5000, "ContentType": "application/pdf"}
        result = client.head_object("docs/guide.pdf")
        assert result["ContentLength"] == 5000


# ---------------------------------------------------------------------------
# NeptuneClient tests
# ---------------------------------------------------------------------------


class TestNeptuneClient:
    def _make_client(self) -> tuple[NeptuneClient, MagicMock]:
        mock_boto = MagicMock()
        client = NeptuneClient(graph_id="g-test123", region="us-east-1", boto_client=mock_boto)
        return client, mock_boto

    def test_init_with_mock(self):
        client, mock_boto = self._make_client()
        assert client.client is mock_boto
        assert client.graph_id == "g-test123"
        assert client.is_configured is True

    def test_not_configured(self, monkeypatch):
        monkeypatch.delenv("NEPTUNE_GRAPH_ID", raising=False)
        monkeypatch.delenv("NEPTUNE_ANALYTICS_GRAPH_ID", raising=False)
        mock_boto = MagicMock()
        client = NeptuneClient(graph_id="", boto_client=mock_boto)
        assert client.is_configured is False
        with pytest.raises(NeptuneClientError, match="not configured"):
            _ = client.graph_id

    def test_execute_query_success(self):
        client, mock_boto = self._make_client()
        payload_content = json.dumps({"results": [{"n": {"name": "SystemA"}}]}).encode()
        mock_payload = MagicMock()
        mock_payload.read.return_value = payload_content
        mock_boto.execute_query.return_value = {"payload": mock_payload}

        result = client.execute_query(
            "MATCH (n) RETURN n LIMIT 1",
            parameters={"limit": 1},
        )

        assert result == {"results": [{"n": {"name": "SystemA"}}]}
        mock_boto.execute_query.assert_called_once_with(
            graphIdentifier="g-test123",
            queryString="MATCH (n) RETURN n LIMIT 1",
            parameters={"limit": 1},
            language="OPEN_CYPHER",
        )

    def test_execute_query_error(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        mock_boto.execute_query.side_effect = ClientError(
            {"Error": {"Code": "MalformedQueryException", "Message": "Syntax error"}},
            "ExecuteQuery",
        )

        with pytest.raises(NeptuneClientError) as exc_info:
            client.execute_query("INVALID CYPHER")
        assert exc_info.value.code == "MalformedQueryException"

    def test_execute_batch_success(self):
        client, mock_boto = self._make_client()
        payload = MagicMock()
        payload.read.return_value = json.dumps({"results": []}).encode()
        mock_boto.execute_query.return_value = {"payload": payload}

        queries = [
            ("MATCH (n) RETURN count(n)", None),
            ("MATCH ()-[r]->() RETURN count(r)", None),
        ]
        results = client.execute_batch(queries)
        assert len(results) == 2
        assert mock_boto.execute_query.call_count == 2

    def test_execute_batch_stop_on_error(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        mock_boto.execute_query.side_effect = ClientError(
            {"Error": {"Code": "QueryError", "Message": "fail"}},
            "ExecuteQuery",
        )

        queries = [("BAD QUERY", None), ("GOOD QUERY", None)]
        with pytest.raises(NeptuneClientError):
            client.execute_batch(queries, stop_on_error=True)

    def test_execute_batch_continue_on_error(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        payload = MagicMock()
        payload.read.return_value = json.dumps({"results": []}).encode()

        # First call fails, second succeeds
        mock_boto.execute_query.side_effect = [
            ClientError(
                {"Error": {"Code": "QueryError", "Message": "fail"}},
                "ExecuteQuery",
            ),
            {"payload": payload},
        ]

        queries = [("BAD QUERY", None), ("GOOD QUERY", None)]
        results = client.execute_batch(queries, stop_on_error=False)
        assert len(results) == 2
        assert "error" in results[0]
        assert results[1] == {"results": []}

    def test_ping_success(self):
        client, mock_boto = self._make_client()
        payload = MagicMock()
        payload.read.return_value = json.dumps({"results": [{"ping": 1}]}).encode()
        mock_boto.execute_query.return_value = {"payload": payload}
        assert client.ping() is True

    def test_ping_not_configured(self):
        mock_boto = MagicMock()
        client = NeptuneClient(graph_id="", boto_client=mock_boto)
        assert client.ping() is False


# ---------------------------------------------------------------------------
# BedrockKBClient tests
# ---------------------------------------------------------------------------


class TestBedrockKBClient:
    def _make_client(self) -> tuple[BedrockKBClient, MagicMock]:
        mock_boto = MagicMock()
        client = BedrockKBClient(region="us-east-1", boto_client=mock_boto)
        return client, mock_boto

    def test_init_with_mock(self):
        client, mock_boto = self._make_client()
        assert client.client is mock_boto

    def test_retrieve_success(self):
        client, mock_boto = self._make_client()
        mock_boto.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Document chunk about SystemA"},
                    "score": 0.95,
                    "metadata": {"key": "value"},
                    "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                },
                {
                    "content": {"text": "Another relevant chunk"},
                    "score": 0.82,
                    "metadata": {},
                    "location": {},
                },
            ]
        }

        results = client.retrieve(kb_id="KB001", query="What is SystemA?", number_of_results=5)
        assert len(results) == 2
        assert isinstance(results[0], KBRetrievalResult)
        assert results[0].text == "Document chunk about SystemA"
        assert results[0].score == 0.95
        assert results[0].kb_id == "KB001"
        assert results[0].source_uri == "s3://bucket/doc.pdf"

    def test_retrieve_empty_query(self):
        client, _ = self._make_client()
        with pytest.raises(ValueError, match="not be empty"):
            client.retrieve(kb_id="KB001", query="   ")

    def test_retrieve_invalid_count(self):
        client, _ = self._make_client()
        with pytest.raises(ValueError, match="between 1 and 20"):
            client.retrieve(kb_id="KB001", query="test", number_of_results=25)

    def test_retrieve_api_error(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        mock_boto.retrieve.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "KB not found"}},
            "Retrieve",
        )

        with pytest.raises(BedrockKBClientError) as exc_info:
            client.retrieve(kb_id="KB_INVALID", query="test")
        assert exc_info.value.code == "ResourceNotFoundException"

    def test_retrieve_multi_partial_failure(self):
        client, mock_boto = self._make_client()
        from botocore.exceptions import ClientError

        def mock_retrieve(**kwargs):
            kb_id = kwargs["knowledgeBaseId"]
            if kb_id == "KB_BAD":
                raise ClientError(
                    {"Error": {"Code": "Error", "Message": "fail"}},
                    "Retrieve",
                )
            return {
                "retrievalResults": [
                    {"content": {"text": f"Result from {kb_id}"}, "score": 0.9, "metadata": {}, "location": {}},
                ]
            }

        mock_boto.retrieve.side_effect = mock_retrieve

        results = client.retrieve_multi(
            kb_ids=[("KB_GOOD", "Good"), ("KB_BAD", "Bad")],
            query="test query",
        )
        assert len(results["KB_GOOD"]) == 1
        assert len(results["KB_BAD"]) == 0

    def test_retrieve_with_label(self):
        client, mock_boto = self._make_client()
        mock_boto.retrieve.return_value = {
            "retrievalResults": [
                {"content": {"text": "chunk"}, "score": 0.5, "metadata": {}, "location": {}},
            ]
        }

        results = client.retrieve(kb_id="KB001", query="q", kb_label="My KB")
        assert results[0].kb_label == "My KB"
        assert results[0].display_source == "My KB"

    def test_ping_success(self):
        client, mock_boto = self._make_client()
        mock_boto.retrieve.return_value = {"retrievalResults": []}
        assert client.ping("KB001") is True

    def test_ping_failure(self):
        client, mock_boto = self._make_client()
        mock_boto.retrieve.side_effect = Exception("connection error")
        assert client.ping("KB001") is False


# ---------------------------------------------------------------------------
# OpenSearchClient tests (with import guard)
# ---------------------------------------------------------------------------


class TestOpenSearchClient:
    """Test OpenSearch client with fully mocked dependencies."""

    def test_init_with_mock(self):
        """Test that we can pass a pre-built client."""
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        client = OpenSearchClient(
            endpoint="https://search.example.com",
            index_name="test-index",
            os_client=mock_os,
        )
        assert client.client is mock_os
        assert client.index_name == "test-index"
        assert client.is_configured is True

    def test_not_configured(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        client = OpenSearchClient(endpoint="", os_client=MagicMock())
        assert client.is_configured is False

    def test_create_index_already_exists(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        mock_os.indices.exists.return_value = True
        client = OpenSearchClient(endpoint="https://x.com", os_client=mock_os)

        result = client.create_index()
        assert result["already_exists"] is True

    def test_create_index_new(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        mock_os.indices.exists.return_value = False
        mock_os.indices.create.return_value = {"acknowledged": True}
        client = OpenSearchClient(endpoint="https://x.com", index_name="my-idx", os_client=mock_os)

        result = client.create_index(body={"settings": {"number_of_shards": 1}})
        assert result["acknowledged"] is True
        mock_os.indices.create.assert_called_once()

    def test_search(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        mock_os.search.return_value = {
            "hits": {"total": {"value": 2}, "hits": [{"_id": "1"}, {"_id": "2"}]}
        }
        client = OpenSearchClient(endpoint="https://x.com", os_client=mock_os)

        result = client.search(query_body={"query": {"match_all": {}}}, size=5)
        assert result["hits"]["total"]["value"] == 2

    def test_knn_search(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        mock_os.search.return_value = {
            "hits": {"total": {"value": 1}, "hits": [{"_id": "chunk_1", "_score": 0.95}]}
        }
        client = OpenSearchClient(endpoint="https://x.com", os_client=mock_os)

        result = client.knn_search(vector=[0.1] * 1024, k=5)
        assert result["hits"]["total"]["value"] == 1
        # Verify knn query structure was passed
        call_kwargs = mock_os.search.call_args[1]
        body = call_kwargs["body"]
        assert "knn" in body["query"]

    def test_bulk_index(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        client = OpenSearchClient(endpoint="https://x.com", os_client=mock_os)

        # Mock the opensearchpy.helpers.bulk
        with patch("hermes_bedrock_agent.clients.opensearch_client.OpenSearchClient.bulk_index") as mock_bulk:
            mock_bulk.return_value = {"success_count": 3, "error_count": 0}
            docs = [{"chunk_id": f"c{i}", "content": f"text {i}"} for i in range(3)]
            result = client.bulk_index(docs)
            assert result["success_count"] == 3

    def test_ping_configured(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        mock_os.ping.return_value = True
        client = OpenSearchClient(endpoint="https://x.com", os_client=mock_os)
        assert client.ping() is True

    def test_ping_not_configured(self):
        from hermes_bedrock_agent.clients.opensearch_client import OpenSearchClient

        mock_os = MagicMock()
        client = OpenSearchClient(endpoint="", os_client=mock_os)
        assert client.ping() is False
