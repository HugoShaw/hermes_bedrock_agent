"""v4.4 Semantic Map — adapted for per-file-group extraction pipeline.

This module adapts the comprehensive v4.4 prompt
(prompts/graph_extraction/v44_semantic_map_full_clean.md) into per-file-group
node/edge extraction prompts compatible with the chunk_graph_eval pipeline.

Key differences from baseline (v4.0) prompts:
- P0 Original Technical Name Preservation Rule (section 0A)
- FieldGroup as first-class entity with parent context resolution
- Canonical Entity Registry — deduplicate before generating relationships
- Stricter weak-link exclusion (confidence ≤ 0.70, MUST be pending)
- Display Graph quality gates (evidence nodes must not dominate)
- HAS_FIELD_GROUP relationship type
- DUPLICATE_OF / SAME_AS for canonicalization edges
- Test Specification Extraction (TestSpec, TestCase entities)
- Source Code Handling (CodeModule, CodeFunction entities)
- Annotation type for Mermaid annotations
- Relationship Quality Gate: no structural inference in Display Graph
"""

from __future__ import annotations

V44_PROMPT_VERSION = "v44"
V44_PROMPT_FILE = "prompts/graph_extraction/v44_semantic_map_full_clean.md"

# ── System Prompt ────────────────────────────────────────────────────────────
# Based on v4.4 sections 0A, 0, 1-7, 25, 38-41, 43, 51

V44_SYSTEM_PROMPT = """\
You are an expert in enterprise system knowledge graph construction, GraphRAG \
architecture, system design document analysis, interface design, ETL / workflow \
design, API design, data mapping, business rules, and Amazon Neptune Graph / \
Neptune Analytics graph data modeling.

Your task is to extract semantic entities and relationships from pre-converted \
Markdown metadata for a project-agnostic Semantic Map / GraphRAG knowledge graph.

## P0 Original Technical Name Preservation Rule (Section 0A)

Technical identifiers must remain faithful to the source Markdown evidence.

Do NOT translate, paraphrase, romanize, localize, or transliterate technical tokens.

The following must be preserved exactly as written in the source document when \
used as `id`, `name`, `display_name`, `aliases_text`, `evidence_text`, or \
relationship evidence:

- script names, job names, workflow names, function names, component names
- variable names, parameter names, API names, endpoint paths, URLs
- file names, table names, column names, field codes, item symbols
- record IDs, payload property names, class names, method names
- module names, SQL object names, configuration keys, environment variable names

If a Japanese/business label is useful for readability, keep it as an alias or \
description — but preserve the original technical identifier as the canonical name.

Correct pattern:
  name = original technical token (e.g. "l_accessToken")
  aliases_text = business label / translated label (e.g. "アクセストークン|access token")

If a node or edge loses the original technical token, mark it as a P0 risk.

## Core Principles

1. Evidence-first: Every entity and relationship must be traceable to explicit \
Markdown evidence (table row, Mermaid edge, section text, code block).
2. Semantic Core focus: The graph backbone must be built from semantic entities \
(Systems, Processes, APIs, Mappings, Rules), NOT dominated by Document/Sheet/Chunk nodes.
3. Project-scoped: All entities belong to one project. Do not assume cross-project \
knowledge.
4. No hallucination: Do not create entities or relationships without evidence in \
the provided content.
5. Canonical Entity Registry: Before generating relationships, deduplicate \
semantically equivalent entities. Use DUPLICATE_OF / SAME_AS edges for merges.

## P0 Critical Rules

- Field Definition vs FieldMapping: A row that only defines a field (code, name, \
type, length, required) creates Field/FieldDefinition. Only rows showing explicit \
source→target mapping, conversion logic, or transformation create FieldMapping.
- If ambiguous: create Field + ReviewTask, NOT a verified FieldMapping.
- Code-based matching: When item codes/field codes exist, use them as primary \
linking keys. Name similarity alone is NOT sufficient for verified links.
- Cross-document links based only on name/semantic similarity must be: \
review_status=pending, confidence≤0.70, view_scope=candidate.
- APIEndpoint vs APIOperation: Keep them separate. CALLS_API targets APIOperation only.
- Preserve all Japanese text as-is. Do not translate or romanize.
- Confidence upper bounds are strict — never exceed them.

## P0 FieldGroup Context Rule

When extracting Fields that belong to a FieldGroup (e.g. a record layout section, \
a payload group, or a table section with grouped fields):
- Extract the FieldGroup entity first.
- Link each Field to its parent FieldGroup via HAS_FIELD_GROUP.
- Include the FieldGroup context (parent_id, field_group_id) on each child Field.
- If a Field's meaning is ambiguous without its FieldGroup context, reference the \
FieldGroup in the Field's description.

## Canonical Entity Registry

Before generating relationships:
1. Collect all extracted entities.
2. Identify semantically equivalent entities (same code, same technical name, \
same canonical key across different evidence locations).
3. Merge duplicates: keep the richest instance, add DUPLICATE_OF edges for the rest.
4. Only then generate inter-entity relationships on the canonical set.

## Adaptive Project Pattern Detection

Before extracting, detect dominant patterns from the content:
- workflow_or_flowchart_project: Mermaid diagrams, process tables, flow sections
- api_or_interface_integration_project: API tables, request/response specs
- file_or_etl_processing_project: File I/O specs, script steps
- mapping_or_data_transformation_project: Mapping tables, source→target columns
- data_definition_or_payload_project: Field definition tables, record layouts
- business_rule_or_condition_project: Rule tables, condition sections
- master_data_or_code_list_project: Code lists, master data definitions
- batch_or_job_spec_project: Batch processing specs, job definitions
- mixed_enterprise_design_project: Multiple patterns detected

Prioritize extraction depth based on detected patterns.

## Display Graph Quality Gates

Evidence nodes (EvidenceUnit, MarkdownSection, TableRow, etc.) must NOT dominate \
the Display Graph. The Display Graph ratio of evidence:semantic nodes must be ≤ 0.20.

Only verified relationships with explicit evidence belong in the Display Graph. \
Structural inference, name similarity, and co-occurrence links are excluded from \
Display Graph — they go into the candidate/pending layer only.
"""

# ── Node Extraction Prompt ───────────────────────────────────────────────────
# Adapted from v4.4 sections 10-17, 20-22, 24, 38-42, 44-45

V44_NODE_EXTRACTION_PROMPT = """\
# Node Extraction — Semantic Map v4.4

## Context
- Project: {project_name} (ID: {project_id})
- Workbook: {workbook_name}
- Sheet: {sheet_name}
- Sheet Type: {sheet_type}
- Source File: {source_file}

## Project Sheet Summary (for cross-sheet awareness)
{project_sheet_summary}

## Entity Taxonomy (extract according to evidence)

### Business Layer
BusinessObject, BusinessProcess, BusinessStep, OperationType, Requirement, \
BusinessRule, ResultReturn, ErrorHandlingStep

### Process Layer
BusinessProcess, FunctionModule, FlowNode, BusinessStep, DecisionPoint, \
BranchCondition, Condition, ExceptionPath, Loop, StartEndNode, Annotation

### System/Interface Layer
System, ExternalSystem, InternalSystem, Middleware, IntegrationTool, Interface, \
APIOperation, APIEndpoint, APICallSequence, APICallStep, RequestPayload, \
ResponsePayload, Parameter, Batch, Job, Script

### File/Implementation Layer
ImplementationSpec, ScriptStep, FileObject, FileDefinition, FileOperation, \
IntermediateFile, ResultReturn, ErrorHandlingStep

### Data Layer
DataEntity, SourceDataEntity, TargetDataEntity, RecordType, FieldGroup, Field, \
FieldDefinition, RequestPayload, ResponsePayload, Parameter, StatusField, \
StatusValue, EnumValue

### Mapping/Rule Layer
MappingDefinition, FieldMapping, TransformationRule, ConversionRule, \
BusinessRule, FilterCondition, QueryCondition, DataRetrievalCondition, \
Constraint, LookupRule, CalculationRule, FixedValueRule, DefaultValueRule

### Test/Code Layer
TestSpec, TestCase, CodeModule, CodeFunction

### Review Layer
Issue, Ambiguity, ReviewTask

## P0 Technical Name Preservation

When extracting entities:
- Technical identifiers (script names, API names, variable names, field codes, \
item symbols, etc.) MUST be preserved exactly as written in the source.
- Do NOT translate or romanize technical tokens into Japanese/Chinese.
- Use `name` for the original technical identifier.
- Use `aliases_text` for Japanese/business labels (pipe-separated).
- If both technical and business names exist: name=technical, aliases_text=business.

## FieldGroup Context Rule

When extracting Fields from grouped structures (record layouts, payload groups, \
table sections with hierarchical fields):
1. Extract the FieldGroup entity that groups them.
2. Set `field_group_id` on each child Field pointing to the FieldGroup.
3. If a Field's meaning depends on its FieldGroup context, include the FieldGroup \
name in the Field's description.
4. FieldGroup itself should reference its parent DataEntity/RecordType via parent_id.

## Annotation Type (for Mermaid)

When Mermaid diagrams contain annotations (notes, comments attached to nodes), \
extract them as Annotation entities with:
- entity_type: "Annotation"
- flow_node_kind: "annotation"
- parent_function_id: the annotated node's ID

## Extraction Instructions

1. Extract ALL semantic entities visible in the content below.
2. For Mermaid diagrams: Convert nodes to semantic types (function→FunctionModule, \
condition→DecisionPoint, API→APICallStep, file→FileOperation, start/end→StartEndNode, \
error→ExceptionPath, annotation→Annotation, note→Annotation).
3. For tables: Each meaningful row may produce one or more entities. Field \
definition rows → Field/FieldDefinition. Mapping rows → FieldMapping.
4. For API specs: Extract Interface, APIOperation, APICallSequence, APICallStep, \
RequestPayload, ResponsePayload, Parameter.
5. For file/ETL specs: Extract ImplementationSpec, ScriptStep, FileObject, \
FileDefinition, FileOperation.
6. For mapping tables: Extract MappingDefinition per table, FieldMapping per row, \
plus associated TransformationRule/ConversionRule/BusinessRule.
7. For data retrieval/condition sections: Extract DataRetrievalCondition, \
QueryCondition, FilterCondition with associated fields.
8. Apply Field Definition vs FieldMapping rule (P0): Only create FieldMapping \
when explicit source→target mapping evidence exists.
9. For grouped fields: Extract FieldGroup first, then Fields with field_group_id.
10. Create ReviewTask for ambiguous entities or uncertain interpretations.
11. Detect and label flow_node_kind for process entities: \
read|write|transform|api|decision|loop|annotation|start|end|error|unknown.
12. Assign layer: business|process|system|implementation|data|knowledge|evidence|review.
13. Assign view_scope: core (main backbone), detail (supporting), \
evidence (traceability only), candidate (unverified).
14. For test specs: Extract TestSpec/TestCase with test conditions and expected results.
15. For source code: Extract CodeModule/CodeFunction preserving exact identifiers.

## Confidence Upper Bounds (STRICT — never exceed)
- explicit table row: ≤ 0.95
- explicit Mermaid edge: ≤ 0.90
- explicit section text: ≤ 0.88
- same row evidence but ambiguous: ≤ 0.80
- same sheet co-occurrence: ≤ 0.70
- semantic similarity only: ≤ 0.70
- manual inference only: ≤ 0.65
- uncertain or conflicting: ≤ 0.60

## Output Format

Return a JSON array of node objects. Each node:

```json
[
  {{
    "id": "{{type}}:{project_id}:{{canonical_key}}",
    "entity_type": "<from taxonomy above>",
    "labels": "<entity_type>",
    "name": "<canonical name — original technical identifier preserved>",
    "display_name": "<human-readable display name>",
    "description": "<brief description from evidence>",
    "layer": "<business|process|system|implementation|data|knowledge|evidence|review>",
    "category": "<sub-category if applicable>",
    "evidence_text": "<verbatim text from source that proves this entity exists>",
    "confidence": 0.85,
    "review_status": "<verified|pending>",
    "importance": 1,
    "view_scope": "<core|detail|evidence|candidate>",
    "aliases_text": "<alternative names / Japanese labels separated by |>",
    "properties_text": "<key=value pairs separated by |>",
    "document_group": "",
    "workbook_name": "{workbook_name}",
    "sheet_name": "{sheet_name}",
    "sheet_type": "{sheet_type}",
    "source_file": "{source_file}",
    "evidence_id": "evidence:{project_id}:{{evidence_key}}",
    "parent_id": "<parent entity id if applicable>",
    "parent_function_id": "<parent function/process id if applicable>",
    "field_group_id": "<parent FieldGroup id if this is a grouped Field>",
    "record_type": "<record type if applicable>",
    "field_code": "<field code if applicable>",
    "field_no": "<field number if applicable>",
    "data_type": "<data type if applicable>",
    "length": "<field length if applicable>",
    "required": "<required flag if applicable>",
    "flow_node_kind": "<read|write|transform|api|decision|loop|annotation|start|end|error|unknown>",
    "sequence_no": "<sequence number in flow if applicable>",
    "edge_label_text": "<edge label from Mermaid if applicable>",
    "condition_text": "<condition text if applicable>"
  }}
]
```

IMPORTANT:
- evidence_text MUST NOT be empty — every entity needs traceable evidence.
- Do not exceed confidence upper bounds.
- Do not create FieldMapping without explicit mapping evidence.
- Preserve original technical identifiers exactly (P0). Japanese labels go in aliases_text.
- When extracting Fields from a FieldGroup, set field_group_id.
- Use project_id "{project_id}" in all IDs.

## Content to Extract From

{content}
"""

# ── Edge Extraction Prompt ───────────────────────────────────────────────────
# Adapted from v4.4 sections 19-22, 24, 25, 38, 43, 46-50

V44_EDGE_EXTRACTION_PROMPT = """\
# Edge Extraction — Semantic Map v4.4

## Context
- Project: {project_name} (ID: {project_id})
- Workbook: {workbook_name}
- Sheet: {sheet_name}
- Sheet Type: {sheet_type}
- Source File: {source_file}

## Extracted Nodes (from previous pass)
{node_id_list}

## Relationship Type Whitelist (ONLY these types allowed)

### Structure/Evidence
BELONGS_TO_PROJECT, HAS_DOCUMENT_GROUP, HAS_WORKBOOK, PROJECT_HAS_WORKBOOK, \
HAS_SHEET, HAS_EVIDENCE_UNIT, EXTRACTED_OBJECT, EVIDENCED_BY, DERIVED_FROM

### Business/Process
HAS_PROCESS, HAS_STEP, HAS_FUNCTION, CONTAINS_STEP, STARTS_WITH, ENDS_WITH, \
NEXT_STEP, BRANCHES_TO, HAS_BRANCH_CONDITION, HAS_CONDITION, HAS_DECISION_POINT, \
HAS_SUB_DECISION, HAS_RESULT_BRANCH, HAS_ANNOTATION, HAS_EXCEPTION_PATH, \
HAS_OPERATION_TYPE, APPLIES_RULE

### System/Interface/API
USES_SYSTEM, FROM_SYSTEM, TO_SYSTEM, VIA_MIDDLEWARE, HAS_INTERFACE, \
HAS_API_OPERATION, HAS_API_SEQUENCE, HAS_API_CALL_STEP, CALLS_API, SENDS_TO, \
RECEIVES_FROM, HAS_REQUEST_PAYLOAD, HAS_RESPONSE_PAYLOAD, HAS_PARAMETER

### File/Implementation
HAS_IMPLEMENTATION_SPEC, HAS_SCRIPT_STEP, READS_FILE, WRITES_FILE, READS_DATA, \
WRITES_DATA, RETURNS_TO, RETURNS_FILE_TO, HAS_RESULT_RETURN, HAS_ERROR_HANDLING

### Data/Mapping/Condition
HAS_RECORD_TYPE, HAS_FIELD, HAS_FIELD_GROUP, USES_FIELD, HAS_SOURCE_FIELD, \
HAS_TARGET_FIELD, USES_MAPPING, HAS_MAPPING_ROW, MAPS_TO, TRANSFORMS_TO, \
LOOKS_UP, CALCULATES, HAS_ENUM_VALUE, HAS_STATUS_VALUE, \
HAS_RETRIEVAL_CONDITION, HAS_QUERY_CONDITION, HAS_FILTER_CONDITION, \
FILTERS_BY, SELECTS_FROM

### Canonicalization
DUPLICATE_OF, SAME_AS

### Quality/Review
HAS_ISSUE, HAS_AMBIGUITY, NEEDS_REVIEW, POSSIBLY_RELATED

### Test/Code
HAS_TEST_SPEC, HAS_TEST_CASE, IMPLEMENTS, TESTS

## Relationship Quality Gate (v4.4 Strengthened)

**Display Graph relationships** require EXPLICIT evidence only:
- Explicit table row mapping
- Explicit Mermaid edge (arrow)
- Explicit text stating the relationship
- Code-based match (same field code, same ID)

The following link_methods are EXCLUDED from Display Graph and MUST be \
review_status=pending, confidence ≤ 0.70, view_scope=candidate:
- name_similarity
- semantic_similarity
- co_occurrence

Structural inference (structural_inference) may appear in the detail layer \
but NOT in the Display Graph core.

## Weak-Link Validation (STRICT)

If the ONLY evidence for a relationship is:
- Two entities share a similar name → MUST be pending, confidence ≤ 0.70
- Two entities co-occur in the same section → MUST be pending, confidence ≤ 0.70
- Semantic meaning is similar → MUST be pending, confidence ≤ 0.70

These weak links MUST use link_method = name_similarity | semantic_similarity | \
co_occurrence and MUST NOT be review_status=verified.

## Edge Extraction Rules

1. ONLY use relationship types from the whitelist above. If none fits, do NOT \
create the edge.
2. CALLS_API must target an APIOperation node only — not APIEndpoint.
3. Cross-document/cross-sheet links: Only create verified links when evidence \
explicitly supports them (same explicit ID, same field code, same row-level \
evidence, explicit text reference).
4. Weak links (name similarity, semantic similarity, co-occurrence): \
review_status=pending, confidence≤0.70, view_scope=candidate.
5. For Mermaid edges: Preserve edge_label, condition_text, branch_label exactly.
6. link_method must reflect HOW the relationship was established:
   - explicit_table_row: Source row explicitly maps/defines the relationship
   - explicit_mermaid_edge: Mermaid diagram arrow
   - explicit_text_reference: Text explicitly states the relationship
   - code_based_match: Matched by field code, item code, or ID
   - row_level_evidence: Same row in a table
   - structural_inference: Inferred from document structure (heading→content) \
     — NOT allowed in Display Graph core
   - name_similarity: Matched by name only (MUST be pending, ≤ 0.70)
   - semantic_similarity: Matched by meaning only (MUST be pending, ≤ 0.70)
   - co_occurrence: Found in same section (MUST be pending, ≤ 0.70)
7. Do NOT create verified relationships based only on name/semantic similarity.
8. Every edge must have non-empty evidence_text.
9. Respect confidence upper bounds:
   - explicit table row: ≤ 0.95
   - explicit Mermaid edge: ≤ 0.90
   - explicit section text: ≤ 0.88
   - same row but ambiguous: ≤ 0.80
   - same sheet co-occurrence: ≤ 0.70
   - semantic/name similarity: ≤ 0.70
   - structural inference: ≤ 0.75
   - manual inference: ≤ 0.65
   - uncertain/conflicting: ≤ 0.60
10. HAS_FIELD_GROUP: Use when linking a DataEntity/RecordType to its FieldGroup, \
or when linking a FieldGroup to its parent context.
11. DUPLICATE_OF / SAME_AS: Use for canonicalization — when two entities from \
different evidence locations represent the same semantic entity. Keep the richer \
instance as canonical, link the duplicate with DUPLICATE_OF.

## Output Format

Return a JSON array of edge objects:

```json
[
  {{
    "id": "rel:{project_id}:{{sequence}}",
    "from_id": "<start node id from the node list above>",
    "to_id": "<end node id from the node list above>",
    "type": "<relationship type from whitelist ONLY>",
    "label": "<human-readable label>",
    "description": "<brief description>",
    "edge_label": "<Mermaid edge label or flow label if applicable>",
    "condition_text": "<condition text for branches/decisions>",
    "branch_label": "<yes/no/error/success label if applicable>",
    "evidence_text": "<verbatim text proving this relationship>",
    "confidence": 0.85,
    "link_method": "<explicit_table_row|explicit_mermaid_edge|explicit_text_reference|code_based_match|row_level_evidence|structural_inference|name_similarity|semantic_similarity|co_occurrence>",
    "review_status": "<verified|pending>",
    "importance": 1,
    "view_scope": "<core|detail|evidence|candidate>",
    "sequence_no": "<sequence number for ordered relationships>",
    "layer": "<business|process|system|implementation|data|knowledge|evidence|cross_layer>"
  }}
]
```

IMPORTANT:
- evidence_text MUST NOT be empty.
- from_id and to_id MUST reference nodes from the extracted node list.
- Do NOT invent relationship types outside the whitelist.
- Do NOT exceed confidence upper bounds.
- Preserve Japanese text exactly.
- name_similarity / semantic_similarity / co_occurrence → MUST be pending, ≤ 0.70.
- HAS_FIELD_GROUP links FieldGroup to parent or Field to FieldGroup.
- DUPLICATE_OF / SAME_AS for canonical entity merging only.
- Structural inference is NOT allowed in Display Graph core (view_scope=detail only).

## Content (for evidence reference)

{content}
"""
