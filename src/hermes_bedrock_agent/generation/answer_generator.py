"""Answer generator — produces final answers from fused context via Bedrock Claude.

Provides:
- AnswerGenerator: generates answers using bedrock_client
- MockAnswerGenerator: deterministic mock for testing
- Does NOT access OpenSearch or Neptune directly
- Only receives FusedContext (pre-built by retrieval pipeline)
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.generation.prompts import (
    build_answer_prompt,
    get_prompt_version,
)
from hermes_bedrock_agent.retrieval.context_builder import ContextBuilder
from hermes_bedrock_agent.schemas.retrieval import (
    AnswerResult,
    Citation,
    FusedContext,
    RetrievalSource,
)

logger = get_logger(__name__)


class AnswerGeneratorConfig:
    """Configuration for answer generation."""

    def __init__(
        self,
        *,
        model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        mock_mode: bool = False,
    ):
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.mock_mode = mock_mode


class AnswerGenerator:
    """Generates answers from FusedContext using Bedrock Claude.

    Does NOT access OpenSearch or Neptune. Only receives pre-built
    FusedContext from the retrieval pipeline.

    Uses clients/bedrock_client.py via dependency injection.
    """

    def __init__(
        self,
        bedrock_client=None,
        config: Optional[AnswerGeneratorConfig] = None,
        context_builder: Optional[ContextBuilder] = None,
    ):
        """Initialize answer generator.

        Args:
            bedrock_client: Instance of BedrockRuntimeClient from clients/.
                           Can be None if mock_mode=True.
            config: Generation configuration.
            context_builder: ContextBuilder instance (created if None).
        """
        self._client = bedrock_client
        self.config = config or AnswerGeneratorConfig()
        self._context_builder = context_builder or ContextBuilder()

    def generate_answer(
        self,
        question: str,
        fused_context: FusedContext,
    ) -> AnswerResult:
        """Generate an answer from fused retrieval context.

        Args:
            question: Original user question.
            fused_context: Merged evidence from fusion stage.

        Returns:
            AnswerResult with generated answer, citations, and metadata.
        """
        start_time = time.time()

        # Build structured context string
        context_str = self._context_builder.build_context(fused_context)

        # Build prompts
        system_prompt, user_prompt = build_answer_prompt(question, context_str)

        # Generate answer
        if self.config.mock_mode:
            answer_text = self._mock_generate(question, fused_context)
        else:
            answer_text = self._invoke_llm(system_prompt, user_prompt)

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Extract citations from answer
        citations = self._extract_citations(answer_text, fused_context)

        # Estimate context tokens
        context_tokens = len(context_str) // 3

        # Collect all used chunk_ids (text + graph source_chunk_ids)
        used_chunk_ids = [ev.chunk_id for ev in fused_context.text_evidence if ev.chunk_id]
        for gev in fused_context.graph_evidence:
            used_chunk_ids.extend(gev.source_chunk_ids)
        used_chunk_ids = sorted(set(used_chunk_ids))

        # Collect graph paths
        used_graph_paths = [
            gev.path_description for gev in fused_context.graph_evidence
            if gev.path_description
        ]

        # Detect insufficient evidence
        insufficient = (not fused_context.text_evidence and not fused_context.graph_evidence)

        return AnswerResult(
            query=question,
            answer=answer_text,
            confidence=self._estimate_confidence(fused_context, citations),
            citations=citations,
            context_token_count=context_tokens,
            text_evidence_used=len(fused_context.text_evidence),
            graph_evidence_used=len(fused_context.graph_evidence),
            used_chunk_ids=used_chunk_ids,
            used_graph_paths=used_graph_paths,
            insufficient_evidence=insufficient,
            model_name=self.config.model_id,
            prompt_template=get_prompt_version(),
            generation_time_ms=elapsed_ms,
        )

    def _invoke_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Invoke Bedrock Claude for answer generation."""
        if not self._client:
            raise RuntimeError("bedrock_client required when mock_mode=False")

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
        }

        try:
            response = self._client.invoke_model(
                model_id=self.config.model_id,
                body=body,
            )

            # Parse Claude response
            if isinstance(response, dict):
                content = response.get("content", [])
                if isinstance(content, list) and content:
                    return content[0].get("text", "")
                return response.get("text", str(response))
            return str(response)

        except Exception as e:
            logger.error(f"LLM invocation failed: {e}")
            return f"回答生成に失敗しました。エラー: {str(e)}"

    def _mock_generate(self, question: str, fused: FusedContext) -> str:
        """Generate deterministic mock answer for testing."""
        parts = [f"Based on the available evidence regarding: {question}\n"]

        if fused.text_evidence:
            parts.append("From text sources:")
            for i, ev in enumerate(fused.text_evidence[:3]):
                parts.append(f"  [T{i + 1}] {ev.content[:100]}")

        if fused.graph_evidence:
            parts.append("\nFrom graph analysis:")
            for i, ev in enumerate(fused.graph_evidence[:3]):
                parts.append(f"  [G{i + 1}] {ev.content[:100]}")

        if not fused.text_evidence and not fused.graph_evidence:
            parts.append("No relevant evidence found. Further confirmation is needed.")

        return "\n".join(parts)

    def _extract_citations(
        self,
        answer_text: str,
        fused: FusedContext,
    ) -> list[Citation]:
        """Extract citation references from generated answer text."""
        citations: list[Citation] = []

        # Find [T1], [T2], etc. references
        import re

        text_refs = re.findall(r"\[T(\d+)\]", answer_text)
        for ref in text_refs:
            idx = int(ref) - 1
            if 0 <= idx < len(fused.text_evidence):
                ev = fused.text_evidence[idx]
                cid = hashlib.sha256(
                    f"cite_{ev.evidence_id}".encode()
                ).hexdigest()[:12]
                citations.append(Citation(
                    citation_id=f"cite_{cid}",
                    evidence_id=ev.evidence_id,
                    source_uri=ev.source_uri,
                    document_id=ev.document_id,
                    chunk_id=ev.chunk_id,
                    page=ev.page,
                    section_title=ev.section_title,
                    citation_type=ev.source,
                ))

        # Find [G1], [G2], etc. references
        graph_refs = re.findall(r"\[G(\d+)\]", answer_text)
        for ref in graph_refs:
            idx = int(ref) - 1
            if 0 <= idx < len(fused.graph_evidence):
                ev = fused.graph_evidence[idx]
                cid = hashlib.sha256(
                    f"cite_{ev.evidence_id}".encode()
                ).hexdigest()[:12]
                chunk_id = ev.source_chunk_ids[0] if ev.source_chunk_ids else ""
                citations.append(Citation(
                    citation_id=f"cite_{cid}",
                    evidence_id=ev.evidence_id,
                    chunk_id=chunk_id,
                    citation_type=RetrievalSource.NEPTUNE_GRAPH,
                ))

        return citations

    def _estimate_confidence(
        self,
        fused: FusedContext,
        citations: list[Citation],
    ) -> float:
        """Estimate answer confidence based on evidence quality."""
        if not fused.text_evidence and not fused.graph_evidence:
            return 0.0

        # Base confidence from evidence count
        evidence_count = fused.total_evidence_count
        count_score = min(evidence_count / 5.0, 1.0) * 0.4

        # Citation coverage score
        citation_score = min(len(citations) / 3.0, 1.0) * 0.3

        # Average evidence score
        all_scores = [ev.score for ev in fused.text_evidence]
        all_scores.extend(ev.score for ev in fused.graph_evidence)
        avg_score = (sum(all_scores) / len(all_scores)) if all_scores else 0.0
        quality_score = avg_score * 0.3

        return min(count_score + citation_score + quality_score, 1.0)
