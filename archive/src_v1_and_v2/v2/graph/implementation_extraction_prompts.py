"""
Implementation Extraction Prompts for Stage 06.

Provides schema-constrained prompt templates for implementation graph extraction.
Used by implementation_graph_builder.py for LLM-based extraction (when available).

These prompts enforce:
- Only allowed Implementation Graph labels
- Only allowed Implementation relation types
- Evidence linking requirements
- JSON output format
"""

from __future__ import annotations

# Allowed Implementation Graph node labels
IMPLEMENTATION_LABELS = [
    "System",
    "Module",
    "API",
    "Service",
    "Class",
    "Method",
    "Table",
    "Column",
    "SQL",
    "Job",
    "File",
    "ExternalSystem",
    "Config",
    "Message",
    "ErrorCode",
    "Document",
    "EvidenceChunk",
]

# Allowed Implementation Graph relation types
IMPLEMENTATION_RELATIONS = [
    "BELONGS_TO",
    "CONTAINS",
    "IMPLEMENTS",
    "USES",
    "CALLS",
    "READS",
    "WRITES",
    "MAPS_TO",
    "DEPENDS_ON",
    "TRIGGERS",
    "VALIDATES",
    "HAS_FIELD",
    "HAS_API",
    "HAS_METHOD",
    "HAS_TABLE",
    "HAS_COLUMN",
    "HAS_ERROR",
    "HAS_EVIDENCE",
    "MENTIONED_IN",
    "RELATED_TO",
]


SYSTEM_PROMPT = """You are an enterprise implementation knowledge graph extraction expert.
Your job is to extract implementation-level entities (systems, APIs, tables, code, etc.)
from enterprise technical documents, source code, SQL, and configuration files.

You must follow these rules strictly:
1. Only use allowed node labels: {labels}
2. Only use allowed relation types: {relations}
3. Every node and edge must include evidence_chunk_ids (the chunk ID from the input)
4. Every node and edge must include source_ids (the document ID from the input)
5. Every node must include confidence (0.0 to 1.0)
6. Preserve exact technical names (table names, class names, method names, file paths)
7. Do NOT extract generic words like "data", "system", "file" unless they are specific named entities
8. Do NOT invent implementation objects not present in the evidence
9. Do NOT extract business process concepts (those belong to the Business Semantic Graph)

Output must be a JSON object with:
  nodes: []
  edges: []
  rejected_items: []
""".format(
    labels=", ".join(IMPLEMENTATION_LABELS),
    relations=", ".join(IMPLEMENTATION_RELATIONS),
)


EXTRACTION_PROMPT_TEMPLATE = """Extract implementation-level entities and relationships from the following evidence chunks.

## Allowed Node Labels
{labels}

## Allowed Relation Types
{relations}

## Input Evidence Chunks
{chunks_json}

## Instructions
- Extract System, Module, Service, Class, Method, Table, Column, File, Config, API, Job, etc.
- Use exact names from the source (table names, class names, method names, file paths)
- Each node needs: node_id (generated), label, name, display_name, layer="implementation",
  source_ids, evidence_chunk_ids, confidence
- Each edge needs: edge_id (generated), source_node_id, target_node_id, relation_type,
  layer="implementation", source_ids, evidence_chunk_ids, confidence
- Reject items that don't fit any allowed label or relation

## Output Format (JSON)
{{
  "nodes": [
    {{
      "label": "Table",
      "name": "payment_req",
      "display_name": "PAYMENT_REQ",
      "aliases": [],
      "description": "Payment request table",
      "confidence": 0.95,
      "evidence_chunk_ids": ["chunk_id_here"],
      "source_ids": ["doc_id_here"]
    }}
  ],
  "edges": [
    {{
      "source_label": "Class",
      "source_name": "PaymentReqAction",
      "target_label": "Table",
      "target_name": "PAYMENT_REQ",
      "relation_type": "READS",
      "confidence": 0.85,
      "evidence_chunk_ids": ["chunk_id_here"],
      "source_ids": ["doc_id_here"]
    }}
  ],
  "rejected_items": []
}}
"""


def build_extraction_prompt(
    chunks: list[dict],
    max_text_length: int = 2000,
) -> str:
    """Build extraction prompt from a batch of evidence chunks."""
    import json

    # Prepare chunk summaries for the prompt
    chunk_summaries = []
    for chunk in chunks:
        summary = {
            "chunk_id": chunk.get("chunk_id", ""),
            "document_id": chunk.get("document_id", ""),
            "source_path": chunk.get("source_path", ""),
            "chunk_type": chunk.get("chunk_type", ""),
            "text": chunk.get("text", "")[:max_text_length],
        }
        chunk_summaries.append(summary)

    return EXTRACTION_PROMPT_TEMPLATE.format(
        labels="\n".join(f"- {l}" for l in IMPLEMENTATION_LABELS),
        relations="\n".join(f"- {r}" for r in IMPLEMENTATION_RELATIONS),
        chunks_json=json.dumps(chunk_summaries, ensure_ascii=False, indent=2),
    )
