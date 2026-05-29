"""Phase 2: Two-pass LLM extraction of nodes and edges from markdown files.

Pass 1 extracts all entity nodes.
Pass 2 takes the node ID list and extracts all edges — avoids truncation issues
that plagued the original single-pass approach.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from ..clients.bedrock import converse_text
from .config import GraphPipelineConfig

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert enterprise system knowledge graph extraction engine.
You analyze Japanese enterprise design documents (middleware specifications, API mappings, flowcharts, interface definitions) and extract structured semantic entities and relationships.

You must extract entities at multiple levels:
- L2: Systems, Interfaces, BusinessProcesses
- L3: FunctionModules, APIOperations, MappingDefinitions, DecisionPoints
- L4: FlowNodes, APICallSteps, ScriptSteps, FileOperations, internal processing steps
- L5: Fields, FieldMappings, TransformationRules, FilterConditions, StatusValues

Return ONLY valid JSON. Never add explanatory text outside the JSON."""

_V3_NODE_EXTRACTION_PROMPT = """Analyze the following enterprise design document markdown and extract ALL semantic entities as a JSON array.

## Project Context
Project: {project_name} (ID: {project_id})
Workbook: {workbook_name}
Sheet: {sheet_name} (Type: {sheet_type})
Source File: {source_file}

## All Sheets in This Project (for cross-sheet understanding)
{project_sheet_summary}

## Document Content
{content}

## Extraction Instructions

Extract ALL meaningful entities. Use these entity types:
System, Middleware, Interface, BusinessProcess, FunctionModule, FlowNode, DecisionPoint, BranchCondition, APIOperation, APICallStep, MappingDefinition, FieldMapping, Field, DataEntity, FileObject, TransformationRule, ConversionRule, BusinessRule, FilterCondition, StatusValue, ScriptStep, FileOperation, ResultReturn, ErrorHandlingStep, Annotation

Rules:
1. Preserve Japanese text in name/display_name
2. Every entity needs non-empty evidence_text (short quote from doc, max 100 chars)
3. Extract INTERNAL steps within function blocks (FlowNode/ScriptStep/FileOperation)
4. For mapping tables: extract row-level FieldMapping
5. Use stable lowercase IDs with underscores
6. confidence: 0.85+ for explicit, 0.70-0.75 for inferred

Return ONLY a JSON array of node objects:
[
  {{
    "id": "stable_local_id",
    "entity_type": "System|FunctionModule|FlowNode|etc",
    "name": "Japanese name preserved",
    "display_name": "Human readable",
    "description": "1 sentence",
    "layer": "system|process|data|knowledge",
    "evidence_text": "short quote from document",
    "confidence": 0.85,
    "review_status": "verified|pending",
    "importance": 2,
    "view_scope": "core|detail",
    "flow_node_kind": "read|write|transform|api|decision|loop|annotation|start|end|unknown",
    "parent_function_id": "",
    "sequence_no": ""
  }}
]"""


_V3_EDGE_EXTRACTION_PROMPT = """Given the following enterprise design document and the list of extracted entity nodes, identify ALL relationships between them.

## Project Context
Project: {project_name} (ID: {project_id})
Workbook: {workbook_name}
Sheet: {sheet_name} (Type: {sheet_type})
Source File: {source_file}

## Extracted Node IDs
{node_id_list}

## Document Content
{content}

## Relationship Types (use exactly these)
Structure: BELONGS_TO_PROJECT, HAS_WORKBOOK, HAS_SHEET, EVIDENCED_BY
Process: HAS_PROCESS, HAS_FUNCTION, CONTAINS_STEP, STARTS_WITH, ENDS_WITH, NEXT_STEP, BRANCHES_TO, HAS_BRANCH_CONDITION, HAS_CONDITION, HAS_DECISION_POINT, HAS_EXCEPTION_PATH, HAS_ANNOTATION
System: USES_SYSTEM, FROM_SYSTEM, TO_SYSTEM, VIA_MIDDLEWARE, HAS_INTERFACE, HAS_API_OPERATION, CALLS_API, SENDS_TO, RECEIVES_FROM, READS_FILE, WRITES_FILE
Data: HAS_RECORD_TYPE, HAS_FIELD, USES_FIELD, HAS_SOURCE_FIELD, HAS_TARGET_FIELD, USES_MAPPING, HAS_MAPPING_ROW, MAPS_TO, HAS_ENUM_VALUE, HAS_STATUS_VALUE
API: HAS_API_SEQUENCE, HAS_API_CALL_STEP, HAS_RETRIEVAL_CONDITION, HAS_FILTER_CONDITION, HAS_REQUEST_PAYLOAD, HAS_RESPONSE_PAYLOAD
Rules: APPLIES_RULE, HAS_RESULT_RETURN, HAS_ERROR_HANDLING, RETURNS_TO, FILTERS_BY

Rules:
1. from_id and to_id MUST match IDs from the Extracted Node IDs list above
2. Every edge needs non-empty evidence_text (short quote, max 80 chars)
3. Preserve edge labels, branch labels, conditions from flowcharts
4. confidence: 0.85+ for explicit, 0.70-0.75 for inferred
5. Be comprehensive: capture NEXT_STEP sequences, CONTAINS_STEP hierarchies, MAPS_TO field links

Return ONLY a JSON array of edge objects:
[
  {{
    "from_id": "source_node_id",
    "to_id": "target_node_id",
    "type": "RELATIONSHIP_TYPE",
    "edge_label": "label from flowchart arrow or empty",
    "condition_text": "branch condition or empty",
    "branch_label": "yes/no/status label or empty",
    "evidence_text": "short supporting quote",
    "confidence": 0.85,
    "link_method": "explicit_text|structural|inferred",
    "review_status": "verified|pending",
    "sequence_no": "",
    "layer": "process|system|data|knowledge"
  }}
]"""


# ── JSON recovery parsers ─────────────────────────────────────────────────────

def _parse_node_response(raw: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("nodes", [])
        return []
    except json.JSONDecodeError:
        nodes = []
        arr_start = text.find("[")
        if arr_start >= 0:
            bracket_depth = 0
            i = arr_start
            last_complete = arr_start + 1
            while i < len(text):
                if text[i] == "{":
                    bracket_depth += 1
                elif text[i] == "}":
                    bracket_depth -= 1
                    if bracket_depth == 0:
                        last_complete = i + 1
                elif text[i] == "]" and bracket_depth == 0:
                    last_complete = i
                    break
                i += 1

            arr_text = text[arr_start:last_complete]
            if not arr_text.endswith("]"):
                arr_text = arr_text.rstrip().rstrip(",") + "]"
            try:
                nodes = json.loads(arr_text)
            except Exception:
                pass

        if nodes:
            logger.warning("Recovered %d nodes from truncated JSON", len(nodes))
        else:
            logger.error("Failed to parse node response as JSON")
        return nodes


def _parse_edge_response(raw: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("edges", [])
        return []
    except json.JSONDecodeError:
        edges = []
        arr_start = text.find("[")
        if arr_start >= 0:
            bracket_depth = 0
            i = arr_start
            last_complete = arr_start + 1
            while i < len(text):
                if text[i] == "{":
                    bracket_depth += 1
                elif text[i] == "}":
                    bracket_depth -= 1
                    if bracket_depth == 0:
                        last_complete = i + 1
                elif text[i] == "]" and bracket_depth == 0:
                    last_complete = i
                    break
                i += 1

            arr_text = text[arr_start:last_complete]
            if not arr_text.endswith("]"):
                arr_text = arr_text.rstrip().rstrip(",") + "]"
            try:
                edges = json.loads(arr_text)
            except Exception:
                pass

        if edges:
            logger.warning("Recovered %d edges from truncated JSON", len(edges))
        else:
            logger.error("Failed to parse edge response as JSON")
        return edges


# ── Per-file extraction ───────────────────────────────────────────────────────

def extract_from_markdown(
    file_rec: dict,
    cfg: GraphPipelineConfig,
    project_sheet_summary: str,
    bedrock_client: Any,
    cache_dir: Path,
) -> tuple[list[dict], list[dict]]:
    """Extract semantic entities from one markdown file via two-pass LLM calls.

    Pass 1: extract nodes.
    Pass 2: given node IDs, extract edges.
    Returns (nodes, edges) as plain dicts with source metadata already attached.
    """
    cache_key = hashlib.md5(file_rec["file_path"].encode()).hexdigest()
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            nodes = cached.get("nodes", [])
            edges = cached.get("edges", [])
            # Re-extract edges if cache has nodes but zero edges
            if not (len(nodes) > 10 and len(edges) == 0):
                return nodes, edges
        except Exception:
            pass

    try:
        content = Path(file_rec["file_path"]).read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Cannot read %s: %s", file_rec["file_path"], exc)
        return [], []

    if len(content.strip()) < 100:
        logger.info("Skipping near-empty file: %s", file_rec["file_name"])
        return [], []

    if len(content) > 25000:
        content = content[:25000] + "\n\n[...content truncated for extraction...]"

    # ── Pass 1: nodes ─────────────────────────────────────────────────────────
    node_prompt = _V3_NODE_EXTRACTION_PROMPT.format(
        project_name=cfg.project_name,
        project_id=cfg.project_id,
        workbook_name=file_rec["workbook_name"],
        sheet_name=file_rec["sheet_name"],
        sheet_type=file_rec["sheet_type"],
        source_file=file_rec["file_path"],
        project_sheet_summary=project_sheet_summary,
        content=content,
    )

    try:
        full_prompt = f"<system>\n{_SYSTEM_PROMPT}\n</system>\n\n{node_prompt}"
        response, _usage = converse_text(
            client=bedrock_client,
            model_id=cfg.model_id,
            prompt=full_prompt,
            max_tokens=cfg.max_tokens,
        )
    except Exception as exc:
        logger.error("LLM node extraction failed for %s: %s", file_rec["file_name"], exc)
        return [], []

    nodes = _parse_node_response(response)

    time.sleep(2)

    # ── Pass 2: edges ─────────────────────────────────────────────────────────
    edges: list[dict] = []
    if nodes:
        node_id_list = "\n".join(
            f"- {n.get('id', '?')} ({n.get('entity_type', '?')}): {n.get('name', '')}"
            for n in nodes[:80]
        )
        edge_prompt = _V3_EDGE_EXTRACTION_PROMPT.format(
            project_name=cfg.project_name,
            project_id=cfg.project_id,
            workbook_name=file_rec["workbook_name"],
            sheet_name=file_rec["sheet_name"],
            sheet_type=file_rec["sheet_type"],
            source_file=file_rec["file_path"],
            node_id_list=node_id_list,
            content=content,
        )
        try:
            full_prompt2 = f"<system>\n{_SYSTEM_PROMPT}\n</system>\n\n{edge_prompt}"
            response2, _usage2 = converse_text(
                client=bedrock_client,
                model_id=cfg.model_id,
                prompt=full_prompt2,
                max_tokens=cfg.max_tokens,
            )
        except Exception as exc:
            logger.error("LLM edge extraction failed for %s: %s", file_rec["file_name"], exc)
            response2 = "[]"

        edges = _parse_edge_response(response2)

    # Attach source metadata
    for node in nodes:
        node["project_name"] = cfg.project_name
        node["project_id"] = cfg.project_id
        node["workbook_name"] = file_rec["workbook_name"]
        node["sheet_name"] = file_rec["sheet_name"]
        node["sheet_type"] = file_rec["sheet_type"]
        node["source_file"] = file_rec["file_path"]

    for edge in edges:
        edge["project_name"] = cfg.project_name
        edge["project_id"] = cfg.project_id
        edge["workbook_name"] = file_rec["workbook_name"]
        edge["sheet_name"] = file_rec["sheet_name"]
        edge["source_file"] = file_rec["file_path"]

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return nodes, edges
