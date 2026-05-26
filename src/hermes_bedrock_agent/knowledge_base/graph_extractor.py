"""LLM-based graph extraction from parsed Markdown chunks.

Two-pass extraction using Claude Sonnet:
  Pass 1: Business Semantic Graph — high-level systems, processes, data flows
  Pass 2: Implementation / Evidence Graph — APIs, fields, mappings, rules

Each pass sends the Markdown chunk content to the VLM and receives structured
JSON with nodes and edges. Both are linked back to source chunks and PDF evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Optional

from ..clients.bedrock import converse_text, make_bedrock_client
from ..config import Config, config as _default_config
from .schemas import Chunk, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Prompts for two-pass LLM extraction
# ─────────────────────────────────────────────────────────────────────────────

_BUSINESS_GRAPH_PROMPT = """\
You are a business analyst extracting a Business Semantic Graph from an enterprise integration specification document.

## Input
The following is parsed Markdown from an Excel specification sheet.
- Workbook: {workbook_name}
- Sheet: {sheet_name} (index: {sheet_index})

## Content
{content}

## Task
Extract a Business Semantic Graph containing:
- **Systems**: Enterprise systems mentioned (e.g., SAP, DataSpider, ANDPAD, IntermediateFile)
- **DataFlows**: Directional data flows between systems (which system sends data to which)
- **BusinessProcesses**: High-level business processes described (e.g., 発注登録, 納品一覧取得)
- **Relationships**: How systems connect, which processes trigger which data flows

## Output Format
Return ONLY valid JSON (no markdown fencing):
{{
  "nodes": [
    {{"id": "<unique_id>", "label": "<System|DataFlow|BusinessProcess>", "name": "<display_name>", "description": "<brief description in original language>"}}
  ],
  "edges": [
    {{"from": "<node_id>", "to": "<node_id>", "relationship": "<FLOWS_TO|TRIGGERS|USES|PRODUCES|CONSUMES>", "description": "<brief description>"}}
  ]
}}

Rules:
- Use the ORIGINAL Japanese names for processes and data flows
- System names: use canonical English names (SAP, DataSpider, ANDPAD, IntermediateFile)
- Generate IDs as: label_name (e.g., System_SAP, DataFlow_発注データ連携, BusinessProcess_発注登録)
- Keep the graph focused on business understanding — what happens, not how
- Maximum 15 nodes and 20 edges per sheet
- If the content is just a title page or change history with no business logic, return {{"nodes": [], "edges": []}}
"""

_IMPLEMENTATION_GRAPH_PROMPT = """\
You are a technical analyst extracting an Implementation / Evidence Graph from an enterprise integration specification document.

## Input
The following is parsed Markdown from an Excel specification sheet.
- Workbook: {workbook_name}
- Sheet: {sheet_name} (index: {sheet_index})
- Chunk type: {chunk_type}

## Content
{content}

## Task
Extract an Implementation Graph containing:
- **API**: API endpoints or operations (e.g., 発注作成, 発注変更, GET /orders)
- **Field**: Data fields mentioned in mapping tables (source and target fields)
- **MappingRule**: Field-to-field mapping rules with transformation logic
- **BusinessRule**: Business conditions, validation rules, special handling
- **Table**: Database tables or intermediate files referenced
- **Relationships**: Which fields map to which, which APIs use which fields, which rules apply

## Output Format
Return ONLY valid JSON (no markdown fencing):
{{
  "nodes": [
    {{"id": "<unique_id>", "label": "<API|Field|MappingRule|BusinessRule|Table>", "name": "<display_name>", "properties": {{"<key>": "<value>"}}}}
  ],
  "edges": [
    {{"from": "<node_id>", "to": "<node_id>", "relationship": "<MAPS_TO|CALLS_API|HAS_FIELD|HAS_CONDITION|TRANSFORMS|DEFINED_IN>", "properties": {{"<key>": "<value>"}}}}
  ]
}}

Rules:
- Preserve ORIGINAL Japanese field names and rule descriptions
- Generate IDs as: label_sheetNN_name (e.g., Field_sheet06_発注管理ID, API_sheet06_発注作成)
- For MappingRules: include source_field, target_field, transformation in properties
- For BusinessRules: include the condition text in properties
- For Fields: include source_system and target_system in properties if known
- Maximum 25 nodes and 30 edges per chunk
- If the content has no implementation details, return {{"nodes": [], "edges": []}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM extraction functions
# ─────────────────────────────────────────────────────────────────────────────

def _clean_json_response(text: str) -> str:
    """Strip markdown fencing and extract JSON from LLM response."""
    text = text.strip()
    # Remove ```json ... ``` wrapping
    if text.startswith("```"):
        lines = text.split("\n")
        # Find first and last fence
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    return text


def _safe_node_id(label: str, name: str, sheet_index: int = 0) -> str:
    """Generate a stable, safe node ID."""
    clean = re.sub(r"[^\w\u3000-\u9fff]", "_", name)[:60]
    return f"{label}_sheet{sheet_index:02d}_{clean}"


def _extract_business_graph_llm(
    chunk: Chunk,
    client,
    model_id: str,
    max_content_chars: int = 6000,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Use Claude Sonnet to extract Business Semantic Graph from a chunk."""
    content = chunk.content[:max_content_chars]
    prompt = _BUSINESS_GRAPH_PROMPT.format(
        workbook_name=chunk.workbook_name,
        sheet_name=chunk.sheet_name,
        sheet_index=chunk.sheet_index,
        content=content,
    )

    try:
        response_text, usage = converse_text(client, model_id, prompt, max_tokens=4096, temperature=0.1)
        logger.debug("Business LLM: %d in / %d out tokens", usage.get("inputTokens", 0), usage.get("outputTokens", 0))
    except Exception as exc:
        logger.warning("Business graph LLM call failed for sheet %d: %s", chunk.sheet_index, exc)
        return [], []

    try:
        data = json.loads(_clean_json_response(response_text))
    except json.JSONDecodeError as exc:
        logger.warning("Business graph JSON parse failed for sheet %d: %s", chunk.sheet_index, exc)
        return [], []

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    pdf_path = chunk.source_pdf_s3_path

    for raw_node in data.get("nodes", []):
        node_id = raw_node.get("id", "")
        if not node_id:
            continue
        props = {"description": raw_node.get("description", "")}
        props.update(raw_node.get("properties", {}))
        props["sheet_index"] = chunk.sheet_index
        props["workbook_name"] = chunk.workbook_name
        nodes.append(GraphNode(
            node_id=node_id,
            label=raw_node.get("label", "BusinessProcess"),
            name=raw_node.get("name", node_id),
            properties=props,
            evidence_pdf_s3_path=pdf_path,
        ))

    for raw_edge in data.get("edges", []):
        from_id = raw_edge.get("from", "")
        to_id = raw_edge.get("to", "")
        if not from_id or not to_id:
            continue
        props = {"description": raw_edge.get("description", "")}
        props.update(raw_edge.get("properties", {}))
        props["chunk_id"] = chunk.chunk_id
        edges.append(GraphEdge(
            from_id=from_id,
            to_id=to_id,
            relationship=raw_edge.get("relationship", "RELATES_TO"),
            properties=props,
            evidence_pdf_s3_path=pdf_path,
        ))

    return nodes, edges


def _extract_implementation_graph_llm(
    chunk: Chunk,
    client,
    model_id: str,
    max_content_chars: int = 6000,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Use Claude Sonnet to extract Implementation/Evidence Graph from a chunk."""
    content = chunk.content[:max_content_chars]
    prompt = _IMPLEMENTATION_GRAPH_PROMPT.format(
        workbook_name=chunk.workbook_name,
        sheet_name=chunk.sheet_name,
        sheet_index=chunk.sheet_index,
        chunk_type=chunk.chunk_type,
        content=content,
    )

    try:
        response_text, usage = converse_text(client, model_id, prompt, max_tokens=4096, temperature=0.1)
        logger.debug("Implementation LLM: %d in / %d out tokens", usage.get("inputTokens", 0), usage.get("outputTokens", 0))
    except Exception as exc:
        logger.warning("Implementation graph LLM call failed for chunk %s: %s", chunk.chunk_id, exc)
        return [], []

    try:
        data = json.loads(_clean_json_response(response_text))
    except json.JSONDecodeError as exc:
        logger.warning("Implementation graph JSON parse failed for chunk %s: %s", chunk.chunk_id, exc)
        return [], []

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    pdf_path = chunk.source_pdf_s3_path

    for raw_node in data.get("nodes", []):
        node_id = raw_node.get("id", "")
        if not node_id:
            continue
        props = raw_node.get("properties", {})
        props["sheet_index"] = chunk.sheet_index
        props["sheet_name"] = chunk.sheet_name
        props["chunk_id"] = chunk.chunk_id
        props["workbook_name"] = chunk.workbook_name
        nodes.append(GraphNode(
            node_id=node_id,
            label=raw_node.get("label", "Field"),
            name=raw_node.get("name", node_id),
            properties=props,
            evidence_pdf_s3_path=pdf_path,
        ))

    for raw_edge in data.get("edges", []):
        from_id = raw_edge.get("from", "")
        to_id = raw_edge.get("to", "")
        if not from_id or not to_id:
            continue
        props = raw_edge.get("properties", {})
        props["chunk_id"] = chunk.chunk_id
        edges.append(GraphEdge(
            from_id=from_id,
            to_id=to_id,
            relationship=raw_edge.get("relationship", "RELATES_TO"),
            properties=props,
            evidence_pdf_s3_path=pdf_path,
        ))

    return nodes, edges


# ─────────────────────────────────────────────────────────────────────────────
# Fallback: keyword-based extraction (no LLM cost, used for overview chunks)
# ─────────────────────────────────────────────────────────────────────────────

_KNOWN_SYSTEMS = {
    "SAP": "SAP S/4HANA", "S4/HANA": "SAP S/4HANA", "S4HANA": "SAP S/4HANA",
    "DataSpider": "DataSpider (NTT DATA)", "ANDPAD": "ANDPAD",
    "中間F": "中間ファイル (Intermediate File)", "中間ファイル": "中間ファイル (Intermediate File)",
}
_SYSTEM_CANONICAL = {
    "SAP": "SAP", "S4/HANA": "SAP", "S4HANA": "SAP",
    "DataSpider": "DataSpider", "ANDPAD": "ANDPAD",
    "中間F": "IntermediateFile", "中間ファイル": "IntermediateFile",
}


def _extract_entities_keyword(chunk: Chunk) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Lightweight keyword-based extraction for overview/cross-sheet chunks."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    pdf_path = chunk.source_pdf_s3_path

    clean_name = re.sub(r"[^\w]", "_", chunk.sheet_name)[:40]
    sheet_node_id = f"Sheet_sheet{chunk.sheet_index:02d}_{clean_name}"
    nodes.append(GraphNode(
        node_id=sheet_node_id, label="Sheet", name=chunk.sheet_name,
        properties={"sheet_index": chunk.sheet_index, "workbook_name": chunk.workbook_name},
        evidence_pdf_s3_path=pdf_path,
    ))

    for sys_kw in chunk.systems:
        canonical = _SYSTEM_CANONICAL.get(sys_kw, sys_kw)
        sys_node_id = f"System_{canonical}"
        nodes.append(GraphNode(
            node_id=sys_node_id, label="System", name=canonical,
            properties={"display_name": _KNOWN_SYSTEMS.get(sys_kw, sys_kw)},
            evidence_pdf_s3_path=pdf_path,
        ))
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=sys_node_id, relationship="REFERENCES",
            properties={"chunk_id": chunk.chunk_id},
            evidence_pdf_s3_path=pdf_path,
        ))

    return nodes, edges


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction entry points
# ─────────────────────────────────────────────────────────────────────────────

def extract_business_graph(
    chunks: list[Chunk],
    cfg: Optional[Config] = None,
    delay_seconds: float = 3.0,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Extract Business Semantic Graph from chunks using LLM.

    Groups chunks by sheet and sends one representative chunk per sheet
    to avoid redundant LLM calls.
    """
    cfg = cfg or _default_config
    client = make_bedrock_client(cfg.aws_region)
    model_id = cfg.vlm_model_id

    # Group chunks by sheet — pick the longest chunk per sheet for best context
    sheet_chunks: dict[int, Chunk] = {}
    for chunk in chunks:
        if chunk.sheet_index == 0:
            continue
        existing = sheet_chunks.get(chunk.sheet_index)
        if existing is None or len(chunk.content) > len(existing.content):
            sheet_chunks[chunk.sheet_index] = chunk

    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []

    for i, (sheet_idx, chunk) in enumerate(sorted(sheet_chunks.items())):
        if i > 0:
            time.sleep(delay_seconds)
        logger.info("Business graph: sheet %d (%s)", sheet_idx, chunk.sheet_name)
        nodes, edges = _extract_business_graph_llm(chunk, client, model_id)
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        logger.info("  → %d nodes, %d edges", len(nodes), len(edges))

    logger.info("Business graph total: %d nodes, %d edges", len(all_nodes), len(all_edges))
    return all_nodes, all_edges


def extract_implementation_graph(
    chunks: list[Chunk],
    cfg: Optional[Config] = None,
    delay_seconds: float = 3.0,
    chunk_types: Optional[set[str]] = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Extract Implementation/Evidence Graph from chunks using LLM.

    Only processes chunks of relevant types (mapping, API, rules, conditions).
    Overview chunks get lightweight keyword extraction.
    """
    cfg = cfg or _default_config
    client = make_bedrock_client(cfg.aws_region)
    model_id = cfg.vlm_model_id

    # Types that benefit from LLM extraction
    llm_types = chunk_types or {"mapping_table", "api_spec", "business_rule", "data_condition", "flowchart"}

    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []
    llm_call_count = 0

    for chunk in chunks:
        if chunk.chunk_type in llm_types:
            if llm_call_count > 0:
                time.sleep(delay_seconds)
            logger.info("Implementation graph: chunk %s (type=%s)", chunk.chunk_id[:30], chunk.chunk_type)
            nodes, edges = _extract_implementation_graph_llm(chunk, client, model_id)
            all_nodes.extend(nodes)
            all_edges.extend(edges)
            llm_call_count += 1
            logger.info("  → %d nodes, %d edges", len(nodes), len(edges))
        else:
            # Lightweight keyword extraction for overview/cross_sheet_summary
            nodes, edges = _extract_entities_keyword(chunk)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    logger.info(
        "Implementation graph total: %d nodes, %d edges (%d LLM calls)",
        len(all_nodes), len(all_edges), llm_call_count,
    )
    return all_nodes, all_edges


def extract_entities(chunk: Chunk) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Legacy entry point — keyword-only extraction for backward compatibility.

    Used when LLM extraction is not desired (e.g., quick dry-run, cost control).
    """
    return _extract_entities_keyword(chunk)
