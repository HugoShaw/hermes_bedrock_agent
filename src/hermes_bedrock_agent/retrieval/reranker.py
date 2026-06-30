"""Bedrock reranker module for post-retrieval relevance scoring."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Optional

import boto3

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class RerankConfig:
    """Reranker configuration, populated from environment variables."""
    enabled: bool = False
    model_id: str = "amazon.rerank-v1:0"
    candidate_k: int = 30
    top_k: int = 5
    fallback_on_error: bool = True
    timeout_seconds: int = 30


@dataclass
class RerankResult:
    """Result of a rerank operation."""
    chunks: list[RetrievedChunk] = field(default_factory=list)
    reranked: bool = False
    error: str = ""
    original_order: list[str] = field(default_factory=list)
    rerank_scores: dict[str, float] = field(default_factory=dict)


def load_rerank_config() -> RerankConfig:
    """Load rerank configuration from environment variables."""
    import os
    return RerankConfig(
        enabled=os.getenv("RERANK_ENABLED", "false").lower() in ("true", "1", "yes"),
        model_id=os.getenv("RERANK_MODEL_ID", "amazon.rerank-v1:0"),
        candidate_k=int(os.getenv("RERANK_CANDIDATE_K", "30")),
        top_k=int(os.getenv("RERANK_TOP_K", "5")),
        fallback_on_error=os.getenv("RERANK_FALLBACK_ON_ERROR", "true").lower() in ("true", "1", "yes"),
        timeout_seconds=int(os.getenv("RERANK_TIMEOUT_SECONDS", "30")),
    )


def rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    rerank_cfg: Optional[RerankConfig] = None,
    cfg: Optional[Config] = None,
) -> RerankResult:
    """Rerank chunks using Bedrock rerank model.

    Args:
        query: The user's original query (normalized is fine)
        chunks: Candidate chunks from hybrid retrieval (pre-sorted by hybrid score)
        rerank_cfg: Reranker configuration. If None, loads from env.
        cfg: App config (for AWS region).

    Returns:
        RerankResult with reranked chunks. If reranking fails and fallback_on_error is True,
        returns original chunks (truncated to top_k) with reranked=False and error message.
    """
    if rerank_cfg is None:
        rerank_cfg = load_rerank_config()
    cfg = cfg or _default_config

    if not rerank_cfg.enabled:
        return RerankResult(
            chunks=chunks[:rerank_cfg.top_k],
            reranked=False,
            original_order=[c.chunk_id for c in chunks[:rerank_cfg.top_k]],
        )

    candidates = chunks[:rerank_cfg.candidate_k]
    if not candidates:
        return RerankResult(chunks=[], reranked=False)

    original_order = [c.chunk_id for c in candidates]

    documents = [c.content for c in candidates]

    request_body = {
        "query": query,
        "documents": documents,
        "top_n": rerank_cfg.top_k,
    }

    def _call_rerank():
        client = boto3.client("bedrock-runtime", region_name=cfg.aws_region)
        response = client.invoke_model(
            modelId=rerank_cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body),
        )
        return json.loads(response["body"].read())

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call_rerank)
            result = future.result(timeout=rerank_cfg.timeout_seconds)
    except FuturesTimeoutError:
        error_msg = "Rerank API call timed out after {}s".format(rerank_cfg.timeout_seconds)
        logger.warning(error_msg)
        if rerank_cfg.fallback_on_error:
            return RerankResult(
                chunks=chunks[:rerank_cfg.top_k],
                reranked=False,
                error=error_msg,
                original_order=original_order,
            )
        raise TimeoutError(error_msg)
    except Exception as exc:
        error_msg = "Rerank API error: {}".format(exc)
        logger.warning(error_msg)
        if rerank_cfg.fallback_on_error:
            return RerankResult(
                chunks=chunks[:rerank_cfg.top_k],
                reranked=False,
                error=error_msg,
                original_order=original_order,
            )
        raise

    reranked_chunks: list[RetrievedChunk] = []
    rerank_scores: dict[str, float] = {}

    for item in result.get("results", []):
        idx = item["index"]
        score = item["relevance_score"]
        if idx < len(candidates):
            chunk = candidates[idx].model_copy(update={"score": round(score, 4)})
            reranked_chunks.append(chunk)
            rerank_scores[chunk.chunk_id] = score

    logger.info(
        "Reranked %d candidates → %d results using %s",
        len(candidates), len(reranked_chunks), rerank_cfg.model_id,
    )

    return RerankResult(
        chunks=reranked_chunks,
        reranked=True,
        original_order=original_order,
        rerank_scores=rerank_scores,
    )
