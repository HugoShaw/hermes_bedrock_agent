"""Multimodal LLM client - supports Bedrock Claude, OpenAI, and local models."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from hermes_bedrock_agent.config import LLMConfig
from hermes_bedrock_agent.s3_graph_etl.llm.base_client import BaseLLMClient

logger = logging.getLogger(__name__)


class BedrockClaudeClient(BaseLLMClient):
    """Bedrock Claude multimodal client."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        if config is None:
            config = LLMConfig.from_env()
        self.config = config
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
        return self._client

    def invoke_text(self, prompt: str, system: str = "") -> str:
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            body["system"] = system

        response = self.client.invoke_model(
            modelId=self.config.text_model_id,
            body=json.dumps(body),
            contentType="application/json",
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]

    def invoke_vision(self, prompt: str, image_bytes: bytes, media_type: str = "image/png") -> str:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": prompt},
        ]}]
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": messages,
        }
        response = self.client.invoke_model(
            modelId=self.config.vision_model_id,
            body=json.dumps(body),
            contentType="application/json",
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]

    def invoke_structured(self, prompt: str, schema: dict[str, Any], system: str = "") -> dict[str, Any]:
        system_msg = (system or "") + "\n\nYou MUST respond with valid JSON only. No markdown, no explanation."
        text = self.invoke_text(prompt + f"\n\nExpected JSON schema: {json.dumps(schema)}", system=system_msg)
        # Try to extract JSON from response
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)


class MockLLMClient(BaseLLMClient):
    """Mock LLM client for dry-run testing."""

    def invoke_text(self, prompt: str, system: str = "") -> str:
        return "[DRY-RUN] LLM text response placeholder"

    def invoke_vision(self, prompt: str, image_bytes: bytes, media_type: str = "image/png") -> str:
        return "[DRY-RUN] LLM vision response placeholder"

    def invoke_structured(self, prompt: str, schema: dict[str, Any], system: str = "") -> dict[str, Any]:
        return {"dry_run": True, "message": "Mock structured output"}


def create_llm_client(config: LLMConfig | None = None, dry_run: bool = False) -> BaseLLMClient:
    """Factory function to create the appropriate LLM client."""
    if dry_run:
        return MockLLMClient()
    if config is None:
        config = LLMConfig.from_env()
    if config.vision_provider == "bedrock":
        return BedrockClaudeClient(config)
    # Future: OpenAI, local model support
    raise ValueError(f"Unsupported LLM provider: {config.vision_provider}")
