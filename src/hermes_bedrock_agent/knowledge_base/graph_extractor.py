"""LLM-based graph extraction from parsed Markdown chunks.

Two-pass extraction using Claude Sonnet:
  Pass 1: Business Semantic Graph — high-level systems, processes, data flows
           (workbook-level summary + per-sheet content for full context)
  Pass 2: Implementation / Evidence Graph — tables, fields, mappings, rules
           (per-chunk, with full content to capture field-level relationships)

Each pass sends the Markdown chunk content to the VLM and receives structured
JSON with nodes and edges. Both are linked back to source chunks and PDF evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from ..clients.bedrock import converse_text, make_bedrock_client
from ..config import Config, config as _default_config
from .schemas import Chunk, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Prompts for two-pass LLM extraction
# ─────────────────────────────────────────────────────────────────────────────

_BUSINESS_GRAPH_PROMPT = """\
You are a system integration architect analyzing enterprise interface specification documents.

## Context
This workbook is an interface design document (IFマッピング定義書) that defines data integration \
between enterprise systems. The document covers interface specifications, data mappings, API \
definitions, and business rules.

### Workbook-level Overview
{workbook_summary}

### Current Sheet
- Workbook: {workbook_name}
- Sheet: {sheet_name} (index: {sheet_index})

### Sheet Content
{content}

## Task
Extract a **Business Semantic Graph** that helps users understand the overall system architecture \
and data flow design at a business level.

Extract these node types:
- **System**: Enterprise systems, middleware, platforms (e.g., SAP S4/HANA, DataSpider, ANDPAD)
- **InterfaceSpec**: Interface specifications / IFマッピング definitions with IF-ID
- **DataFlow**: Named data flows between systems (directional: source→target)
- **BusinessProcess**: Business operations triggered by the interface (e.g., 発注情報登録, 納品一覧取得)
- **API**: API operations exposed or consumed (e.g., 【Send】発注作成, 発注一覧取得 GET)

Extract these edge types:
- **SENDS_DATA_TO**: System A sends data to System B (directional data flow)
- **CALLS_API**: System or process calls an API
- **TRIGGERS**: Event or process triggers another process/flow
- **PRODUCES**: Process produces data flow or intermediate file
- **PART_OF**: Sub-component is part of a larger interface/process

## Output Format
Return ONLY valid JSON (no markdown fencing, no comments):
{{
  "nodes": [
    {{
      "id": "<unique_stable_id>",
      "label": "<System|InterfaceSpec|DataFlow|BusinessProcess|API>",
      "name": "<display_name — use original Japanese for processes/APIs>",
      "description": "<1-2 sentence description in original language>"
    }}
  ],
  "edges": [
    {{
      "from": "<source_node_id>",
      "to": "<target_node_id>",
      "relationship": "<SENDS_DATA_TO|CALLS_API|TRIGGERS|PRODUCES|PART_OF>",
      "description": "<brief description of this relationship>"
    }}
  ]
}}

## Rules
1. System names: use canonical names (SAP, DataSpider, ANDPAD, IntermediateFile)
2. For processes and APIs, preserve the ORIGINAL Japanese names exactly
3. Node IDs must be stable: use format `Label_ShortName` (e.g., System_SAP, API_発注作成, DataFlow_発注データ連携)
4. Focus on WHAT happens at business level, not HOW fields are mapped
5. Maximum 20 nodes and 25 edges per sheet
6. If this sheet is just a title page, change history, or empty → return {{"nodes": [], "edges": []}}
"""

_IMPLEMENTATION_GRAPH_PROMPT = """\
You are a data integration engineer analyzing field-level mapping specifications.

## Context
This document defines field-by-field data mapping between enterprise systems. \
It typically contains:
- Source table/file with field definitions (左側: source system fields)
- Target table/API with field definitions (右側: target system fields)
- Mapping rules connecting source fields to target fields (中央: transformation logic)
- Business rules and conditions that control the mapping

### Current Sheet
- Workbook: {workbook_name}
- Sheet: {sheet_name} (index: {sheet_index})
- Content type: {chunk_type}

### Sheet Content
{content}

## Task
Extract an **Implementation / Evidence Graph** focusing on the actual data structures, \
field mappings, and transformation rules defined in this specification.

Extract these node types:
- **SourceTable**: Source system table or file (e.g., SAP発注情報ファイル, ヘッダレコード, 明細レコード)
- **TargetTable**: Target system table or API payload (e.g., ANDPAD発注ヘッダ, ContractOrderItemForCreate)
- **SourceField**: Individual field in the source table (with properties: no, type, required, length)
- **TargetField**: Individual field in the target table (with properties: no, type, required, length)
- **MappingRule**: A transformation rule connecting source to target (with: source_fields, target_field, logic)
- **BusinessRule**: Condition or validation rule (with: condition_text, affected_fields)
- **API**: API endpoint being called (with: method, direction)

Extract these edge types:
- **HAS_FIELD**: Table → Field (source or target)
- **MAPS_TO**: SourceField → TargetField (direct 1:1 mapping)
- **TRANSFORMS_TO**: SourceField → MappingRule → TargetField (with transformation logic)
- **HAS_CONDITION**: MappingRule → BusinessRule (conditional mapping)
- **CALLS_API**: SourceTable/DataFlow → API (which API is called)
- **DEFINED_IN**: Field/Rule → Sheet (traceability)

## Output Format
Return ONLY valid JSON (no markdown fencing, no comments):
{{
  "nodes": [
    {{
      "id": "<unique_stable_id>",
      "label": "<SourceTable|TargetTable|SourceField|TargetField|MappingRule|BusinessRule|API>",
      "name": "<display_name — use ORIGINAL Japanese field names>",
      "properties": {{
        "source_system": "<system name if known>",
        "target_system": "<system name if known>",
        "field_no": "<number if field>",
        "data_type": "<field type>",
        "required": "<true/false>",
        "transformation": "<transformation logic text>",
        "condition": "<condition text for rules>"
      }}
    }}
  ],
  "edges": [
    {{
      "from": "<source_node_id>",
      "to": "<target_node_id>",
      "relationship": "<HAS_FIELD|MAPS_TO|TRANSFORMS_TO|HAS_CONDITION|CALLS_API|DEFINED_IN>",
      "properties": {{
        "mapping_logic": "<brief transformation description if applicable>"
      }}
    }}
  ]
}}

## Rules
1. Preserve ALL original Japanese field names exactly (e.g., 購買発注番号, 発注管理ID, 税込合計金額)
2. Node IDs: `Label_sheet{{sheet_index:02d}}_ShortName` (e.g., SourceField_sheet06_購買発注番号)
3. For fields with No. numbers, include the number in properties
4. Capture SOURCE → TARGET mapping direction clearly:
   - SourceField from left/source table → TargetField in right/target table
   - Include the transformation logic in MappingRule properties
5. For conditional mappings (e.g., "工事区分=1の場合..."), create a BusinessRule node
5. IMPORTANT: Extract the complete mapping chain when visible:
   SourceField --MAPS_TO--> TargetField (for simple 1:1 mappings)
   SourceField --TRANSFORMS_TO--> MappingRule --MAPS_TO--> TargetField (for complex transformations)
6. Focus on the MOST IMPORTANT mappings — prioritize:
   - Key fields (IDs, amounts, dates)
   - Fields with complex transformation logic
   - Fields with business conditions
   Skip trivial direct-copy fields that have no transformation logic
7. Maximum 30 nodes and 35 edges per chunk
8. If no implementation details exist → return {{"nodes": [], "edges": []}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM extraction functions
# ─────────────────────────────────────────────────────────────────────────────

def _clean_json_response(text: str) -> str:
    """Strip markdown fencing and extract JSON from LLM response.
    
    Also attempts to repair truncated JSON (common when output hits max_tokens).
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    
    # Attempt to parse as-is first
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    
    # Repair truncated JSON: find the last valid nodes/edges array
    # Strategy: try to close open arrays and objects
    repaired = text
    # Count open brackets
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    
    # If we're inside a string value (trailing comma, incomplete value), truncate to last complete entry
    # Find last complete object in array (last "}")
    last_brace = repaired.rfind("}")
    if last_brace > 0:
        # Try truncating to last closing brace and closing arrays
        candidate = repaired[:last_brace + 1]
        # Re-count
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")
        candidate += "]" * open_brackets + "}" * open_braces
        try:
            json.loads(candidate)
            logger.info("JSON repaired by truncating to last complete object")
            return candidate
        except json.JSONDecodeError:
            pass
    
    # More aggressive: find the "edges" array start and close everything
    edges_match = re.search(r'"edges"\s*:\s*\[', repaired)
    if edges_match:
        # Find last complete edge object
        after_edges = repaired[edges_match.end():]
        last_edge_close = after_edges.rfind("}")
        if last_edge_close > 0:
            candidate = repaired[:edges_match.end() + last_edge_close + 1] + "]}"
            try:
                json.loads(candidate)
                logger.info("JSON repaired by closing edges array")
                return candidate
            except json.JSONDecodeError:
                pass
    
    # Last resort: try to extract just nodes if edges are completely broken
    nodes_match = re.search(r'"nodes"\s*:\s*\[', repaired)
    if nodes_match:
        # Find the closing of nodes array (before "edges")
        if edges_match and edges_match.start() > nodes_match.end():
            # Try: everything up to edges key, close as nodes-only
            before_edges = repaired[:edges_match.start()]
            # Remove trailing comma/whitespace
            before_edges = before_edges.rstrip().rstrip(",").rstrip()
            candidate = before_edges + '], "edges": []}'
            # Ensure we have proper structure
            if not candidate.startswith("{"):
                candidate = "{" + candidate
            try:
                json.loads(candidate)
                logger.warning("JSON partially repaired: only nodes extracted (edges truncated)")
                return candidate
            except json.JSONDecodeError:
                pass
    
    return text


def _load_workbook_summary(chunks: list[Chunk]) -> str:
    """Build a workbook-level summary from cross_sheet_summary chunks or sheet list."""
    # Look for cross_sheet_summary chunk
    for chunk in chunks:
        if chunk.chunk_type == "cross_sheet_summary":
            # Return first 3000 chars of the cross-sheet summary as context
            return chunk.content[:3000]

    # Fallback: build a simple sheet list
    sheet_info: dict[int, str] = {}
    for c in chunks:
        if c.sheet_index > 0 and c.sheet_index not in sheet_info:
            sheet_info[c.sheet_index] = c.sheet_name
    if not sheet_info:
        return "(No workbook summary available)"

    lines = ["Sheets in this workbook:"]
    for idx in sorted(sheet_info):
        lines.append(f"  Sheet {idx:02d}: {sheet_info[idx]}")
    return "\n".join(lines)


def _extract_business_graph_llm(
    chunk: Chunk,
    client,
    model_id: str,
    workbook_summary: str,
    max_content_chars: int = 12000,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Use Claude Sonnet to extract Business Semantic Graph from a sheet."""
    content = chunk.content[:max_content_chars]
    prompt = _BUSINESS_GRAPH_PROMPT.format(
        workbook_name=chunk.workbook_name,
        sheet_name=chunk.sheet_name,
        sheet_index=chunk.sheet_index,
        workbook_summary=workbook_summary,
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
        logger.warning("Business graph JSON parse failed for sheet %d: %s\nResponse: %s", chunk.sheet_index, exc, response_text[:200])
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
        props["sheet_name"] = chunk.sheet_name
        props["workbook_name"] = chunk.workbook_name
        if chunk.project_id:
            props["project_id"] = chunk.project_id
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
        props["sheet_index"] = chunk.sheet_index
        if chunk.project_id:
            props["project_id"] = chunk.project_id
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
    max_content_chars: int = 12000,
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
        response_text, usage = converse_text(client, model_id, prompt, max_tokens=8000, temperature=0.1)
        logger.debug("Implementation LLM: %d in / %d out tokens", usage.get("inputTokens", 0), usage.get("outputTokens", 0))
    except Exception as exc:
        logger.warning("Implementation graph LLM call failed for chunk %s: %s", chunk.chunk_id, exc)
        return [], []

    try:
        data = json.loads(_clean_json_response(response_text))
    except json.JSONDecodeError as exc:
        logger.warning("Implementation graph JSON parse failed for chunk %s: %s\nResponse: %s", chunk.chunk_id, exc, response_text[:200])
        return [], []

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    pdf_path = chunk.source_pdf_s3_path

    for raw_node in data.get("nodes", []):
        node_id = raw_node.get("id", "")
        if not node_id:
            continue
        props = raw_node.get("properties", {})
        if not isinstance(props, dict):
            props = {}
        props["sheet_index"] = chunk.sheet_index
        props["sheet_name"] = chunk.sheet_name
        props["chunk_id"] = chunk.chunk_id
        props["workbook_name"] = chunk.workbook_name
        if chunk.project_id:
            props["project_id"] = chunk.project_id
        nodes.append(GraphNode(
            node_id=node_id,
            label=raw_node.get("label", "SourceField"),
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
        if not isinstance(props, dict):
            props = {}
        props["chunk_id"] = chunk.chunk_id
        props["sheet_index"] = chunk.sheet_index
        if chunk.project_id:
            props["project_id"] = chunk.project_id
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
    sheet_props: dict = {"sheet_index": chunk.sheet_index, "workbook_name": chunk.workbook_name}
    if chunk.project_id:
        sheet_props["project_id"] = chunk.project_id
    nodes.append(GraphNode(
        node_id=sheet_node_id, label="Sheet", name=chunk.sheet_name,
        properties=sheet_props,
        evidence_pdf_s3_path=pdf_path,
    ))

    for sys_kw in chunk.systems:
        canonical = _SYSTEM_CANONICAL.get(sys_kw, sys_kw)
        sys_node_id = f"System_{canonical}"
        sys_props: dict = {"source_keyword": sys_kw}
        if chunk.project_id:
            sys_props["project_id"] = chunk.project_id
        nodes.append(GraphNode(
            node_id=sys_node_id, label="System", name=canonical,
            properties=sys_props,
            evidence_pdf_s3_path=pdf_path,
        ))
        edge_props: dict = {"chunk_id": chunk.chunk_id}
        if chunk.project_id:
            edge_props["project_id"] = chunk.project_id
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=sys_node_id, relationship="REFERENCES",
            properties=edge_props,
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

    Strategy:
    - Builds a workbook-level summary from cross_sheet_summary chunks
    - For each sheet, concatenates ALL chunks of that sheet for maximum context
    - Sends sheet content + workbook summary to Claude Sonnet
    """
    cfg = cfg or _default_config
    client = make_bedrock_client(cfg.aws_region)
    model_id = cfg.vlm_model_id

    # Build workbook-level summary for context
    workbook_summary = _load_workbook_summary(chunks)

    # Group chunks by sheet — concatenate all chunks per sheet for full context
    sheet_content: dict[int, list[Chunk]] = {}
    for chunk in chunks:
        if chunk.sheet_index == 0:
            continue
        sheet_content.setdefault(chunk.sheet_index, []).append(chunk)

    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []

    for i, (sheet_idx, sheet_chunks) in enumerate(sorted(sheet_content.items())):
        if i > 0:
            time.sleep(delay_seconds)

        # Build a merged chunk with all content from this sheet
        merged_text = "\n\n".join(c.content for c in sorted(sheet_chunks, key=lambda x: x.chunk_id))
        # Use the first chunk as the representative (for metadata)
        representative = sheet_chunks[0]
        # Create a synthetic chunk with merged content
        merged_chunk = Chunk(
            chunk_id=representative.chunk_id,
            content=merged_text,
            chunk_type=representative.chunk_type,
            sheet_index=sheet_idx,
            sheet_name=representative.sheet_name,
            workbook_name=representative.workbook_name,
            source_pdf_s3_path=representative.source_pdf_s3_path,
            source_excel_s3_path=representative.source_excel_s3_path,
            source_markdown_s3_path=representative.source_markdown_s3_path,
            related_sheets=representative.related_sheets,
            systems=representative.systems,
            apis=representative.apis,
            fields=representative.fields,
            embedding_text="",
            project_id=representative.project_id,
        )

        logger.info("Business graph: sheet %d (%s) — %d chars", sheet_idx, representative.sheet_name, len(merged_text))
        nodes, edges = _extract_business_graph_llm(merged_chunk, client, model_id, workbook_summary)
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

    Strategy:
    - For mapping/API/rule/condition/flowchart chunks: full LLM extraction
    - For overview chunks: lightweight keyword extraction (no cost)
    - Sends each chunk's FULL content (up to 12K chars) for deep understanding
    """
    cfg = cfg or _default_config
    client = make_bedrock_client(cfg.aws_region)
    model_id = cfg.vlm_model_id

    # Types that have rich implementation detail worth LLM extraction
    llm_types = chunk_types or {"mapping_table", "api_spec", "business_rule", "data_condition", "flowchart"}

    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []
    llm_call_count = 0

    for chunk in chunks:
        if chunk.chunk_type in llm_types:
            if llm_call_count > 0:
                time.sleep(delay_seconds)
            logger.info(
                "Implementation graph: chunk %s (type=%s, sheet=%d, %d chars)",
                chunk.chunk_id[:30], chunk.chunk_type, chunk.sheet_index, len(chunk.content),
            )
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
