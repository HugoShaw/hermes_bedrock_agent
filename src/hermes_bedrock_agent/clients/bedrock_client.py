"""Low-level Bedrock Runtime client wrapper.

This module provides ONLY the transport-level interface to AWS Bedrock Runtime.
It handles:
- boto3 session/client creation
- invoke_model (text & multimodal)
- converse API
- Error wrapping

Business logic (embedding, VLM parsing, graph extraction, answer generation)
belongs in their respective modules, NOT here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.configs.settings import LLMSettings, get_settings

logger = get_logger(__name__)


class BedrockRuntimeClient:
    """Low-level wrapper around AWS Bedrock Runtime API.

    Handles connection management and raw model invocation.
    Does NOT contain any business logic — callers compose the request
    body and interpret the response according to their domain.
    """

    def __init__(
        self,
        region: Optional[str] = None,
        boto_client: Optional[Any] = None,
    ) -> None:
        """Initialize Bedrock Runtime client.

        Args:
            region: AWS region. If None, read from settings.
            boto_client: Optional pre-built boto3 client (for testing/mocking).
        """
        self._region = region or get_settings().aws.region
        self._provided_client = boto_client
        self._client: Optional[Any] = boto_client

    @property
    def client(self) -> Any:
        """Lazily create boto3 bedrock-runtime client."""
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def invoke_model(
        self,
        model_id: str,
        body: dict[str, Any],
        content_type: str = "application/json",
        accept: str = "application/json",
    ) -> dict[str, Any]:
        """Invoke a model and return the parsed JSON response.

        Args:
            model_id: Bedrock model ID (e.g. 'anthropic.claude-sonnet-4-20250514').
            body: Request body dict (will be JSON-serialized).
            content_type: Request content type.
            accept: Response accept type.

        Returns:
            Parsed JSON response body.

        Raises:
            BedrockClientError: On AWS API errors.
        """
        try:
            response = self.client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType=content_type,
                accept=accept,
            )
            response_body = response["body"].read()
            return json.loads(response_body)
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(exc))
            logger.error("Bedrock invoke_model failed [%s]: %s (model=%s)", code, message, model_id)
            raise BedrockClientError(f"Bedrock [{code}]: {message}", code=code) from exc
        except BotoCoreError as exc:
            logger.error("Bedrock SDK error: %s", exc)
            raise BedrockClientError(f"AWS SDK error: {exc}") from exc

    def invoke_model_stream(
        self,
        model_id: str,
        body: dict[str, Any],
        content_type: str = "application/json",
        accept: str = "application/json",
    ) -> Any:
        """Invoke a model with streaming response.

        Args:
            model_id: Bedrock model ID.
            body: Request body dict.
            content_type: Request content type.
            accept: Response accept type.

        Returns:
            Raw streaming response (EventStream). Caller must iterate.

        Raises:
            BedrockClientError: On AWS API errors.
        """
        try:
            response = self.client.invoke_model_with_response_stream(
                modelId=model_id,
                body=json.dumps(body),
                contentType=content_type,
                accept=accept,
            )
            return response.get("body")
        except (ClientError, BotoCoreError) as exc:
            logger.error("Bedrock stream invoke failed: %s", exc)
            raise BedrockClientError(f"Bedrock stream error: {exc}") from exc

    def converse(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        system: Optional[list[dict[str, Any]]] = None,
        inference_config: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Call the Bedrock Converse API (messages-style).

        Args:
            model_id: Bedrock model ID.
            messages: List of message dicts with role/content.
            system: Optional system prompt blocks.
            inference_config: Optional inference parameters (maxTokens, temperature, etc.)

        Returns:
            Full converse response dict.

        Raises:
            BedrockClientError: On AWS API errors.
        """
        try:
            kwargs: dict[str, Any] = {
                "modelId": model_id,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system
            if inference_config:
                kwargs["inferenceConfig"] = inference_config

            response = self.client.converse(**kwargs)
            return response
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(exc))
            logger.error("Bedrock converse failed [%s]: %s", code, message)
            raise BedrockClientError(f"Bedrock converse [{code}]: {message}", code=code) from exc
        except BotoCoreError as exc:
            logger.error("Bedrock converse SDK error: %s", exc)
            raise BedrockClientError(f"AWS SDK error: {exc}") from exc

    def is_available(self) -> bool:
        """Check if the Bedrock Runtime service is reachable."""
        try:
            # Light-weight call — list foundation models (first page only)
            bedrock_client = boto3.client("bedrock", region_name=self._region)
            bedrock_client.list_foundation_models(maxResults=1)
            return True
        except Exception:
            return False


class BedrockClientError(Exception):
    """Raised when a Bedrock API call fails."""

    def __init__(self, message: str, code: str = "Unknown") -> None:
        super().__init__(message)
        self.code = code


def get_bedrock_client(region: Optional[str] = None) -> BedrockRuntimeClient:
    """Factory function to create a BedrockRuntimeClient instance.

    Convenience wrapper for embedder and other modules that need
    a ready-to-use Bedrock client without managing configuration.

    Args:
        region: AWS region override. Uses settings default if None.

    Returns:
        Configured BedrockRuntimeClient instance.
    """
    return BedrockRuntimeClient(region=region)
