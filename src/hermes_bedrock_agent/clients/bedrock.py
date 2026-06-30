"""Bedrock Converse API wrapper — text and multimodal (VLM)."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

# Thread-based timeout to guard against Bedrock converse() hanging indefinitely.
# botocore read_timeout can fail to fire in ap-northeast-1 with large payloads.
# SIGALRM cannot interrupt C-level blocking socket reads in urllib3, so we use
# concurrent.futures to abandon stuck threads instead.
_CONVERSE_TIMEOUT_SEC = 180


class _ConverseTimeout(Exception):
    """Raised when a converse() call exceeds the thread-based deadline."""


# Single-thread pool — we reuse it across calls but each call gets a fresh future.
# daemon=True ensures abandoned threads don't block process exit.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="converse_timeout")


def _converse_with_timeout(client, **kwargs):
    """Wrap client.converse() with a thread-based timeout and one retry.

    Uses concurrent.futures to submit the call to a background thread.
    If the thread doesn't return within _CONVERSE_TIMEOUT_SEC, we abandon it
    (the thread may eventually complete or be killed at process exit).
    """
    for attempt in range(2):
        future = _executor.submit(client.converse, **kwargs)
        try:
            response = future.result(timeout=_CONVERSE_TIMEOUT_SEC)
            return response
        except FuturesTimeoutError:
            future.cancel()  # best-effort; thread may still be blocked
            logger.warning(
                "converse() timed out after %ds (attempt %d/2) — thread abandoned",
                _CONVERSE_TIMEOUT_SEC, attempt + 1,
            )
            if attempt == 1:
                raise _ConverseTimeout(
                    f"converse() exceeded {_CONVERSE_TIMEOUT_SEC}s on both attempts"
                )
    raise _ConverseTimeout("converse() timed out after all retries")


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
    fallback_model_id: Optional[str] = None,
) -> tuple[str, dict]:
    """Text-only Converse call. Returns (response_text, usage_dict)."""
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    inference_config = {"maxTokens": max_tokens, "temperature": temperature}
    try:
        response = _converse_with_timeout(
            client,
            modelId=model_id,
            messages=messages,
            inferenceConfig=inference_config,
        )
    except Exception as primary_err:
        if not fallback_model_id:
            raise
        err_desc = str(primary_err)
        logger.warning(
            "Primary model %s failed (%s), falling back to %s",
            model_id, err_desc, fallback_model_id,
        )
        response = _converse_with_timeout(
            client,
            modelId=fallback_model_id,
            messages=messages,
            inferenceConfig=inference_config,
        )
        logger.info("Fallback model %s succeeded", fallback_model_id)
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
    fallback_model_id: Optional[str] = None,
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

    messages = [{"role": "user", "content": content}]
    inference_config = {"maxTokens": max_tokens, "temperature": temperature}
    try:
        response = _converse_with_timeout(
            client,
            modelId=model_id,
            messages=messages,
            inferenceConfig=inference_config,
        )
    except Exception as primary_err:
        if not fallback_model_id:
            raise
        err_desc = str(primary_err)
        logger.warning(
            "Primary model %s failed (%s), falling back to %s",
            model_id, err_desc, fallback_model_id,
        )
        response = _converse_with_timeout(
            client,
            modelId=fallback_model_id,
            messages=messages,
            inferenceConfig=inference_config,
        )
        logger.info("Fallback model %s succeeded", fallback_model_id)
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
    fallback_model_id: Optional[str] = None,
) -> dict:
    """Full Converse call with system prompt. Returns the raw response dict."""
    kwargs = dict(
        modelId=model_id,
        messages=messages,
        system=system,
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    try:
        return _converse_with_timeout(client, **kwargs)
    except Exception as primary_err:
        if not fallback_model_id:
            raise
        err_desc = str(primary_err)
        logger.warning(
            "Primary model %s failed (%s), falling back to %s",
            model_id, err_desc, fallback_model_id,
        )
        kwargs["modelId"] = fallback_model_id
        response = _converse_with_timeout(client, **kwargs)
        logger.info("Fallback model %s succeeded", fallback_model_id)
        return response


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
