"""Bedrock Converse API wrapper — text and multimodal (VLM)."""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config


def make_bedrock_client(region: str = "ap-northeast-1") -> Any:
    """Create a bedrock-runtime client with long read timeout for VLM calls."""
    return boto3.client(
        "bedrock-runtime",
        config=Config(
            region_name=region,
            read_timeout=600,
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )


def make_embed_client(region: str = "ap-northeast-1") -> Any:
    """Bedrock-runtime client for embedding calls (default timeout)."""
    return boto3.client("bedrock-runtime", region_name=region)


def converse_text(
    client: Any,
    model_id: str,
    prompt: str,
    max_tokens: int = 12000,
    temperature: float = 0.1,
) -> tuple[str, dict]:
    """Text-only Converse call. Returns (response_text, usage_dict)."""
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    text = "".join(
        block["text"]
        for block in response["output"]["message"]["content"]
        if "text" in block
    )
    return text, response.get("usage", {})


def converse_multimodal(
    client: Any,
    model_id: str,
    images: list[tuple[bytes, str]],
    prompt: str,
    max_tokens: int = 12000,
    temperature: float = 0.1,
) -> tuple[str, dict]:
    """Multimodal Converse call with one or more images.

    images: list of (raw_bytes, media_type) — bytes are sent raw, NOT base64.
    Returns (response_text, usage_dict).
    """
    content: list[dict] = []
    for img_bytes, media_type in images:
        content.append(
            {
                "image": {
                    "format": media_type.split("/")[1],
                    "source": {"bytes": img_bytes},
                }
            }
        )
    content.append({"text": prompt})

    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    text = "".join(
        block["text"]
        for block in response["output"]["message"]["content"]
        if "text" in block
    )
    return text, response.get("usage", {})


def converse_with_system(
    client: Any,
    model_id: str,
    system: list[dict],
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> dict:
    """Full Converse call with system prompt. Returns the raw response dict."""
    return client.converse(
        modelId=model_id,
        messages=messages,
        system=system,
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )


def embed_text(
    client: Any,
    model_id: str,
    text: str,
    dimensions: int = 1024,
) -> list[float]:
    """Call Bedrock Titan Embed V2 and return the embedding vector."""
    body = json.dumps({"inputText": text[:8000], "dimensions": dimensions, "normalize": True})
    response = client.invoke_model(
        modelId=model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]
