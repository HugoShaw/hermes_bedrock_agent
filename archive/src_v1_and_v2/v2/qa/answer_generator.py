"""
V2 Answer Generator — Generates final answers from HybridContext.

Supports two modes:
1. LLM mode: Uses Bedrock Claude (converse API) with budgeted context
2. no-LLM mode: Returns deterministic answer preview (for testing/dry-run)

Includes strict context budgeting to prevent token overflow:
- Limits evidence chunks, graph nodes, graph edges
- Enforces max total context chars
- Filters SQL dump artifacts
- Prefers high-score evidence linked to graph nodes
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.qa.qa_prompts import (
    SYSTEM_PROMPT,
    build_no_llm_answer,
    build_qa_prompt,
)
from hermes_bedrock_agent.v2.schemas.retrieval_schema import HybridContext


# Budget defaults
DEFAULT_MAX_BUSINESS_NODES = 15
DEFAULT_MAX_BUSINESS_EDGES = 20
DEFAULT_MAX_IMPLEMENTATION_NODES = 20
DEFAULT_MAX_IMPLEMENTATION_EDGES = 25
DEFAULT_MAX_EVIDENCE_CHUNKS = 12
DEFAULT_MAX_EVIDENCE_CHARS_PER_CHUNK = 1200
DEFAULT_MAX_TOTAL_CONTEXT_CHARS = 12000
DEFAULT_MIN_EVIDENCE_SCORE = 0.05

# Excluded patterns
SQL_DUMP_PATTERNS = [
    'JOURNAL_BASE20180530',
    'INSERT INTO JOURNAL_BASE',
    'INSERT INTO `JOURNAL_BASE`',
]


class ContextBudget:
    """Controls how much context is sent to the LLM."""

    def __init__(
        self,
        max_business_nodes: int = DEFAULT_MAX_BUSINESS_NODES,
        max_business_edges: int = DEFAULT_MAX_BUSINESS_EDGES,
        max_implementation_nodes: int = DEFAULT_MAX_IMPLEMENTATION_NODES,
        max_implementation_edges: int = DEFAULT_MAX_IMPLEMENTATION_EDGES,
        max_evidence_chunks: int = DEFAULT_MAX_EVIDENCE_CHUNKS,
        max_evidence_chars_per_chunk: int = DEFAULT_MAX_EVIDENCE_CHARS_PER_CHUNK,
        max_total_context_chars: int = DEFAULT_MAX_TOTAL_CONTEXT_CHARS,
        min_evidence_score: float = DEFAULT_MIN_EVIDENCE_SCORE,
    ):
        self.max_business_nodes = max_business_nodes
        self.max_business_edges = max_business_edges
        self.max_implementation_nodes = max_implementation_nodes
        self.max_implementation_edges = max_implementation_edges
        self.max_evidence_chunks = max_evidence_chunks
        self.max_evidence_chars_per_chunk = max_evidence_chars_per_chunk
        self.max_total_context_chars = max_total_context_chars
        self.min_evidence_score = min_evidence_score


def apply_context_budget(
    context: HybridContext,
    budget: ContextBudget | None = None,
) -> HybridContext:
    """Apply context budget — trim and filter the HybridContext before LLM call.

    Returns a new HybridContext with budgeted content. Original is not modified.
    """
    if budget is None:
        budget = ContextBudget()

    # Budget business context
    biz_nodes = [i for i in context.business_context if i.get('type') == 'business_node']
    biz_edges = [i for i in context.business_context if i.get('type') == 'business_edge']
    budgeted_biz = biz_nodes[:budget.max_business_nodes] + biz_edges[:budget.max_business_edges]

    # Budget implementation context
    impl_nodes = [i for i in context.implementation_context if i.get('type') == 'implementation_node']
    impl_edges = [i for i in context.implementation_context if i.get('type') == 'implementation_edge']
    budgeted_impl = impl_nodes[:budget.max_implementation_nodes] + impl_edges[:budget.max_implementation_edges]

    # Budget evidence context — most critical for over-returning queries
    evidence_items = [i for i in context.evidence_context if i.get('type') == 'evidence_chunk']

    # Filter out SQL dump contamination
    evidence_items = _filter_sql_dumps(evidence_items)

    # Filter by minimum score
    evidence_items = [
        i for i in evidence_items
        if i.get('score', 0.0) >= budget.min_evidence_score
    ]

    # Truncate text per chunk
    for item in evidence_items:
        text = item.get('text', '')
        if len(text) > budget.max_evidence_chars_per_chunk:
            item = dict(item)
            item['text'] = text[:budget.max_evidence_chars_per_chunk] + '...'

    # Limit chunk count
    evidence_items = evidence_items[:budget.max_evidence_chunks]

    # Enforce total context char limit
    budgeted_evidence = _enforce_total_chars(
        evidence_items, budget.max_total_context_chars, budgeted_biz, budgeted_impl
    )

    return HybridContext(
        query=context.query,
        business_context=budgeted_biz,
        implementation_context=budgeted_impl,
        evidence_context=budgeted_evidence,
        reasoning_constraints=context.reasoning_constraints,
        metadata=context.metadata,
    )


def _filter_sql_dumps(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove evidence chunks that are SQL dump artifacts."""
    filtered = []
    for item in items:
        text = item.get('text', '')
        title = item.get('title', '')
        source_path = item.get('source_path', '')
        combined = f"{text} {title} {source_path}"

        is_dump = False
        for pattern in SQL_DUMP_PATTERNS:
            if pattern in combined:
                is_dump = True
                break

        if not is_dump:
            filtered.append(item)

    return filtered


def _enforce_total_chars(
    evidence_items: list[dict[str, Any]],
    max_chars: int,
    biz_items: list[dict[str, Any]],
    impl_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enforce total context char budget by trimming evidence if needed."""
    # Estimate current graph context chars
    graph_chars = sum(len(str(i)) for i in biz_items) + sum(len(str(i)) for i in impl_items)
    remaining = max_chars - graph_chars

    if remaining <= 0:
        # Graph context alone exceeds budget — return minimal evidence
        return evidence_items[:2]

    budgeted = []
    total = 0
    for item in evidence_items:
        item_chars = len(str(item))
        if total + item_chars > remaining:
            break
        budgeted.append(item)
        total += item_chars

    return budgeted


class AnswerGeneratorV2:
    """Generates answers from budgeted HybridContext.

    Supports LLM mode (Bedrock Claude) and no-LLM mode (deterministic preview).
    """

    def __init__(
        self,
        model_id: str | None = None,
        region: str = "ap-northeast-1",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        budget: ContextBudget | None = None,
    ):
        self.model_id = model_id or os.getenv('BEDROCK_TEXT_MODEL_ID', 'jp.anthropic.claude-sonnet-4-6')
        self.region = region
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.budget = budget or ContextBudget()
        self._client = None

    def _get_client(self):
        """Lazy-init Bedrock client."""
        if self._client is None:
            try:
                from hermes_bedrock_agent.clients.bedrock_client import BedrockRuntimeClient
                self._client = BedrockRuntimeClient(region=self.region)
            except Exception:
                self._client = None
        return self._client

    def generate_answer(
        self,
        query: str,
        hybrid_context: HybridContext,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        """Generate answer from HybridContext.

        Args:
            query: Original user query.
            hybrid_context: Full HybridContext from retrieval pipeline.
            use_llm: If True, call LLM. If False, return deterministic preview.

        Returns:
            Dict with keys: answer, mode, model, prompt_chars, context_chars,
            warnings, citations, debug.
        """
        # Apply context budget
        budgeted = apply_context_budget(hybrid_context, self.budget)

        # Build prompt
        prompt_text = build_qa_prompt(budgeted)
        prompt_chars = len(prompt_text) + len(SYSTEM_PROMPT)

        # Collect metadata
        biz_nodes = [i for i in budgeted.business_context if i.get('type') == 'business_node']
        biz_edges = [i for i in budgeted.business_context if i.get('type') == 'business_edge']
        impl_nodes = [i for i in budgeted.implementation_context if i.get('type') == 'implementation_node']
        impl_edges = [i for i in budgeted.implementation_context if i.get('type') == 'implementation_edge']
        evi_chunks = [i for i in budgeted.evidence_context if i.get('type') == 'evidence_chunk']

        debug_info = {
            'intent': budgeted.metadata.get('intent', 'unknown'),
            'primary_path': budgeted.metadata.get('primary_path', ''),
            'secondary_paths': budgeted.metadata.get('secondary_paths', []),
            'business_nodes_used': len(biz_nodes),
            'business_edges_used': len(biz_edges),
            'implementation_nodes_used': len(impl_nodes),
            'implementation_edges_used': len(impl_edges),
            'evidence_chunks_used': len(evi_chunks),
            'evidence_chunks_before_budget': hybrid_context.metadata.get('evidence_chunks_matched', 0),
            'context_chars_budgeted': budgeted.total_chars,
            'context_chars_original': hybrid_context.total_chars,
            'prompt_chars': prompt_chars,
        }

        warnings: list[str] = []
        citations: list[dict[str, str]] = []

        # Collect citations from evidence
        for chunk in evi_chunks:
            cid = chunk.get('chunk_id', '')
            src = chunk.get('source_path', '')
            title = chunk.get('title', '')
            if cid or src:
                citations.append({'chunk_id': cid, 'source_path': src, 'title': title})

        # Check for warnings
        for constraint in budgeted.reasoning_constraints:
            if '⚠️' in constraint:
                warnings.append(constraint)

        if not use_llm:
            # No-LLM mode — deterministic preview
            answer = build_no_llm_answer(budgeted)
            return {
                'answer': answer,
                'mode': 'no_llm',
                'model': None,
                'prompt_chars': prompt_chars,
                'context_chars': budgeted.total_chars,
                'warnings': warnings,
                'citations': citations,
                'debug': debug_info,
            }

        # LLM mode — try to call Bedrock
        client = self._get_client()
        if client is None:
            # Fallback to no-LLM
            warnings.append("LLM client unavailable — falling back to no_llm mode.")
            answer = build_no_llm_answer(budgeted)
            return {
                'answer': answer,
                'mode': 'fallback',
                'model': None,
                'prompt_chars': prompt_chars,
                'context_chars': budgeted.total_chars,
                'warnings': warnings,
                'citations': citations,
                'debug': debug_info,
            }

        # Call Bedrock Converse API
        try:
            start = time.time()
            response = client.converse(
                model_id=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": prompt_text}],
                    }
                ],
                system=[{"text": SYSTEM_PROMPT}],
                inference_config={
                    "maxTokens": self.max_tokens,
                    "temperature": self.temperature,
                },
            )
            elapsed = time.time() - start

            # Extract answer text from response
            answer_text = ""
            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])
            for block in content_blocks:
                if "text" in block:
                    answer_text += block["text"]

            debug_info['llm_elapsed_seconds'] = round(elapsed, 2)
            debug_info['llm_usage'] = response.get('usage', {})

            return {
                'answer': answer_text,
                'mode': 'llm',
                'model': self.model_id,
                'prompt_chars': prompt_chars,
                'context_chars': budgeted.total_chars,
                'warnings': warnings,
                'citations': citations,
                'debug': debug_info,
            }

        except Exception as exc:
            # LLM call failed — fallback
            warnings.append(f"LLM call failed: {exc}. Falling back to no_llm mode.")
            answer = build_no_llm_answer(budgeted)
            return {
                'answer': answer,
                'mode': 'fallback',
                'model': self.model_id,
                'prompt_chars': prompt_chars,
                'context_chars': budgeted.total_chars,
                'warnings': warnings,
                'citations': citations,
                'debug': debug_info,
            }
