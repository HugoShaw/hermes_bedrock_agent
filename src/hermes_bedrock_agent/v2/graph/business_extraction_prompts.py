"""
Business Extraction Prompts for Stage 05.

Provides schema-constrained prompt templates for business graph extraction.
Used by business_graph_builder.py for LLM-based extraction (when available).

Also provides deterministic heuristic extraction as a fallback.
"""

from __future__ import annotations

# ============================================================================
# Schema Constraints (embedded in prompts)
# ============================================================================

ALLOWED_NODE_LABELS = [
    "Project",
    "BusinessDomain",
    "BusinessProcess",
    "BusinessStep",
    "BusinessRule",
    "BusinessTerm",
    "Function",
    "Screen",
    "Role",
    "Organization",
    "Document",
    "EvidenceChunk",
]

ALLOWED_RELATION_TYPES = [
    "BELONGS_TO",
    "CONTAINS",
    "HAS_STEP",
    "NEXT_STEP",
    "HAS_RULE",
    "HAS_TERM",
    "HAS_FUNCTION",
    "VALIDATES",
    "USES",
    "DEPENDS_ON",
    "HAS_EVIDENCE",
    "MENTIONED_IN",
    "RELATED_TO",
]

# ============================================================================
# LLM Extraction Prompt
# ============================================================================

BUSINESS_EXTRACTION_SYSTEM_PROMPT = """You are an enterprise business knowledge graph extractor.
You analyze enterprise documents and extract structured business knowledge entities and relationships.

RULES:
1. Extract ONLY business-readable entities. Do not extract implementation details (code, APIs, tables, classes).
2. Use the EXACT allowed labels and relation types below. Do NOT invent new ones.
3. Prefer Japanese business names if the source text is Japanese.
4. Use display_name as a human-readable business name.
5. Add aliases when Chinese/English/Japanese variants appear in the text.
6. Do NOT extract generic low-value terms like "system", "data", "process", "user" UNLESS they are part of a specific named business concept (e.g., "支払申請システム" is OK, but bare "システム" is NOT).
7. Do NOT invent entities not supported by the evidence text.
8. Every node MUST include the evidence_chunk_ids that support it.
9. Every edge MUST include the evidence_chunk_ids that support it.
10. Assign confidence: 1.0 for explicitly stated facts, 0.8 for strongly implied, 0.6 for inferred.
11. If you cannot extract any meaningful entities, return empty arrays.

ALLOWED NODE LABELS:
{node_labels}

ALLOWED RELATION TYPES:
{relation_types}

OUTPUT FORMAT (JSON):
{{
  "nodes": [
    {{
      "label": "...",
      "name": "canonical lowercase name",
      "display_name": "Human Readable Name",
      "aliases": ["alias1", "alias2"],
      "description": "brief description",
      "confidence": 0.8,
      "evidence_chunk_ids": ["chunk_id_1"]
    }}
  ],
  "edges": [
    {{
      "source_name": "canonical name of source node",
      "source_label": "SourceLabel",
      "target_name": "canonical name of target node",
      "target_label": "TargetLabel",
      "relation_type": "RELATION_TYPE",
      "description": "brief description",
      "confidence": 0.8,
      "evidence_chunk_ids": ["chunk_id_1"]
    }}
  ],
  "rejected_items": [
    {{
      "type": "node|edge",
      "reason": "why rejected",
      "raw": "original text snippet"
    }}
  ]
}}
"""

BUSINESS_EXTRACTION_USER_PROMPT = """Extract business knowledge graph entities and relationships from the following evidence chunks.

Evidence chunks:
---
{evidence_text}
---

Extract business-level entities (domains, processes, steps, rules, terms, functions, screens, roles, organizations) and their relationships.

Remember:
- Only use allowed labels: {node_labels}
- Only use allowed relation types: {relation_types}
- Include evidence_chunk_ids for every node and edge
- Do not extract implementation-level entities (code, APIs, tables)
- Assign appropriate confidence scores

Return your result as a JSON object with "nodes", "edges", and "rejected_items" arrays."""


def format_extraction_prompt(
    evidence_chunks: list[dict],
    *,
    max_text_length: int = 8000,
) -> tuple[str, str]:
    """Format the extraction prompt with evidence chunks.

    Returns:
        (system_prompt, user_prompt)
    """
    # Build evidence text
    evidence_parts = []
    total_length = 0
    for chunk in evidence_chunks:
        chunk_text = (
            f"[chunk_id: {chunk['chunk_id']}]\n"
            f"[source: {chunk.get('source_path', 'unknown')}]\n"
            f"[type: {chunk.get('chunk_type', 'unknown')}]\n"
            f"{chunk['text']}\n"
        )
        if total_length + len(chunk_text) > max_text_length:
            break
        evidence_parts.append(chunk_text)
        total_length += len(chunk_text)

    evidence_text = "\n---\n".join(evidence_parts)

    node_labels_str = ", ".join(ALLOWED_NODE_LABELS)
    relation_types_str = ", ".join(ALLOWED_RELATION_TYPES)

    system_prompt = BUSINESS_EXTRACTION_SYSTEM_PROMPT.format(
        node_labels=node_labels_str,
        relation_types=relation_types_str,
    )

    user_prompt = BUSINESS_EXTRACTION_USER_PROMPT.format(
        evidence_text=evidence_text,
        node_labels=node_labels_str,
        relation_types=relation_types_str,
    )

    return system_prompt, user_prompt
