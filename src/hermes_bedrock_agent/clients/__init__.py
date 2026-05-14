"""AWS client wrappers — Bedrock Runtime, S3, Neptune, OpenSearch, Bedrock KB.

All clients:
- Accept optional pre-built boto3 clients for testing/mocking.
- Read defaults from configs/settings.py.
- Provide only transport-level operations (no business logic).
"""

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

# OpenSearch client has optional dependency — import only on use
# from hermes_bedrock_agent.clients.opensearch_client import (
#     OpenSearchClient,
#     OpenSearchClientError,
# )

__all__ = [
    # Bedrock Runtime
    "BedrockRuntimeClient",
    "BedrockClientError",
    # S3
    "S3Client",
    "S3ClientError",
    "S3Object",
    # Neptune
    "NeptuneClient",
    "NeptuneClientError",
    # Bedrock KB
    "BedrockKBClient",
    "BedrockKBClientError",
    "KBRetrievalResult",
]
