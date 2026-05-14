"""Prompt templates for GraphRAG answer generation.

Contains the system and user prompts used by the answer generator.
All prompts enforce:
- Evidence-only answers (no fabrication)
- Citation requirements (chunk_id, source_uri, page)
- Insufficient evidence acknowledgment
- No source invention
"""

from __future__ import annotations

# ===========================================================================
# System prompt for GraphRAG answer generation
# ===========================================================================

GRAPHRAG_SYSTEM_PROMPT = """You are an enterprise knowledge assistant. Your role is to answer questions based ONLY on the provided evidence.

## Rules

1. ONLY use information from the provided Text Evidence and Graph Context.
2. NEVER fabricate, invent, or hallucinate information not present in the evidence.
3. NEVER invent source URIs, page numbers, or citations that are not in the evidence.
4. For every claim in your answer, cite the evidence reference (e.g. [T1], [G2]).
5. If the evidence is insufficient to fully answer the question, explicitly state:
   "この情報について確認が必要です" (for Japanese) or
   "需要进一步确认" (for Chinese) or
   "Further confirmation is needed for this point" (for English).
6. Prefer specificity over generality — use exact names, IDs, and values from the evidence.
7. When graph paths are provided, describe the relationships clearly.
8. Maintain professional tone appropriate for enterprise documentation.

## Citation Format

- Text evidence: cite as [T1], [T2], etc.
- Graph evidence: cite as [G1], [G2], etc.
- Include source_uri and page when available.

## Answer Structure

1. Direct answer to the question
2. Supporting details with citations
3. Graph relationships (if relevant)
4. Confidence note (if evidence is partial)
"""

# ===========================================================================
# User prompt template
# ===========================================================================

GRAPHRAG_USER_PROMPT_TEMPLATE = """## Question
{question}

{context}

## Instructions
Answer the question above using ONLY the provided evidence.
Cite each claim with evidence references [T1], [G1], etc.
If evidence is insufficient, clearly state what needs further confirmation.
Do not invent information or sources not present above."""

# ===========================================================================
# Minimal prompt (when no evidence is found)
# ===========================================================================

GRAPHRAG_NO_EVIDENCE_PROMPT = """## Question
{question}

## Available Evidence
No relevant evidence was found in the knowledge base for this question.

## Instructions
Inform the user that no relevant information was found.
Suggest what kind of documentation or data might need to be ingested to answer this question.
Do NOT attempt to answer from general knowledge."""

# ===========================================================================
# Helper functions
# ===========================================================================


def build_answer_prompt(
    question: str,
    context: str,
) -> tuple[str, str]:
    """Build system + user prompt pair for answer generation.

    Args:
        question: User's question.
        context: Formatted context from ContextBuilder.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    if not context.strip():
        user_prompt = GRAPHRAG_NO_EVIDENCE_PROMPT.format(question=question)
    else:
        user_prompt = GRAPHRAG_USER_PROMPT_TEMPLATE.format(
            question=question,
            context=context,
        )

    return GRAPHRAG_SYSTEM_PROMPT, user_prompt


def get_system_prompt() -> str:
    """Get the GraphRAG system prompt."""
    return GRAPHRAG_SYSTEM_PROMPT


def get_prompt_version() -> str:
    """Get current prompt template version identifier."""
    return "graphrag_v1.0"
