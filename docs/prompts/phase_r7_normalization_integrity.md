# Phase R7 — Graph Normalization, Deduplication & Integrity Check

## Objective

Normalize, deduplicate, and validate the raw graph extracted in Phase R6.

R7 is a **graph normalization and integrity phase**.

R7 must not write Neptune.  
R7 must not query Neptune.  
R7 must not call Bedrock.  
R7 must not generate embeddings.  
R7 must not write LanceDB.  
R7 must not run QA terminal.  
R7 must not proceed to R8 automatically.

The purpose of R7 is to transform the raw R6 extraction outputs into a clean, canonical, Neptune-ready graph artifact set.

R6 generated:

- 859 raw entities
- 1,044 clean raw relations
- 181 evidence records
- 140 entity dedup candidate groups
- 177 duplicate relation groups
- 0 dangling relations
- 0 extraction failures
- 0 custom relation types
- Q1-Q5 graph coverage passed
- Q4 preview CSV passed with restricted `q4_relation_type`

R7 must produce:

- canonical entities
- canonical relations
- canonical evidence
- entity normalization map
- relation deduplication map
- rejected / pending relations
- Neptune-ready preview artifacts
- Q4 final Semantic Map preview using only `generates`, `depends_on`, `relates_to`

---

## Project Context

Project root:

```text
~/projects/hermes_bedrock_agent
````

Rebuild target:

```text
run_id: murata_rebuild_v1
dataset: murata
future Neptune dataset: murata
future LanceDB collection: murata_e2e_murata_rebuild_v1
```

Previous phases:

```text
R1: target-question-driven sample selection
R2: parse / VLM quality check
R2.5: VLM smoke test + high-priority VLM parsing
R3: structure-aware chunking + chunk purpose classification
R4: summary chunk generation
R5: embedding generation + LanceDB retrieval validation
R6: graph extraction
R6 audit: strict quality gate PASS
```

R6 strict audit result:

```text
R6 PASS: 23/23 gates
Raw entities: 859
Unique entities by name+type: 387
Raw relations: 1,044
Raw evidence: 181
Dedup candidate groups: 140
Duplicate relation groups: 177
Removable duplicate entity instances: 472
Dangling relations: 0
Extraction failures: 0
Custom relation types: 0
relates_to: 2.7%
Mean confidence: 0.962
Q4 continuous path: 13 nodes
```

---

## Control Files to Read

Before executing R7, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r7_normalization_integrity.md`

Also read previous phase prompts if needed:

```text
docs/prompts/phase_r6_graph_extraction.md
docs/prompts/phase_r5_embedding_lancedb.md
docs/prompts/phase_r4_summary_chunks.md
docs/prompts/phase_r3_chunking_quality.md
```

Read R6 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_entities_r6.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_relations_r6.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_evidence_r6.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entity_dedup_candidates_r6.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/suspicious_relations_r6.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/extraction_failures_r6.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/relation_type_distribution_r6.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/target_question_graph_coverage_r6.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/nodes_r6_q4_preview.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/edges_r6_q4_preview.csv
```

Read R6 audit reports:

```text
docs/murata_rebuild_r6_strict_audit_report.md
docs/murata_rebuild_r6_quality_gate_decision.md
docs/murata_rebuild_r6_graph_extraction_report.md
docs/murata_rebuild_r6_target_question_graph_coverage.md
docs/murata_rebuild_r6_relation_quality_report.md
docs/murata_rebuild_r6_dedup_candidates_report.md
docs/murata_rebuild_r6_q4_semantic_map_preview.md
docs/murata_rebuild_r6_next_step_recommendation.md
```

If any file is missing, report it clearly.
Do not continue if critical raw graph files are missing.

---

## R7 Scope

R7 includes:

1. Load raw R6 graph artifacts.
2. Normalize entity names.
3. Generate canonical entity IDs.
4. Deduplicate entity records.
5. Build entity normalization map.
6. Rewrite raw relations to canonical entity IDs.
7. Deduplicate relations.
8. Preserve multi-source evidence and provenance.
9. Validate relation integrity.
10. Separate rejected and pending relations.
11. Generate Neptune-ready preview artifacts.
12. Generate Q4 final Semantic Map preview using `q4_relation_type`.
13. Produce normalization and integrity reports.
14. Update `docs/task_state.md`.

R7 excludes:

1. Neptune query.
2. Neptune write.
3. Bedrock / LLM calls.
4. Embedding generation.
5. LanceDB write.
6. VLM calls.
7. QA answer generation.
8. QA terminal.
9. Final graph import.
10. Proceeding to R8 automatically.

---

## Required Pre-checks

Before normalization, perform these checks:

1. Verify all critical R6 input files exist.
2. Count raw entities, raw relations, raw evidence records.
3. Verify raw relation required fields:

   * source_entity
   * target_entity
   * relation_type
   * source_chunk_id
   * evidence_text
   * confidence
4. Verify no dangling relation before normalization.
5. Verify relation types are in the allowed set.
6. Verify `custom` relation count is 0.
7. Verify `q4_relation_type` exists for Q4 preview relations, if applicable.
8. Verify `run_id=murata_rebuild_v1`.
9. Verify `dataset=murata`.

If pre-check fails, stop and report.

---

## Entity Normalization Rules

R7 must normalize entities conservatively.

### Core Principle

Do **not** over-merge entities across different semantic layers.

For example:

Do merge:

```text
JOURNAL_BASE
JournalBase
journal_base
```

only if they refer to the same logical table/object and type mapping is appropriate.

Do **not** blindly merge:

```text
Table: PAYMENT_REQ
Class: PaymentReq
Action: PaymentReqAction
Service: PaymentReqService
```

These are different implementation-layer entities and should remain separate nodes, connected by relations such as:

```text
references
reads_from
writes_to
calls
maps_to
implements
supports
```

---

## Entity Canonicalization Strategy

Generate a canonical entity ID for each normalized entity.

Recommended format:

```text
ent_<layer>_<type>_<slug>
```

Examples:

```text
ent_data_table_journal_base
ent_data_table_payment_req
ent_data_column_bill_no
ent_system_action_payment_req_action
ent_system_service_payment_req_service
ent_business_step_payment_request_creation
ent_business_process_accounts_payable_flow
ent_external_system_oa
```

Use lowercase slugs.

Normalize:

1. case
2. whitespace
3. full-width / half-width characters
4. punctuation
5. common Java naming variants
6. table/class variants when safe

Examples:

```text
JOURNAL_BASE → journal_base
JournalBase → journal_base
PAYMENT_REQ → payment_req
PaymentReq → payment_req
RECEIVING_JOURNAL → receiving_journal
ReceivingJournal → receiving_journal
SUN_REQUEST → sun_request
SunRequest → sun_request
```

But preserve original names in aliases:

```json
{
  "canonical_name": "JOURNAL_BASE",
  "aliases": ["JournalBase", "journal_base"]
}
```

---

## Entity Type Handling

Allowed canonical entity types:

```text
BusinessProcess
BusinessStep
BusinessObject
BusinessRule
System
Module
Screen
API
Action
Service
ServiceImpl
DAO
Mapper
Class
Method
Table
View
Column
Field
Status
EnumValue
Document
File
ExternalSystem
Interface
Report
Evidence
```

If raw type is unknown or inconsistent, map it to the closest allowed type.

Do not create arbitrary new types unless absolutely necessary.
If a new type is unavoidable, report it in the R7 report.

---

## Layer Handling

Use these layers:

```text
business
system
data
evidence
```

Mapping:

```text
business:
  BusinessProcess, BusinessStep, BusinessObject, BusinessRule, Screen, Report

system:
  System, Module, API, Action, Service, ServiceImpl, DAO, Mapper, Class, Method, Interface, ExternalSystem

data:
  Table, View, Column, Field, Status, EnumValue

evidence:
  Document, File, Evidence
```

If layer is missing in raw entity, infer from entity type.

---

## Entity Merge Rules

### Safe Merge

Merge raw entities if all are true:

1. Same or compatible entity type.
2. Same normalized name / slug.
3. Same layer or compatible layer.
4. No conflict in source semantics.
5. No conflict between table/class/action/service types.

Examples:

```text
JOURNAL_BASE (Table) + journal_base (Table) → merge
PAYMENT_REQ (Table) + payment_req (Table) → merge
BILL_NO (Column) + bill_no (Column) → merge
STATUS (Column) + STATUS (Field) → merge only if context supports same meaning
```

### Do Not Merge

Do not merge if types differ semantically:

```text
PaymentReqAction (Action) ≠ PaymentReqService (Service)
PaymentReq (Class) ≠ PAYMENT_REQ (Table)
JOURNAL_BASE (Table) ≠ JournalBaseAction (Action)
STATUS (Column) ≠ STATUS_PAYMENT (Status) unless evidence supports same concept
```

Instead, create relations:

```text
Class maps_to Table
Action calls Service
Service reads_from Table
Service writes_to Table
Table has_field Column
```

### Ambiguous Merge

If uncertain, do not merge.
Put the group into:

```text
pending_entity_merges_r7.jsonl
```

---

## Canonical Entity Schema

Write canonical entities to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entities_r7.jsonl
```

Each canonical entity must include:

```json
{
  "entity_id": "ent_data_table_journal_base",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "canonical_name": "JOURNAL_BASE",
  "display_name": "JOURNAL_BASE",
  "entity_type": "Table",
  "layer": "data",
  "aliases": ["JournalBase", "journal_base"],
  "description": "...",
  "source_chunk_ids": ["chunk_r3_xxx", "summary_r4_xxx"],
  "source_uris": ["s3://..."],
  "raw_entity_ids": ["raw_ent_xxx"],
  "related_target_questions": ["Q2", "Q3"],
  "properties": {
    "table_name": "JOURNAL_BASE"
  },
  "confidence_max": 0.98,
  "confidence_avg": 0.93,
  "support_count": 3
}
```

---

## Entity Normalization Map Schema

Write normalization map to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entity_normalization_map_r7.jsonl
```

Each line:

```json
{
  "raw_entity_id": "raw_ent_xxx",
  "raw_name": "JournalBase",
  "raw_type": "Class",
  "canonical_entity_id": "ent_system_class_journal_base",
  "canonical_name": "JournalBase",
  "canonical_type": "Class",
  "merge_action": "merged|kept_separate|pending",
  "reason": "same normalized name and compatible type"
}
```

---

## Relation Normalization Rules

R7 must rewrite raw relations to canonical entity IDs.

For each raw relation:

1. Resolve source raw entity to canonical source entity.
2. Resolve target raw entity to canonical target entity.
3. Validate relation type.
4. Preserve original relation type.
5. Preserve `q4_relation_type` if present.
6. Preserve source chunk and evidence.
7. Preserve confidence.
8. Preserve target question mapping.

---

## Relation Deduplication Rules

Deduplicate relations by:

```text
canonical_source_entity_id
relation_type
canonical_target_entity_id
```

Optionally include normalized `q4_relation_type` where relevant.

When merging duplicates, preserve provenance:

```json
{
  "support_count": 8,
  "source_chunk_ids": ["chunk_r3_xxx", "summary_r4_xxx"],
  "evidence_ids": ["raw_ev_xxx"],
  "evidence_texts": ["..."],
  "raw_relation_ids": ["raw_rel_xxx"],
  "confidence_max": 0.98,
  "confidence_avg": 0.91
}
```

Do not lose evidence.

---

## Relation Confidence and Filtering

Default:

```text
Keep relation if confidence >= 0.85
```

Special case:

```text
confidence >= 0.80 may be kept if:
  - relation_type is not generic
  - evidence_text is strong
  - target question coverage depends on it
```

Move to pending or rejected if:

```text
confidence < 0.85 and relation_type = relates_to
missing evidence_text
missing source_chunk_id
missing canonical source or target
unsupported relation type
appears hallucinated
```

R6 audit found 4 low-confidence `relates_to` relations at 0.80.
R7 should evaluate these carefully.

---

## Self-Reference Relation Policy

R6 audit found 5 self-referencing `transitions_to` relations.

These may be valid state-machine transitions.

R7 should keep them only if:

1. relation_type = `transitions_to`
2. entity represents Status / Field / EnumValue
3. evidence clearly describes a state transition

Add metadata:

```json
{
  "relation_semantics": "state_transition",
  "self_reference_allowed": true
}
```

Reject other self-referencing relations unless justified.

---

## Relation Schema

Write normalized relations to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/relations_r7.jsonl
```

Each relation:

```json
{
  "relation_id": "rel_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "source_entity_id": "ent_system_action_payment_req_action",
  "source_entity_name": "PaymentReqAction",
  "source_entity_type": "Action",
  "target_entity_id": "ent_system_service_payment_req_service",
  "target_entity_name": "PaymentReqService",
  "target_entity_type": "Service",
  "relation_type": "calls",
  "q4_relation_type": null,
  "description": "...",
  "source_chunk_ids": ["chunk_r3_xxx"],
  "source_uris": ["s3://..."],
  "evidence_ids": ["ev_xxx"],
  "evidence_texts": ["..."],
  "raw_relation_ids": ["raw_rel_xxx"],
  "related_target_questions": ["Q1", "Q5"],
  "key_fields": ["BILL_NO", "STATUS"],
  "support_count": 1,
  "confidence_max": 0.98,
  "confidence_avg": 0.98,
  "metadata": {
    "relation_semantics": null,
    "self_reference_allowed": false
  }
}
```

---

## Evidence Normalization

Normalize evidence records and link them to canonical entities / relations.

Write to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/evidence_r7.jsonl
```

Each evidence:

```json
{
  "evidence_id": "ev_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "source_chunk_id": "chunk_r3_xxx",
  "source_uri": "s3://...",
  "source_file_name": "...",
  "evidence_text": "...",
  "evidence_type": "schema|code|process|visual|summary|config",
  "supports_entity_ids": ["ent_data_table_journal_base"],
  "supports_relation_ids": ["rel_xxx"],
  "related_target_questions": ["Q2", "Q3"],
  "confidence": 0.95
}
```

---

## Rejected / Pending Outputs

Write rejected relations to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/rejected_relations_r7.jsonl
```

Write pending relations to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/pending_relations_r7.jsonl
```

Write pending entity merges to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/pending_entity_merges_r7.jsonl
```

Each rejected / pending record must include:

```json
{
  "raw_id": "...",
  "reason": "...",
  "recommended_action": "...",
  "source_chunk_id": "...",
  "evidence_text": "..."
}
```

---

## Neptune-Ready Preview

R7 must create Neptune-ready preview files only.
Do not import them.

Create:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_nodes_preview_r7.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edges_preview_r7.csv
```

Suggested `neptune_nodes_preview_r7.csv` columns:

```csv
~id,~label,name,canonical_name,entity_type,layer,run_id,dataset,display_name,aliases,source_chunk_ids,source_uris,confidence_avg,support_count
```

Suggested `neptune_edges_preview_r7.csv` columns:

```csv
~id,~from,~to,~label,relation_type,run_id,dataset,evidence_ids,source_chunk_ids,confidence_avg,support_count
```

Note:

* These are preview files only.
* Final Neptune load belongs to R8.
* Validate CSV escaping.
* Validate no missing `~id`, `~from`, `~to`, `~label`.

---

## Q4 Final Semantic Map Preview

R7 must create Q4 final preview files using only allowed relation types.

Create:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_nodes_final_preview_r7.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_edges_final_preview_r7.csv
```

Q4 nodes columns:

```csv
id,label,type
```

Q4 edges columns:

```csv
from,to,relation
```

Important:

For Q4 edge `relation`, use:

```text
q4_relation_type
```

not original `relation_type`.

Allowed Q4 relations:

```text
generates
depends_on
relates_to
```

R7 must verify:

1. only these three relation values appear
2. at least one continuous path A → B → C → D exists
3. the path covers at least:

```text
订单/外部数据 → 对账单 → 付款申请 → 审批
```

Ideally cover:

```text
订单/外部数据 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表
```

If report remains partial, state clearly.

---

## Integrity Checks

R7 must perform the following checks:

### Entity Integrity

1. No missing `entity_id`.
2. No duplicate canonical `entity_id`.
3. No missing `canonical_name`.
4. No missing `entity_type`.
5. No missing `layer`.
6. Every entity has `run_id` and `dataset`.
7. Every entity has at least one source chunk or source URI, unless justified.

### Relation Integrity

1. No missing `relation_id`.
2. No duplicate canonical relation ID.
3. Every relation source entity exists.
4. Every relation target entity exists.
5. Every relation has allowed `relation_type`.
6. Every relation has evidence.
7. Every relation has source chunk.
8. Every relation has confidence.
9. No unsupported `custom`.
10. `related_to` is not dominant.
11. Self-reference relations are valid state transitions only.

### Evidence Integrity

1. Every evidence record has source chunk.
2. Every evidence record has evidence text.
3. Every evidence record links to at least one entity or relation.
4. Every relation evidence ID exists.
5. Every entity source chunk exists in R3/R4/R5 inputs, where possible.

### Q1-Q5 Coverage Integrity

Verify canonical graph coverage:

```text
Q1: 应付管理流程, steps, tables, fields, code modules
Q2: JOURNAL_BASE role, schema, process, code references
Q3: SUN_REQUEST + JOURNAL_BASE + RECEIVING_JOURNAL, join fields and bridge logic
Q4: Semantic Map preview path and allowed relations
Q5: PAYMENT_REQ, PAYMENT_RECEIVING, STATUS, BILL_NO, approval fields, OA/callback proposed design
```

---

## Required Outputs

Artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required artifact files:

```text
entities_r7.jsonl
relations_r7.jsonl
evidence_r7.jsonl
entity_normalization_map_r7.jsonl
relation_dedup_map_r7.jsonl
rejected_relations_r7.jsonl
pending_relations_r7.jsonl
pending_entity_merges_r7.jsonl
neptune_nodes_preview_r7.csv
neptune_edges_preview_r7.csv
q4_nodes_final_preview_r7.csv
q4_edges_final_preview_r7.csv
normalization_stats_r7.json
integrity_check_r7.json
target_question_graph_coverage_r7.json
```

Reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r7_normalization_report.md
docs/murata_rebuild_r7_integrity_report.md
docs/murata_rebuild_r7_entity_dedup_report.md
docs/murata_rebuild_r7_relation_dedup_report.md
docs/murata_rebuild_r7_q4_semantic_map_final_preview.md
docs/murata_rebuild_r7_neptune_preview_report.md
docs/murata_rebuild_r7_next_step_recommendation.md
```

---

## R7 Quality Gate

R7 passes only if:

1. Raw R6 inputs are loaded.
2. Entity normalization map is created.
3. Canonical entities are created.
4. Canonical relations are created.
5. Canonical evidence records are created.
6. Entity dedup reduces or explains duplicate groups.
7. Relation dedup reduces or explains duplicate groups.
8. No dangling canonical relation exists.
9. No unsupported relation type exists.
10. `custom` relation count remains 0.
11. `related_to` is not dominant.
12. Rejected / pending relations are separated.
13. Low-confidence generic relations are handled.
14. Self-reference relations are only valid state transitions.
15. Q1-Q5 canonical graph coverage is preserved.
16. Q4 final CSV preview uses only `generates`, `depends_on`, `relates_to`.
17. Q4 final preview has at least one A → B → C → D continuous path.
18. Neptune preview CSV files are generated.
19. Neptune preview files have no missing IDs or endpoints.
20. No Neptune query/write occurs.
21. No Bedrock call occurs.
22. No LanceDB write occurs.
23. No embedding or QA execution occurs.

If R7 quality gate fails:

1. do not proceed to R8
2. report failure reasons
3. recommend one of:

   * revise normalization rules
   * adjust entity merge strategy
   * keep more entities separate
   * change confidence threshold
   * return to R6 for targeted re-extraction
   * manually review pending merges

---

## Reporting Requirements

At completion, output a Phase R7 report with:

1. raw entity count
2. canonical entity count
3. raw relation count
4. canonical relation count
5. evidence count
6. rejected relation count
7. pending relation count
8. pending entity merge count
9. entity dedup reduction ratio
10. relation dedup reduction ratio
11. relation type distribution after normalization
12. integrity check summary
13. Q1-Q5 graph coverage summary
14. Q4 final preview status
15. Neptune preview status
16. whether R7 quality gate passed
17. whether R8 Neptune dry-run / import preview is recommended
18. generated files
19. warnings and risks

---

## Forbidden Actions

R7 must not:

1. query Neptune
2. write Neptune
3. call Bedrock
4. generate embeddings
5. write LanceDB
6. run VLM
7. run QA terminal
8. generate final answers
9. delete baseline data
10. proceed to R8 automatically

---

## Allowed Actions

R7 may:

1. read R6 artifacts
2. read R6 audit reports
3. run local deterministic normalization
4. run local deterministic deduplication
5. run local integrity checks
6. create normalized graph artifacts
7. create preview CSV files
8. create reports
9. update `docs/task_state.md`

---

## State Update

After completing R7, update `docs/task_state.md`:

```markdown
## Current Phase

`R7`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entities_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/relations_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/evidence_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entity_normalization_map_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/relation_dedup_map_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/rejected_relations_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/pending_relations_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/pending_entity_merges_r7.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_nodes_preview_r7.csv`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edges_preview_r7.csv`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_nodes_final_preview_r7.csv`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_edges_final_preview_r7.csv`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/normalization_stats_r7.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/integrity_check_r7.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/target_question_graph_coverage_r7.json`
- `docs/murata_rebuild_r7_normalization_report.md`
- `docs/murata_rebuild_r7_integrity_report.md`
- `docs/murata_rebuild_r7_entity_dedup_report.md`
- `docs/murata_rebuild_r7_relation_dedup_report.md`
- `docs/murata_rebuild_r7_q4_semantic_map_final_preview.md`
- `docs/murata_rebuild_r7_neptune_preview_report.md`
- `docs/murata_rebuild_r7_next_step_recommendation.md`

## Latest Findings

Summarize normalization, deduplication, and integrity results.

## Risks / Issues

Summarize pending merges, rejected relations, Q4 limitations, and Neptune preview risks.

## Recommended Next Phase

`R8`

## Next Phase Prompt

`docs/prompts/phase_r8_neptune_dryrun_preview.md`
```

Then stop and wait for user review.

Do not proceed to R8 automatically.
