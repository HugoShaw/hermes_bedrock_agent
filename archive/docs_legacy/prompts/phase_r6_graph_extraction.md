# Phase R6 — Graph Extraction from Rebuild Evidence Chunks

## Objective

Extract graph entities, relations, and evidence records from the validated Murata rebuild chunks.

R6 is a **graph extraction only** phase.

R6 must not write Neptune.  
R6 must not query Neptune.  
R6 must not run normalization / dedup as a destructive process.  
R6 must not run hybrid QA.  
R6 must not run QA terminal.  
R6 must not proceed to R7 automatically.

The purpose of R6 is to answer one key question:

> Can the current R3/R4 evidence chunks produce a clean, useful, target-question-aligned knowledge graph before we normalize and load it into Neptune?

If R6 graph extraction quality is poor, stop and recommend prompt/schema/input improvements before moving forward.

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
```

R5 successfully validated:

```text
Embedding model: amazon.titan-embed-text-v2:0
LanceDB collection: murata_e2e_murata_rebuild_v1
Vector records: 51
Retrieval validation: 100% top-5 / top-10 success across Q1-Q5
```

Now R6 should extract graph data from the same high-quality evidence chunks.

---

## Control Files to Read

Before executing R6, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r6_graph_extraction.md`

Also read previous phase prompts if needed:

```text
docs/prompts/phase_r3_chunking_quality.md
docs/prompts/phase_r4_summary_chunks.md
docs/prompts/phase_r5_embedding_lancedb.md
```

Read R5/R4/R3 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_input_candidates_r4.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunks_r3.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_chunks_r4.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_records_r5.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/retrieval_metrics_r5.json
```

Read reports if needed:

```text
docs/murata_rebuild_r5_retrieval_quality_report.md
docs/murata_rebuild_r4_summary_quality_report.md
docs/murata_rebuild_r4_target_question_summary_coverage.md
docs/murata_rebuild_process_chain_evidence_report.md
```

---

## Required Pre-checks

Before graph extraction, perform these checks.

### 1. Confirm Text LLM Model

R6 should use the latest configured text LLM model.

Preferred model:

```text
jp.anthropic.claude-sonnet-4-6
```

Check `.env` / project settings for:

```text
TEXT_LLM_MODEL_ID
BEDROCK_MODEL_ID
```

or any project-specific text model setting.

R6 must report:

* actual text LLM model ID used
* env var source
* AWS region
* whether Bedrock client initialized successfully
* whether inference profile is used

If the project still points to an older Sonnet model, report it clearly.

Do not silently switch models unless allowed by configuration.
If `jp.anthropic.claude-sonnet-4-6` is configured and available, use it.

### 2. Validate Graph Extraction Inputs

Load graph extraction input candidates from:

```text
embedding_input_candidates_r4.jsonl
```

Select only records where:

```text
should_extract_graph = true
```

If `should_extract_graph` is missing, infer from:

```text
chunk_purpose
summary_type
source
expected_entities
related_target_questions
```

Default inclusion:

```text
include:
  schema_evidence
  process_evidence
  code_evidence
  config_evidence if it links Action/Service/DAO/Model
  R4 summaries with candidate_graph_nodes / candidate_graph_edges
  semantic_map_summary
  oa_migration_summary

exclude:
  data_sample
  low_value
  embedding-only visual chunks without entity/relation content
```

R6 must report:

* total input candidates loaded
* selected for graph extraction
* excluded candidates
* exclusion reasons

### 3. Validate Target Question Mapping

Use original Q1–Q5 meanings:

```text
Q1: 应付管理业务流程
Q2: JOURNAL_BASE 表作用
Q3: SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联
Q4: 应付管理完整业务流程 Semantic Map
Q5: 付款申请审批迁移到 OA 的系统改造方案
```

Do not use shifted or rewritten meanings.

---

## Target QA Questions

Graph extraction must be aligned to the five target QA questions.

### Q1. 应付管理业务流程

请描述应付管理的业务流程，并要求：

1. 每个流程步骤对应的数据库表
2. 每个步骤涉及的关键字段
3. 如有对应代码模块，请指出类或方法

### Q2. JOURNAL_BASE 表作用

JOURNAL_BASE 表在系统中的作用是什么？

请结合：

1. 表结构
2. 相关业务流程
3. 调用该表的代码模块进行说明

### Q3. SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联

SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三张表之间，在没有外键的情况下：

1. 通过哪些字段形成关联
2. 这些关联在代码中是如何体现的，如 SQL 或 Mapper
3. 在业务流程中的数据流转路径

### Q4. 应付管理完整业务流程 Semantic Map

请围绕“应付管理完整业务流程”，构建一个 Semantic Map，输出 Neptune CSV。

已知业务主流程为：

```text
订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表
```

要求：

1. 必须覆盖以上完整流程链，不得缺失步骤
2. 输出 `nodes.csv`，字段：`id,label,type`
3. 输出 `edges.csv`，字段：`from,to,relation`
4. 关系仅允许：

   * `generates`
   * `depends_on`
   * `relates_to`
5. 必须体现一条清晰主链，至少包含连续路径 A → B → C → D
6. 不要解释，只输出 CSV

### Q5. 付款申请审批迁移到 OA 的系统改造方案

当前系统中，付款申请在应付系统内完成审批。

现在需要进行系统改造：

* 做单仍在应付系统，Payment Request
* 审批流程迁移到 OA 系统
* 审批完成后，审批结果需要回写应付系统

请完成以下内容：

1. 设计新的业务流程
2. 描述数据流转关系
3. 给出系统改造清单
4. 说明对现有业务流程的影响

---

## R6 Scope

R6 includes:

1. select graph extraction input chunks
2. run LLM-based graph extraction
3. generate raw entity records
4. generate raw relation records
5. generate raw evidence records
6. validate extraction format
7. check target-question graph coverage
8. check relation type distribution
9. identify duplicate entity candidates
10. identify suspicious or low-confidence relations
11. recommend whether to proceed to R7 normalization / integrity

R6 excludes:

1. Neptune write
2. Neptune query
3. graph normalization as a destructive final process
4. graph dedup as final merge
5. LanceDB write
6. embedding generation
7. VLM calls
8. QA answer generation
9. QA terminal
10. proceeding to R7 automatically

---

## Graph Schema Design

R6 must extract graph data using controlled node and edge schemas.

### Node Types

Allowed node types:

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

Do not create arbitrary node types unless clearly justified.

If unsure, map to the closest allowed type and add a warning.

### Relation Types

Allowed general relation types:

```text
contains
references
reads_from
writes_to
calls
depends_on
belongs_to
implements
supports
generates
relates_to
maps_to
has_field
has_status
transitions_to
joins_on
flows_to
approves
rejects
updates
exports
imports
```

Avoid generic `custom`.

Avoid using `related_to` unless no more specific relation is possible.

### Q4 Semantic Map Relation Restriction

For Q4 Semantic Map output candidates, relation types must be restricted to:

```text
generates
depends_on
relates_to
```

If the extracted relation uses a richer relation type, also provide a normalized Q4 relation mapping:

```json
{
  "original_relation": "flows_to",
  "q4_relation": "generates"
}
```

---

## Entity Record Schema

Write raw entities to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_entities_r6.jsonl
```

Each entity record must include:

```json
{
  "entity_id": "raw_ent_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "name": "JOURNAL_BASE",
  "canonical_name": "JOURNAL_BASE",
  "display_name": "JOURNAL_BASE",
  "entity_type": "Table",
  "layer": "business|system|data|evidence",
  "description": "...",
  "source_chunk_id": "chunk_or_summary_id",
  "source_uri": "s3://...",
  "source_file_name": "...",
  "related_target_questions": ["Q2", "Q3"],
  "aliases": ["..."],
  "properties": {
    "table_name": "...",
    "class_name": "...",
    "method_name": "...",
    "field_name": "..."
  },
  "confidence": 0.0,
  "extraction_model": "jp.anthropic.claude-sonnet-4-6"
}
```

Entity ID may be raw/non-normalized in R6.
Final normalized IDs will be handled in R7.

---

## Relation Record Schema

Write raw relations to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_relations_r6.jsonl
```

Each relation record must include:

```json
{
  "relation_id": "raw_rel_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "source_entity": "PaymentReqAction",
  "source_entity_type": "Action",
  "target_entity": "PaymentReqService",
  "target_entity_type": "Service",
  "relation_type": "calls",
  "description": "...",
  "evidence_text": "...",
  "source_chunk_id": "chunk_or_summary_id",
  "source_uri": "s3://...",
  "source_file_name": "...",
  "related_target_questions": ["Q1", "Q5"],
  "key_fields": ["BILL_NO", "STATUS"],
  "q4_relation_type": null,
  "confidence": 0.0,
  "extraction_model": "jp.anthropic.claude-sonnet-4-6"
}
```

Relations must use entity names that also appear in raw_entities, where possible.

Every relation must have:

```text
source_chunk_id
evidence_text
source_uri
confidence
```

If these are missing, mark the relation as invalid and write it to a rejected/suspicious relation report.

---

## Evidence Record Schema

Write raw evidence to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_evidence_r6.jsonl
```

Each evidence record must include:

```json
{
  "evidence_id": "raw_ev_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "source_chunk_id": "chunk_or_summary_id",
  "source_uri": "s3://...",
  "source_file_name": "...",
  "evidence_text": "...",
  "evidence_type": "schema|code|process|visual|summary|config",
  "supports_entities": ["JOURNAL_BASE", "PAYMENT_REQ"],
  "supports_relations": ["raw_rel_xxx"],
  "related_target_questions": ["Q1", "Q2"],
  "confidence": 0.0
}
```

---

## Layer Mapping Rules

Use these graph layers:

### Business Layer

Use for:

```text
BusinessProcess
BusinessStep
BusinessObject
BusinessRule
Screen
Report
```

Examples:

```text
应付管理流程
对账单生成
付款申请创建
审批
支付
报表导出
```

### System Layer

Use for:

```text
System
Module
API
Action
Service
ServiceImpl
DAO
Mapper
Class
Method
Interface
ExternalSystem
```

Examples:

```text
MDW系统
OA系统
PaymentReqAction
PaymentReqService
JournalBaseServiceImpl
SUN
HULFT
```

### Data Layer

Use for:

```text
Table
View
Column
Field
Status
EnumValue
```

Examples:

```text
JOURNAL_BASE
PAYMENT_REQ
SUN_REQUEST
RECEIVING_JOURNAL
BILL_NO
STATUS
```

### Evidence Layer

Use for:

```text
Document
File
Evidence
```

Examples:

```text
MDW支払依頼_V3.1.pptx
chunk_r3_037
summary_r4_012
```

---

## Extraction Strategy

### Input Priority

Process chunks in this order:

1. R4 summary chunks
2. schema_evidence chunks
3. process_evidence chunks
4. code_evidence chunks
5. config_evidence chunks

Reason:

* summaries provide business-level structure
* schema chunks provide precise table/field evidence
* process chunks provide workflows
* code chunks provide implementation links
* config chunks provide wiring

### Batch Strategy

Use small batches.

Recommended:

```text
batch_size = 1 to 3 chunks
```

Do not combine too many unrelated chunks in one prompt.

For each batch, include:

* chunk_id
* source_uri
* chunk_purpose
* related_target_questions
* expected_entities
* text

### LLM Output Format

The LLM must return strict JSON:

```json
{
  "entities": [],
  "relations": [],
  "evidence": [],
  "warnings": []
}
```

If JSON parsing fails:

1. save raw output
2. retry once with a stricter JSON repair prompt
3. if still fails, write failure to extraction_failures_r6.jsonl
4. continue with other chunks

---

## LLM Extraction Prompt Requirements

The extraction prompt must instruct the model:

1. Use only the provided chunk text.
2. Do not invent entities or relations.
3. Preserve technical names exactly.
4. Preserve table names exactly.
5. Preserve field names exactly.
6. Preserve class and method names exactly.
7. If uncertain, omit the relation or mark confidence below 0.5.
8. Every relation must have evidence_text copied or summarized from the source chunk.
9. Prefer specific relation types over `related_to`.
10. Avoid `custom`.
11. For Q4 semantic map relations, also map relation to one of:

    * `generates`
    * `depends_on`
    * `relates_to`
12. Return JSON only.

---

## Target Question Coverage Requirements

R6 must produce target-question graph coverage.

### Q1 Graph Coverage

Must include graph entities/relations for:

```text
应付管理流程
对账单生成
付款申请创建
审批
支付
报表/导出
related tables
related code modules
```

Expected relations:

```text
flows_to
generates
depends_on
calls
reads_from
writes_to
updates
exports
```

### Q2 Graph Coverage

Must include:

```text
JOURNAL_BASE
JournalBaseAction
JournalBaseService
JournalBaseServiceImpl
RECEIVING_JOURNAL
RECEIVING_LIST
```

Expected relations:

```text
JOURNAL_BASE has_field ...
JournalBaseService reads_from JOURNAL_BASE
JOURNAL_BASE joins_on RECEIVING_JOURNAL
JOURNAL_BASE supports 对账单生成
```

### Q3 Graph Coverage

Must include:

```text
SUN_REQUEST
JOURNAL_BASE
RECEIVING_JOURNAL
RECEIVING_LIST
PAYMENT_RECEIVING
PAYMENT_REQ
```

Expected relations:

```text
SUN_REQUEST joins_on JOURNAL_BASE
JOURNAL_BASE joins_on RECEIVING_JOURNAL
RECEIVING_JOURNAL joins_on RECEIVING_LIST
RECEIVING_LIST joins_on PAYMENT_RECEIVING
PAYMENT_RECEIVING joins_on PAYMENT_REQ
```

Where applicable, include key fields:

```text
OTHER_SYSTEM_NO
JOURNAL_NO
PAY_NO
BILL_NO
STATUS
```

If some exact relation is not supported by the source chunks, do not invent it. Report missing evidence.

### Q4 Graph Coverage

Must include a Semantic Map candidate chain.

At minimum:

```text
订单/外部数据 → 对账单 → 付款申请 → 审批 → 支付
```

Ideally:

```text
订单/外部数据 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表
```

For Q4, relation types must be convertible to:

```text
generates
depends_on
relates_to
```

R6 must output a candidate Q4 CSV preview:

```text
nodes_r6_q4_preview.csv
edges_r6_q4_preview.csv
```

This preview is for review only.
Do not load into Neptune.

### Q5 Graph Coverage

Must include:

```text
PAYMENT_REQ
PAYMENT_RECEIVING
STATUS
BILL_NO
APPROVAL_BY
APPROVAL_TIME
APPROVAL_REMARK
PaymentReqAction
PaymentReqService
PaymentReqServiceImpl
OA系统
审批结果回写
callback API candidate
```

Expected relations:

```text
PaymentReqAction calls PaymentReqService
PaymentReqService updates PAYMENT_REQ
PAYMENT_REQ has_field STATUS
OA系统 updates PAYMENT_REQ
审批结果回写 updates STATUS
```

If OA is proposed from migration design summary rather than existing system evidence, mark it as:

```text
proposed_design = true
```

Do not mix proposed design with existing implementation without marking it.

---

## Deduplication Policy in R6

R6 should not perform final normalization, but it should identify obvious duplicate candidates.

Write duplicate candidates to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entity_dedup_candidates_r6.jsonl
```

Examples:

```text
PAYMENT_REQ
PaymentReq
payment_req

JOURNAL_BASE
JournalBase

RECEIVING_JOURNAL
ReceivingJournal
```

Do not merge them destructively in R6.

R7 will handle normalization.

---

## Suspicious / Rejected Relations

Write suspicious or invalid relations to:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/suspicious_relations_r6.jsonl
```

Reject or mark suspicious if:

1. missing source entity
2. missing target entity
3. missing evidence_text
4. missing source_chunk_id
5. relation type not in allowed list
6. confidence below 0.4
7. appears hallucinated
8. uses unsupported relation type `custom`

Do not include suspicious relations in the clean raw relation output unless clearly marked.

---

## Required Outputs

Artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required files:

```text
raw_entities_r6.jsonl
raw_relations_r6.jsonl
raw_evidence_r6.jsonl
entity_dedup_candidates_r6.jsonl
suspicious_relations_r6.jsonl
extraction_failures_r6.jsonl
relation_type_distribution_r6.json
target_question_graph_coverage_r6.json
nodes_r6_q4_preview.csv
edges_r6_q4_preview.csv
graph_extraction_input_manifest_r6.jsonl
graph_extraction_llm_raw_outputs_r6.jsonl
```

Reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r6_graph_extraction_report.md
docs/murata_rebuild_r6_target_question_graph_coverage.md
docs/murata_rebuild_r6_relation_quality_report.md
docs/murata_rebuild_r6_dedup_candidates_report.md
docs/murata_rebuild_r6_q4_semantic_map_preview.md
docs/murata_rebuild_r6_next_step_recommendation.md
```

---

## R6 Quality Gate

R6 passes only if:

1. Text LLM model is confirmed and reported.
2. Graph extraction inputs are validated.
3. Raw entities are created.
4. Raw relations are created.
5. Raw evidence records are created.
6. Every clean relation has:

   * source entity
   * target entity
   * relation_type
   * source_chunk_id
   * evidence_text
   * confidence
7. Relation type distribution is reported.
8. `custom` relation count is zero.
9. `related_to` relation count is not dominant.
10. Q1 graph coverage is at least partial.
11. Q2 includes `JOURNAL_BASE`.
12. Q3 includes `SUN_REQUEST`, `JOURNAL_BASE`, and `RECEIVING_JOURNAL` or reports missing evidence clearly.
13. Q4 preview CSV is created.
14. Q4 preview contains at least one continuous path A → B → C → D.
15. Q5 includes `PAYMENT_REQ`, approval fields, and OA/proposed design nodes or reports limitations clearly.
16. Suspicious relations are separated.
17. Extraction failures are logged.
18. No Neptune query/write occurs.
19. No LanceDB write occurs.
20. No embedding, VLM, QA terminal, or final answer generation occurs.

If R6 quality gate fails:

1. do not proceed to R7
2. report failure reasons
3. recommend one of:

   * refine graph extraction prompt
   * reduce batch size
   * extract only summary chunks first
   * add missing summary chunks
   * return to R4 or R5 for specific issue

---

## Reporting Requirements

At completion, output a Phase R6 report with:

1. model used
2. number of input chunks
3. number selected for graph extraction
4. number excluded
5. number of LLM calls
6. number of raw entities
7. number of raw relations
8. number of raw evidence records
9. relation type distribution
10. suspicious relation count
11. extraction failure count
12. duplicate entity candidate count
13. Q1–Q5 graph coverage summary
14. Q4 CSV preview status
15. whether R6 quality gate passed
16. whether R7 normalization/integrity is recommended
17. generated files
18. warnings and risks

---

## Forbidden Actions

R6 must not:

1. query Neptune
2. write Neptune
3. generate embeddings
4. write LanceDB
5. run VLM
6. run QA terminal
7. generate final answers
8. delete baseline data
9. perform destructive normalization
10. proceed to R7 automatically

---

## Allowed Actions

R6 may:

1. read R3/R4/R5 artifacts
2. call Bedrock text LLM for graph extraction
3. create raw graph artifacts
4. create quality reports
5. update `docs/task_state.md`

---

## State Update

After completing R6, update `docs/task_state.md`:

```markdown
## Current Phase

`R6`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_entities_r6.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_relations_r6.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/raw_evidence_r6.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entity_dedup_candidates_r6.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/suspicious_relations_r6.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/extraction_failures_r6.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/relation_type_distribution_r6.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/target_question_graph_coverage_r6.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/nodes_r6_q4_preview.csv`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/edges_r6_q4_preview.csv`
- `docs/murata_rebuild_r6_graph_extraction_report.md`
- `docs/murata_rebuild_r6_target_question_graph_coverage.md`
- `docs/murata_rebuild_r6_relation_quality_report.md`
- `docs/murata_rebuild_r6_dedup_candidates_report.md`
- `docs/murata_rebuild_r6_q4_semantic_map_preview.md`
- `docs/murata_rebuild_r6_next_step_recommendation.md`

## Latest Findings

Summarize graph extraction quality and coverage.

## Risks / Issues

Summarize suspicious relations, extraction failures, missing graph evidence, and dedup risks.

## Recommended Next Phase

`R7`

## Next Phase Prompt

`docs/prompts/phase_r7_normalization_integrity.md`
```

Then stop and wait for user review.

Do not proceed to R7 automatically.

 
