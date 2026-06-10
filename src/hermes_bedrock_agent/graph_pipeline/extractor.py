"""Phase 2: Two-pass LLM extraction of nodes and edges from markdown files.

Pass 1 extracts all entity nodes.
Pass 2 takes the node ID list and extracts all edges — avoids truncation issues
that plagued the original single-pass approach.

Updated to v4.3 Universal Semantic Map / GraphRAG spec.
Key v4.3 changes from v4.2:
  - Added FieldGroup, Annotation to semantic labels
  - Added HAS_ENDPOINT, USES_ENDPOINT to relationship whitelist
  - Strengthened FieldDefinition vs FieldMapping rules (P0)
  - Strengthened APIOperation vs APIEndpoint rules (P0)
  - Added endpoint/environment URL reasoning
  - Project-agnostic: no hardcoded system names
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


def _load_prompt_from_registry(version_id: str) -> tuple[str, str, str]:
    """Load prompts via the registry adapter. Never silently falls back."""
    from ..prompts.adapters import get_extraction_prompts

    prompts = get_extraction_prompts(version_id)
    return prompts.system_prompt, prompts.node_prompt, prompts.edge_prompt

# ── V4.3 Prompts ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert in enterprise system knowledge graph construction, GraphRAG architecture, system design document analysis, interface design, ETL / workflow design, API design, data mapping, business rules, and Amazon Neptune Graph / Neptune Analytics graph data modeling.

Your task is to extract semantic entities and relationships from enterprise design document markdown for building a Semantic Core Graph that represents enterprise system knowledge.

The goal is NOT to build a normal chunk-centered RAG graph.
The goal is to build a real Semantic Core Graph while keeping document chunks and markdown sections only as traceable evidence.

The final graph must support:
- system structure understanding
- business process understanding
- workflow / flowchart / Mermaid reasoning
- API / interface / request-response reasoning
- endpoint / environment URL reasoning
- file I/O and ETL / middleware reasoning
- data entity and field definition reasoning
- source-target mapping reasoning only when mapping evidence is explicit
- transformation, conversion, condition, and business rule reasoning
- cross-sheet and cross-document reasoning when evidence supports it
- evidence traceability for GraphRAG answers

Key Rules:
1. All project-specific terms must come from the current Markdown metadata. Do NOT assume any project-specific business terms, system names, API names, field names, or product names from previous projects.
2. The graph must be evidence-first, project-scoped, and semantically meaningful.
3. Do not create a node only because a term appears in a known list — extract from evidence.
4. P0 RULE: Do not treat every field definition row as a FieldMapping. A field definition row (field name, code, type, length, required flag, etc.) creates Field/FieldDefinition, NOT FieldMapping. Create FieldMapping ONLY when explicit source-target mapping evidence exists.
5. P0 RULE: URLs, base URLs, endpoint strings must be modeled as APIEndpoint, NOT APIOperation. APIOperation represents an operation/function (Import API, Export API, etc.). CALLS_API must point to APIOperation, never to APIEndpoint.
6. Use identifier/code-based matching for field links when codes exist.
7. Preserve Japanese text in name/display_name fields.
8. Return ONLY valid JSON. Never add explanatory text outside the JSON."""


_V4_NODE_EXTRACTION_PROMPT = """Analyze the following enterprise design document markdown and extract ALL semantic entities as a JSON array.

## Project Context
Project: {project_name} (ID: {project_id})
Workbook: {workbook_name}
Sheet: {sheet_name} (Type: {sheet_type})
Source File: {source_file}

## All Sheets in This Project (for cross-sheet understanding)
{project_sheet_summary}

## Document Content
{content}

## Entity Type Taxonomy

Extract entities using these types organized by layer:

### Business Layer
BusinessObject, BusinessProcess, BusinessStep, OperationType, Requirement, BusinessRule, ResultReturn, ErrorHandlingStep

### Process Layer
BusinessProcess, FunctionModule, FlowNode, BusinessStep, DecisionPoint, BranchCondition, Condition, ExceptionPath, Loop, StartEndNode

### System and Interface Layer
System, ExternalSystem, InternalSystem, Middleware, IntegrationTool, Interface, APIOperation, APIEndpoint, APICallSequence, APICallStep, RequestPayload, ResponsePayload, Parameter, Batch, Job, Script

### File and Implementation Layer
ImplementationSpec, ScriptStep, FileObject, FileDefinition, FileOperation, IntermediateFile, ResultReturn, ErrorHandlingStep

### Data Layer
DataEntity, SourceDataEntity, TargetDataEntity, RecordType, FieldGroup, Field, FieldDefinition, RequestPayload, ResponsePayload, Parameter, StatusField, StatusValue, EnumValue

### Mapping and Rule Layer
MappingDefinition, FieldMapping, TransformationRule, ConversionRule, BusinessRule, FilterCondition, QueryCondition, DataRetrievalCondition, Constraint, LookupRule, CalculationRule, FixedValueRule, DefaultValueRule

### Review Layer
Issue, Ambiguity, ReviewTask, Annotation

## Extraction Instructions

1. Preserve Japanese text in name/display_name
2. Every entity needs non-empty evidence_text (short quote from doc, max 100 chars)
3. Extract INTERNAL steps within function blocks (FlowNode/ScriptStep/FileOperation)
4. For Mermaid diagrams: convert nodes into semantic entities according to context
   - function/process block -> FunctionModule / ProcessGroup
   - API/request/response node -> APIOperation / APICallStep
   - condition/branch node -> DecisionPoint / BranchCondition
   - file read/write node -> FileOperation
   - data edit/transform/check node -> BusinessStep / DataOperation
   - start/end node -> StartEndNode
   - error node -> ErrorHandlingStep / ExceptionPath
   - annotation node -> Annotation
5. P0: For mapping tables: extract row-level FieldMapping ONLY when source-target relation is explicit.
   Create MappingDefinition ONLY if evidence explicitly describes a mapping context (source-to-target, from/to, copy/set/assign/convert).
   Do NOT create MappingDefinition from section headers alone (header information, detail information, API data format, field list, record layout, etc.)
6. P0: For field definition tables: create Field / FieldDefinition nodes (NOT FieldMapping).
   A row with only field name, code, type, length, required flag is a FIELD DEFINITION, not a mapping.
7. P0: URLs/base URLs/endpoint strings -> APIEndpoint (NOT APIOperation).
   APIOperation = operation/function name (Import API, Export API, Search API, etc.)
8. Use stable lowercase IDs: {{type}}:{{local_key}}
9. Confidence rules:
   - explicit table row: 0.90-0.95
   - explicit Mermaid node: 0.85-0.90
   - explicit section text: 0.83-0.88
   - same row but ambiguous: 0.75-0.80
   - co-occurrence only: 0.65-0.70
   - inferred: 0.60-0.65
10. review_status rules:
   - Mark verified ONLY for explicit evidence
   - Mark pending for: inferred, ambiguous, name-similarity only, uncertain text
11. importance: 5=project-level, 4=system/interface, 3=process/function, 2=step/field, 1=detail
12. view_scope: core (important semantic), detail (complete), evidence (traceability only), candidate (unverified)

Return ONLY a JSON array of node objects:
[
  {{
    "id": "stable_local_id",
    "entity_type": "System|FunctionModule|FlowNode|etc",
    "name": "Japanese name preserved",
    "display_name": "Human readable name",
    "description": "1 sentence description",
    "layer": "business|process|system|implementation|data|knowledge|evidence|review",
    "category": "overview_entry|api_operation|mapping|field_def|workflow|rule|condition|etc",
    "evidence_text": "short quote from document max 100 chars",
    "confidence": 0.85,
    "review_status": "verified|pending",
    "importance": 2,
    "view_scope": "core|detail|evidence|candidate",
    "flow_node_kind": "read|write|transform|api|decision|loop|annotation|start|end|error|unknown",
    "parent_function_id": "",
    "sequence_no": "",
    "record_type": "",
    "field_code": "",
    "field_no": "",
    "data_type": "",
    "length": "",
    "required": "",
    "condition_text": "",
    "aliases_text": ""
  }}
]"""


_V4_EDGE_EXTRACTION_PROMPT = """Given the following enterprise design document and the list of extracted entity nodes, identify ALL relationships between them.

## Project Context
Project: {project_name} (ID: {project_id})
Workbook: {workbook_name}
Sheet: {sheet_name} (Type: {sheet_type})
Source File: {source_file}

## Extracted Node IDs
{node_id_list}

## Document Content
{content}

## Relationship Type Whitelist (use ONLY these)

### Structure / Evidence
BELONGS_TO_PROJECT, HAS_DOCUMENT_GROUP, HAS_WORKBOOK, PROJECT_HAS_WORKBOOK, HAS_SOURCE_DOCUMENT, HAS_SHEET, HAS_SHEET_LIKE_UNIT, HAS_EVIDENCE_UNIT, EXTRACTED_OBJECT, EVIDENCED_BY, DERIVED_FROM, RELATED_TO

### Business / Process
HAS_PROCESS, HAS_STEP, HAS_FUNCTION, CONTAINS_STEP, STARTS_WITH, ENDS_WITH, NEXT_STEP, BRANCHES_TO, HAS_BRANCH_CONDITION, HAS_CONDITION, HAS_DECISION_POINT, HAS_SUB_DECISION, HAS_RESULT_BRANCH, HAS_ANNOTATION, HAS_EXCEPTION_PATH, HAS_OPERATION_TYPE, APPLIES_RULE

### System / Interface / API
USES_SYSTEM, FROM_SYSTEM, TO_SYSTEM, VIA_MIDDLEWARE, HAS_INTERFACE, HAS_API_OPERATION, HAS_API_SEQUENCE, HAS_API_CALL_STEP, CALLS_API, HAS_ENDPOINT, USES_ENDPOINT, SENDS_TO, RECEIVES_FROM, HAS_REQUEST_PAYLOAD, HAS_RESPONSE_PAYLOAD, HAS_PARAMETER

### File / Implementation
HAS_IMPLEMENTATION_SPEC, HAS_SCRIPT_STEP, READS_FILE, WRITES_FILE, READS_DATA, WRITES_DATA, RETURNS_TO, RETURNS_FILE_TO, HAS_RESULT_RETURN, HAS_ERROR_HANDLING

### Data / Mapping / Condition
HAS_RECORD_TYPE, HAS_FIELD, USES_FIELD, HAS_SOURCE_FIELD, HAS_TARGET_FIELD, USES_MAPPING, HAS_MAPPING_ROW, MAPS_TO, TRANSFORMS_TO, LOOKS_UP, CALCULATES, HAS_ENUM_VALUE, HAS_STATUS_VALUE, HAS_RETRIEVAL_CONDITION, HAS_QUERY_CONDITION, HAS_FILTER_CONDITION, FILTERS_BY, SELECTS_FROM

### Quality / Review
HAS_ISSUE, HAS_AMBIGUITY, NEEDS_REVIEW, POSSIBLY_RELATED, DUPLICATE_OF, SAME_AS

## Edge Extraction Rules

1. from_id and to_id MUST match IDs from the Extracted Node IDs list above
2. Every edge needs non-empty evidence_text (short quote, max 80 chars)
3. Preserve edge labels, branch labels, conditions from flowcharts/Mermaid
4. For Mermaid edges:
   - normal arrow -> NEXT_STEP
   - arrow with label -> NEXT_STEP with edge_label/condition_text
   - conditional branch -> BRANCHES_TO / HAS_BRANCH_CONDITION
   - subgraph contains node -> CONTAINS_STEP
   - API call -> CALLS_API
   - file operation -> READS_FILE / WRITES_FILE
   - exception path -> HAS_EXCEPTION_PATH
   - annotation link -> HAS_ANNOTATION
5. P0: CALLS_API must point to APIOperation, NEVER to APIEndpoint.
   Use HAS_ENDPOINT or USES_ENDPOINT to link operations/steps to endpoint URLs.
6. P0: Do NOT create verified cross-document links based only on weak name similarity
7. Confidence rules:
   - explicit table row: 0.90-0.95
   - explicit Mermaid edge: 0.85-0.90
   - explicit section text: 0.83-0.88
   - same row ambiguous: 0.75-0.80
   - same sheet co-occurrence: 0.65-0.70
   - semantic similarity only: <= 0.70 (mark pending)
   - manual inference: <= 0.65 (mark pending)
8. link_method (MUST use exactly one of these):
   - explicit_text: stated in document text
   - explicit_table_row: in same table row
   - explicit_mermaid_edge: Mermaid arrow
   - explicit_code_block: in code/JSON block
   - explicit_metadata: from metadata section
   - code_based_match: matching codes/IDs
   - row_level_match: same data row
   - source_file_path: from file path
   - structural_inference: inferred from structure/order
   - name_similarity: similar names (MUST be pending)
   - semantic_similarity: semantic match (MUST be pending)
   - co_occurrence: appear together (MUST be pending)
   - manual_inference: manually inferred (MUST be pending)
9. Candidate relationships (confidence <= 0.70) must have review_status=pending

Return ONLY a JSON array of edge objects:
[
  {{
    "from_id": "source_node_id",
    "to_id": "target_node_id",
    "type": "RELATIONSHIP_TYPE",
    "edge_label": "label from flowchart arrow or empty",
    "condition_text": "branch condition or empty",
    "branch_label": "yes/no/status label or empty",
    "evidence_text": "short supporting quote max 80 chars",
    "confidence": 0.85,
    "link_method": "explicit_text|explicit_table_row|explicit_mermaid_edge|structural_inference|etc",
    "review_status": "verified|pending",
    "sequence_no": "",
    "layer": "business|process|system|implementation|data|knowledge|evidence|cross_layer"
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
    prompt_version: str | None = None,
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

    # Resolve prompts: use registry if prompt_version specified, else inline defaults
    if prompt_version:
        sys_prompt, node_tmpl, edge_tmpl = _load_prompt_from_registry(prompt_version)
    else:
        sys_prompt, node_tmpl, edge_tmpl = _SYSTEM_PROMPT, _V4_NODE_EXTRACTION_PROMPT, _V4_EDGE_EXTRACTION_PROMPT

    # ── Pass 1: nodes ─────────────────────────────────────────────────────────
    node_prompt = node_tmpl.format(
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
        full_prompt = f"<system>\n{sys_prompt}\n</system>\n\n{node_prompt}"
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
        edge_prompt = edge_tmpl.format(
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
            full_prompt2 = f"<system>\n{sys_prompt}\n</system>\n\n{edge_prompt}"
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
