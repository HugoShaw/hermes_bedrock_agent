"""v4.5.1 Semantic Map Final — adapted for per-file-group extraction pipeline.

This module adapts the comprehensive v4.5.1 Final prompt with External Rules
(prompts/graph_extraction/v451_semantic_map.md +
 rules/semantic_map_v4_5_1_external_extraction_rules_EN.md)
into per-file-group node/edge extraction prompts compatible with the
chunk_graph_eval pipeline.

Key v4.5.1 changes from v4.5:
- Updated external extraction rules with v4.5.1 Operational Addendum
- Explicit Stable Raw ID and Endpoint Reference Contract (P0 § 5.8)
- Relationship Preservation Contract (P0 § 5.9)
- Mandatory Edge Promotion Diagnostics (P0 § 5.10)
- Mandatory Relationship Candidate Extraction (Phase C2)
- Zero-Count Coverage Gate (§ F)
- USES_SYSTEM relationship in whitelist
- Stricter canonicalization endpoint identity fields:
  from_canonical_key, to_canonical_key, from_name, to_name
- Output dir: {OUTPUT_ROOT}/semantic_map_v4_5_1/
"""

from __future__ import annotations
from pathlib import Path

V451_PROMPT_VERSION = "v4.5.1"
V451_PROMPT_FILE = "prompts/graph_extraction/v451_semantic_map.md"
V451_EXTERNAL_RULES_FILE = "rules/semantic_map_v4_5_1_external_extraction_rules_EN.md"

# Load external rules content at import time
_RULES_PATH = Path(__file__).resolve().parents[3] / V451_EXTERNAL_RULES_FILE
_EXTERNAL_RULES_CONTENT = ""
if _RULES_PATH.exists():
    _EXTERNAL_RULES_CONTENT = _RULES_PATH.read_text(encoding="utf-8")

# ── System Prompt ────────────────────────────────────────────────────────────
# Combines the main prompt's role/principles with the full external rules

V451_SYSTEM_PROMPT = f"""\
You are an expert in enterprise system knowledge graph construction, GraphRAG \
architecture, enterprise project document analysis, business process modeling, \
interface design, ETL / workflow design, API design, data mapping, business rules, \
network / infrastructure modeling, and Amazon Neptune Graph / Neptune Analytics \
graph data modeling.

Your task is to extract semantic entities and relationships from pre-converted \
Markdown metadata for a project-scoped Semantic Map / GraphRAG knowledge graph \
(v4.5.1 Final with External Rules).

## Core Execution Principles

```text
Extract what exists.
Do not extract what does not exist.
Preserve original technical names exactly as written in the source documents.
Canonicalize semantically equivalent entities before generating relationships.
Put uncertain or weakly inferred knowledge into pending/candidate, not verified Display Graph.
Do not compress detailed evidence into only high-level summary nodes.
```

## P0 Non-Negotiable Rules

1. Evidence First: Every verified semantic node/relationship must have source_file, \
evidence_id, evidence_text, project_name, project_id, confidence, review_status, view_scope.
2. Detail Preservation: Do not compress detailed evidence into only parent summary nodes.
3. No Label-Name-Only Classification: Classification must use source evidence text, \
document context, table headers, row context, original technical tokens, and the external rules.
4. External Rule Lookup Required: For every candidate node/relationship, look up the \
label/relationship in the External Extraction Rules below and apply its conditions.
5. Process Granularity: BusinessProcess > FunctionModule > BusinessStep > FlowNode hierarchy.
6. Specific Label Priority: Use the most specific correct label (APICallStep over BusinessStep, etc.).
7. Candidate/ReviewTask Safety: If evidence exists but cannot be safely mapped, create \
candidate or ReviewTask. Do not silently drop.
8. Stable Raw ID and Endpoint Reference Contract: Every raw node must include id, \
stable_raw_id, canonical_key. Every relationship must reference endpoints via raw node id \
AND from_canonical_key/to_canonical_key for post-processing resolution.
9. Relationship Preservation Contract: Every verified raw relationship must be either \
promoted into final semantic edges OR preserved as unresolved_edge_endpoint/candidate_review item. \
Silent deletion is prohibited.
10. Mandatory Edge Promotion Diagnostics: Before final graph generation, verify no verified \
relationship type is reduced to zero without explanation.

## Rule Precedence

```text
1. P0 rules, source boundary, evidence requirements, and preflight gates (this prompt)
2. External Extraction Rules (below)
3. Model judgment
```

## External Extraction Rules

{_EXTERNAL_RULES_CONTENT}

## Node Schema (Required Fields)

```text
id, label, name, display_name, stable_raw_id, canonical_key,
project_name, project_id, source_file,
evidence_id, evidence_text, confidence, review_status, view_scope
```

Optional: aliases_text, description, entity_type, layer, source_file_normalized, \
source_dir, document_group, workbook_name, sheet_name, sheet_index, section_title, \
original_text, original_technical_name, canonical_id, raw_ids.

## Relationship Schema (Required Fields)

```text
id, type, from, to, from_label, from_name, from_canonical_key,
to_label, to_name, to_canonical_key,
project_name, project_id, source_file,
evidence_id, evidence_text, link_method, confidence, review_status, view_scope
```

Optional: source_file_normalized, document_group, workbook_name, \
sheet_name, edge_label, condition_text, branch_label, canonical_from, canonical_to, \
raw_relationship_ids.

## State Enums

- link_method: exact_evidence | explicit_reference | table_row_mapping | visual_edge | \
structured_visual_edge | code_reference | config_reference | canonical_alias | \
document_reference | cross_sheet_reference | cross_document_reference | \
structural_inference | weak_similarity
- review_status: verified | pending | rejected | needs_review
- view_scope: display | full | candidate | evidence_only

## Hard Gates

- weak_similarity must NOT enter verified Display Graph.
- pending/rejected/needs_review must NOT enter verified Display Graph.
- candidate and evidence_only must NOT enter verified Display Graph.
- CALLS_API must point to APIOperation, NOT APIEndpoint.
- FieldDefinition rows must NOT become FieldMapping.
- MappingDefinition must NOT be created from section headers alone.
- Silent deletion of verified relationships is prohibited.
"""

# ── Node Extraction Prompt ───────────────────────────────────────────────────

V451_NODE_EXTRACTION_PROMPT = """\
## Task: Extract Semantic Nodes

Analyze the following enterprise design document and extract ALL semantic entities \
as a JSON array following the v4.5.1 Final extraction rules.

### Project Context
- project_name: {project_name}
- project_id: {project_id}
- workbook_name: {workbook_name}
- sheet_name: {sheet_name}
- sheet_type: {sheet_type}
- source_file: {source_file}

### Project Sheet Overview (for cross-reference context)
{project_sheet_summary}

### Extraction Instructions

1. For every candidate entity, look up its Label in the External Extraction Rules \
(Label Rules section in the system prompt).
2. Apply Role/Granularity, Extraction Condition, Required Evidence, and Do Not Create rules.
3. If evidence satisfies the rule, create a verified node (review_status=verified).
4. If evidence is uncertain, create candidate (review_status=pending, view_scope=candidate).
5. Use the most specific correct label (APICallStep > BusinessStep when API call evidence exists).
6. Preserve original Japanese/technical names in name/display_name fields.
7. Do NOT compress detailed rows into only parent nodes.
8. Include stable_raw_id and canonical_key for every node (critical for edge endpoint resolution).

### Process Hierarchy (Critical)
- BusinessProcess = complete business flow / workflow / lifecycle container
- FunctionModule = named functional block / subflow inside a BusinessProcess
- BusinessStep = one concrete action inside a BusinessProcess or FunctionModule
- FlowNode = visible/procedural node from flowchart / Mermaid / visual evidence

### Output Format

Return a JSON array of node objects. Each node must include at minimum:
```json
[
  {{
    "id": "<project_id>:<label>:<unique_key>",
    "stable_raw_id": "<project_id>|<label>|<normalized_name>|<source_scope>",
    "canonical_key": "<label>|<normalized_name>|<technical_context>",
    "label": "<from allowed labels>",
    "name": "<original technical name>",
    "display_name": "<readable name>",
    "aliases_text": "<pipe-separated aliases if any>",
    "entity_type": "<label>",
    "project_name": "<project_name>",
    "project_id": "<project_id>",
    "source_file": "<source_file>",
    "sheet_name": "<sheet_name>",
    "evidence_id": "evidence:<project_id>:<doc>:<sheet>:<section>:<row>",
    "evidence_text": "<exact source text supporting this entity>",
    "confidence": 1.0,
    "review_status": "verified",
    "view_scope": "display"
  }}
]
```

### Document Content

{content}

### Response

Return ONLY the JSON array of extracted nodes. No explanations."""

# ── Edge Extraction Prompt ───────────────────────────────────────────────────

V451_EDGE_EXTRACTION_PROMPT = """\
## Task: Extract Semantic Relationships

Given the following enterprise design document and extracted nodes, identify ALL \
relationships between them following the v4.5.1 Final extraction rules.

### Project Context
- project_name: {project_name}
- project_id: {project_id}
- workbook_name: {workbook_name}
- sheet_name: {sheet_name}
- sheet_type: {sheet_type}
- source_file: {source_file}

### Extracted Nodes
{node_id_list}

### Extraction Instructions

1. For every candidate relationship, look up the Relationship Type in the External \
Extraction Rules (Relationship Rules section in the system prompt).
2. Verify Typical From, Typical To, Extraction Condition, and Gate.
3. If evidence supports direction, type, and both endpoints, create verified relationship.
4. If evidence is weak or link_method would be weak_similarity, create candidate.
5. Use ONLY whitelisted relationship types. If no type fits, create ReviewTask.
6. CALLS_API must point to APIOperation (not APIEndpoint).
7. Preserve evidence_text for every relationship.
8. CRITICAL: Reference endpoints via their raw node IDs from the Extracted Nodes list above. \
Also provide from_canonical_key and to_canonical_key for post-processing endpoint resolution. \
Do not use vague natural-language references as endpoints.
9. Phase C2 Mandatory Extraction: When evidence shows arrows, containment, ordered steps, \
mapping rows, field ownership, API calls — create relationship candidates before validation.

### Relationship Types (Whitelisted)

Structure: HAS_DOCUMENT_GROUP, HAS_SOURCE_DOCUMENT, PROJECT_HAS_WORKBOOK, HAS_SHEET, \
HAS_EVIDENCE_UNIT, DERIVED_FROM, EVIDENCED_BY, EXTRACTED_OBJECT

Business/Process: HAS_PROCESS, HAS_FUNCTION, HAS_STEP, HAS_OPERATION_TYPE, CONTAINS_STEP, \
STARTS_WITH, ENDS_WITH, NEXT_STEP, HAS_DECISION_POINT, HAS_BRANCH_CONDITION, HAS_CONDITION, \
HAS_SUB_DECISION, HAS_RESULT_BRANCH, BRANCHES_TO, HAS_EXCEPTION_PATH, HAS_ERROR_HANDLING, \
HAS_RESULT_RETURN, HAS_ANNOTATION, APPLIES_RULE

System/API: HAS_INTERFACE, FROM_SYSTEM, TO_SYSTEM, VIA_MIDDLEWARE, SENDS_TO, RECEIVES_FROM, \
CONNECTS_TO, HAS_API_SEQUENCE, HAS_API_CALL_STEP, HAS_API_OPERATION, CALLS_API, HAS_ENDPOINT, \
USES_ENDPOINT, HAS_REQUEST_PAYLOAD, HAS_RESPONSE_PAYLOAD, HAS_PARAMETER, USES_SYSTEM

File/Implementation: HAS_IMPLEMENTATION_SPEC, HAS_SCRIPT_STEP, READS_FILE, WRITES_FILE, \
READS_DATA, WRITES_DATA, USES_MAPPING, RETURNS_FILE_TO

Data/Mapping: HAS_RECORD_TYPE, HAS_FIELD, HAS_MAPPING_ROW, HAS_SOURCE_FIELD, HAS_TARGET_FIELD, \
MAPS_TO, USES_FIELD, TRANSFORMS_TO, CALCULATES, LOOKS_UP, HAS_FILTER_CONDITION, \
HAS_QUERY_CONDITION, HAS_RETRIEVAL_CONDITION, SELECTS_FROM, FILTERS_BY, HAS_STATUS_VALUE, \
HAS_ENUM_VALUE

Network: HAS_NETWORK_TOPOLOGY, HAS_NETWORK_ZONE, CONTAINS_NETWORK_RESOURCE, \
HAS_SECURITY_BOUNDARY, HAS_SUBNET, HAS_VLAN, HAS_IP_RANGE, HAS_IP_ADDRESS, \
BELONGS_TO_NETWORK, USES_PROTOCOL_PORT, PROTECTED_BY, HAS_ACL_RULE, ALLOWS_TRAFFIC, \
DENIES_TRAFFIC, HAS_SECURITY_GROUP, ROUTES_TO, HAS_ROUTE, RESOLVES_TO, BALANCES_TO, \
PROXIES_TO, HAS_CERTIFICATE, USES_VPN, USES_DIRECT_CONNECT, DEFINES_RESOURCE, \
DEPLOYS_RESOURCE, PROTECTS

Quality: HAS_ISSUE, HAS_AMBIGUITY, NEEDS_REVIEW, POSSIBLY_RELATED

### Output Format

Return a JSON array of relationship objects:
```json
[
  {{
    "id": "<project_id>:rel:<unique_key>",
    "type": "<RELATIONSHIP_TYPE from whitelist>",
    "from": "<source node id from Extracted Nodes>",
    "to": "<target node id from Extracted Nodes>",
    "from_label": "<source node label>",
    "from_name": "<source node name>",
    "from_canonical_key": "<source node canonical_key>",
    "to_label": "<target node label>",
    "to_name": "<target node name>",
    "to_canonical_key": "<target node canonical_key>",
    "project_name": "<project_name>",
    "project_id": "<project_id>",
    "source_file": "<source_file>",
    "evidence_id": "evidence:<project_id>:<doc>:<sheet>:<section>:<row>",
    "evidence_text": "<exact source text supporting this relationship>",
    "link_method": "<from allowed link_methods>",
    "confidence": 1.0,
    "review_status": "verified",
    "view_scope": "display"
  }}
]
```

### Document Content

{content}

### Response

Return ONLY the JSON array of extracted relationships. No explanations."""
