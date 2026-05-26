# Phase R3 — Chunking + Chunk Purpose Classification

## Objective

Generate high-quality, structure-aware chunks for the Murata rebuild sample set, and classify every chunk by purpose, quality, embedding eligibility, and graph-extraction eligibility.

R3 is **not** an embedding phase.  
R3 is **not** a graph extraction phase.  
R3 is **not** a QA phase.

The goal of R3 is to make sure that the knowledge units produced from R2 and R2.5 are suitable for later:

- summary generation
- embedding
- graph extraction
- hybrid retrieval
- answer generation

The current baseline GraphRAG quality issue is not that the pipeline cannot run.  
The issue is that the system previously sent too many low-value raw code / SQL / data chunks into embedding and graph extraction.

R3 must therefore introduce:

1. structure-aware chunking
2. chunk purpose classification
3. chunk quality scoring
4. `should_embed`
5. `should_extract_graph`
6. `summary_candidate`
7. target-question coverage mapping

---

## Project Context

Project root:

```text
~/projects/hermes_bedrock_agent
````

Baseline:

```text
baseline run_id: murata_live_v1
baseline LanceDB collection: murata_e2e_murata_live_v1
```

Rebuild target:

```text
rebuild run_id: murata_rebuild_v1
rebuild LanceDB collection: murata_e2e_murata_rebuild_v1
dataset: murata
S3 source: s3://s3-hulftchina-rd/Murata/
```

R2 parsed the selected text/code/schema/config files.

R2.5 successfully validated the VLM API and parsed the 3 HIGH-priority VLM files:

* `村田.xlsx`
* `MDW支払依頼_V3.1.pptx`
* `村田MDW支付系统操作手册之业务功能管理.docx`

R2.5 confirmed that:

* `VISION_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6` should be used
* VLM evidence is useful for Q1 / Q4 / Q5
* VLM evidence should be included as process / visual evidence

---

## Control Files to Read

Before executing R3, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r3_chunking_quality.md`
4. `data/registry/murata_rebuild_v1_sample_files.jsonl`

Also read R2/R2.5 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/normalized_documents.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/visual_blocks_r2_5.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/vlm_raw_outputs_r2_5.jsonl
```

Read these reports if available:

```text
docs/murata_rebuild_parse_quality_report.md
docs/murata_rebuild_target_question_evidence_matrix.md
docs/murata_rebuild_missing_evidence_report.md
docs/murata_rebuild_vlm_quality_report.md
docs/murata_rebuild_process_chain_evidence_report.md
```

---

## Required Pre-check

Before chunking, verify that the following config value is readable from `.env` / project settings:

```text
VISION_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6
```

This is a **config-read verification only**.

Do not call Bedrock.
Do not run VLM.
Do not modify `.env`.
Do not modify core config code.

If the setting cannot be read:

1. stop R3
2. report the exact issue
3. do not proceed to chunking

---

## Target QA Questions

R3 chunking must be driven by the five target QA questions.

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

要求：

* 结合现有表结构，如 `PAYMENT_REQ`、`PAYMENT_RECEIVING` 等
* 尽量具体，不要泛泛而谈
* 不要只写概念，需要有结构化内容

---

## R3 Inputs

Use these inputs:

```text
R2 normalized documents:
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/normalized_documents.jsonl

R2.5 VLM visual evidence:
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/visual_blocks_r2_5.jsonl

R2.5 raw VLM outputs:
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/vlm_raw_outputs_r2_5.jsonl

R1 sample registry:
data/registry/murata_rebuild_v1_sample_files.jsonl
```

---

## R3 Scope

R3 includes:

1. merge R2 parsed text/code/schema/config documents with R2.5 VLM evidence
2. generate structure-aware chunks
3. classify chunk purpose
4. classify chunk quality
5. decide whether each chunk should enter embedding
6. decide whether each chunk should enter graph extraction
7. identify summary candidates
8. produce quality reports

R3 excludes:

1. embedding
2. LanceDB write
3. Neptune query
4. Neptune write
5. graph extraction
6. QA terminal
7. Bedrock / LLM calls
8. VLM calls

---

## Chunk Output Schema

Each chunk in `chunks_r3.jsonl` must include at least:

```json
{
  "chunk_id": "chunk_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "document_id": "doc_xxx",
  "source_uri": "s3://...",
  "source_file_name": "...",
  "source_type": "code|sql|spreadsheet|docx|pptx|image|config|text|unknown|vlm",
  "chunk_type": "text|code|schema|visual|process|config|summary_candidate",
  "chunk_purpose": "answerable_text|code_evidence|schema_evidence|visual_evidence|process_evidence|data_sample|config_evidence|low_value|summary_candidate",
  "chunk_quality": "high|medium|low",
  "quality_score": 0.0,
  "should_embed": true,
  "should_extract_graph": true,
  "is_summary": false,
  "summary_candidate": false,
  "parent_chunk_id": null,
  "section_title": "...",
  "text": "...",
  "language": "zh|ja|en|mixed|code|unknown",
  "related_target_questions": ["Q1", "Q2"],
  "expected_entities": ["JOURNAL_BASE", "PAYMENT_REQ"],
  "evidence_type": ["schema", "code", "business_process", "visual", "config"],
  "visual_block_id": null,
  "confidence": 0.0,
  "metadata": {
    "reason_should_embed": "...",
    "reason_should_extract_graph": "...",
    "reason_chunk_purpose": "...",
    "risk_or_uncertainty": "..."
  }
}
```

If an existing schema model does not yet support all these fields, store the extra fields under `metadata`.

Do not break existing schemas unless absolutely necessary.

---

## Chunk Purpose Definitions

### `answerable_text`

Use for text that can directly answer user questions, such as:

* business process explanation
* functional description
* operation manual text
* workflow description
* meaningful table description
* meaningful system description

Recommended:

```text
should_embed=true
should_extract_graph=true if entities/relations exist
```

---

### `process_evidence`

Use for business workflow or process-step evidence, especially from VLM output, PPTX, DOCX screenshots, or process descriptions.

Examples:

* Receiving List generation
* Payment Request creation
* Approval workflow
* Payment processing
* Payment List / report export

Recommended:

```text
should_embed=true
should_extract_graph=true
```

---

### `schema_evidence`

Use for database schema, DDL, table definitions, Excel schema rows, view definitions, field definitions, status values.

Examples:

* `JOURNAL_BASE` DDL
* `PAYMENT_REQ` field list
* `RECEIVING_JOURNAL` bridge keys
* `V_PAYMENT_REQ_FILE` view
* `STATUS` values

Recommended:

```text
should_embed=true
should_extract_graph=true
```

---

### `code_evidence`

Use for Java / SQL / Mapper / DAO / Action / Service / Model code.

Examples:

* `JournalBaseServiceImpl`
* `PaymentReqAction`
* `PaymentRequestService`
* DAO/Mapper queries
* method-level workflow logic

Recommended default:

```text
should_embed=false
should_extract_graph=true if code contains table access, status flow, field mapping, DAO/Mapper calls, workflow logic
summary_candidate=true
```

Only set `should_embed=true` for code chunks that are highly explanatory and readable.

---

### `visual_evidence`

Use for visual descriptions, screenshots, UI screenshots, diagrams, slide-derived visual summaries.

Recommended:

```text
should_embed=true if readable and business-relevant
should_extract_graph=true if it describes process, entities, relations, or fields
```

---

### `config_evidence`

Use for Struts / Spring / Hibernate / Mapper / routing / dependency wiring config.

Recommended:

```text
should_embed=false by default
should_extract_graph=true if it links Action → Service → DAO → Model or routes API/function modules
summary_candidate=true if important
```

---

### `data_sample`

Use for large INSERT statements, sample rows, bulk data files, raw data dumps.

Recommended:

```text
should_embed=false
should_extract_graph=false
```

---

### `low_value`

Use for empty, duplicated, garbled, boilerplate, generated, uninformative, or extremely fragmented content.

Recommended:

```text
should_embed=false
should_extract_graph=false
```

---

### `summary_candidate`

Use for source chunks that should be summarized in R4 before embedding.

Examples:

* long Java class
* complex ServiceImpl
* complex SQL view
* long operation manual section
* long VLM process result

Recommended:

```text
should_embed=false for raw chunk
should_extract_graph=true if it contains relations
summary_candidate=true
```

---

## Structure-Aware Chunking Rules

### SQL / DDL / View

Chunk by:

1. table definition
2. view definition
3. meaningful query block
4. status enum block
5. join logic block

Important entities:

```text
JOURNAL_BASE
SUN_REQUEST
RECEIVING_JOURNAL
RECEIVING_LIST
PAYMENT_REQ
PAYMENT_RECEIVING
V_PAYMENT_REQ_FILE
V_PAYMENT_RECEIVING
HULFT_DICT
```

Rules:

* Do not split one table definition into meaningless fragments.
* Preserve table name.
* Preserve key fields.
* Preserve comments if available.
* Preserve join conditions.
* Mark schema chunks for `should_embed=true` and `should_extract_graph=true`.
* Mark pure INSERT data as `data_sample`.

---

### Java Code

Chunk by:

1. class
2. major method
3. workflow method
4. DAO/Mapper call
5. status transition method
6. table access block

Rules:

* Preserve class name.
* Preserve method name.
* Preserve package name.
* Preserve imported model/service if useful.
* Mark related target questions.
* Do not mark all code for embedding.
* Mark important code as `summary_candidate=true`.

Relevant code indicators:

```text
JournalBase
ReceivingJournal
PaymentReq
PaymentRequest
PaymentReceiving
SunRequest
STATUS
BILL_NO
PAY_NO
OTHER_SYSTEM_NO
APPROVAL_BY
APPROVAL_TIME
APPROVAL_REMARK
insert
update
select
Mapper
Dao
Service
Action
```

---

### Excel / Spreadsheet

Chunk by:

1. sheet
2. table definition
3. field group
4. status enum group
5. relation / bridge table definition

Rules:

* Preserve sheet name.
* Preserve table physical name.
* Preserve field names and descriptions.
* Mark schema evidence.
* Mark process evidence if VLM extracted process semantics.

---

### PPTX / DOCX / VLM Evidence

Chunk by:

1. business process step
2. visual page / slide
3. UI workflow step
4. table/field description block
5. detected relation group

Rules:

* Use R2.5 VLM output.
* Chunk at process-step level.
* Preserve `visual_block_id`.
* Preserve `source_uri`.
* Preserve confidence.
* Mark Q1/Q4/Q5 support.
* Mark as `process_evidence` or `visual_evidence`.
* Mark `should_embed=true` if readable and useful.
* Mark `should_extract_graph=true` if it contains process entities/relations.

---

### Config

Chunk by:

1. Struts action mapping
2. Spring bean mapping
3. Hibernate model mapping
4. Mapper / DAO wiring
5. route/module relation

Rules:

* Use `config_evidence`.
* Do not embed unless it is human-readable and useful.
* Use graph extraction if it reveals implementation relationships.

---

## Target Question Coverage Requirements

R3 must produce a target-question chunk coverage report.

### Q1 Coverage

Must find chunks for:

* process steps
* related database tables
* key fields
* related code modules

Expected chunk purposes:

```text
process_evidence
schema_evidence
code_evidence
visual_evidence
```

---

### Q2 Coverage

Must find chunks for:

* `JOURNAL_BASE` schema
* `JOURNAL_BASE` fields
* business role of `JOURNAL_BASE`
* Java code using `JOURNAL_BASE`

Expected chunk purposes:

```text
schema_evidence
code_evidence
process_evidence
```

---

### Q3 Coverage

Must find chunks for:

* `SUN_REQUEST`
* `JOURNAL_BASE`
* `RECEIVING_JOURNAL`
* join fields
* bridge table logic
* view or SQL evidence
* code evidence if available

Expected chunk purposes:

```text
schema_evidence
code_evidence
```

---

### Q4 Coverage

Must find process-chain chunks for:

```text
订单/外部数据 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表
```

Mark each step as:

```text
covered
partial
missing
```

At minimum R3 must cover:

```text
订单/外部数据 → 对账单 → 付款申请 → 审批 → 支付
```

If `报表` remains partial or missing, report it clearly.

Expected chunk purposes:

```text
process_evidence
visual_evidence
schema_evidence
```

---

### Q5 Coverage

Must find chunks for:

* `PAYMENT_REQ`
* `PAYMENT_RECEIVING`
* approval status
* `STATUS`
* `BILL_NO`
* approval callback / approval result
* Action / Service modules
* existing approval workflow
* impact on receiving / payment request flow

Expected chunk purposes:

```text
schema_evidence
code_evidence
process_evidence
visual_evidence
```

---

## Required Outputs

Write artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required artifact files:

```text
chunks_r3.jsonl
chunk_purpose_distribution.json
low_value_chunks.jsonl
summary_candidates.jsonl
target_question_chunk_coverage.json
```

Write docs under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required docs:

```text
docs/murata_rebuild_chunk_quality_report.md
docs/murata_rebuild_target_question_chunk_coverage.md
docs/murata_rebuild_low_value_chunks_report.md
docs/murata_rebuild_r3_recommendation_for_summary_generation.md
```

---

## `chunk_purpose_distribution.json` Format

Use a structure similar to:

```json
{
  "run_id": "murata_rebuild_v1",
  "total_chunks": 0,
  "by_chunk_purpose": {
    "process_evidence": 0,
    "schema_evidence": 0,
    "code_evidence": 0,
    "visual_evidence": 0,
    "config_evidence": 0,
    "data_sample": 0,
    "low_value": 0,
    "summary_candidate": 0
  },
  "should_embed": {
    "true": 0,
    "false": 0
  },
  "should_extract_graph": {
    "true": 0,
    "false": 0
  },
  "by_target_question": {
    "Q1": 0,
    "Q2": 0,
    "Q3": 0,
    "Q4": 0,
    "Q5": 0
  }
}
```

---

## `target_question_chunk_coverage.json` Format

Use a structure similar to:

```json
{
  "Q1": {
    "status": "pass|partial|fail",
    "supporting_chunk_ids": [],
    "coverage_notes": "",
    "missing_evidence": []
  },
  "Q2": {
    "status": "pass|partial|fail",
    "supporting_chunk_ids": [],
    "coverage_notes": "",
    "missing_evidence": []
  },
  "Q3": {
    "status": "pass|partial|fail",
    "supporting_chunk_ids": [],
    "coverage_notes": "",
    "missing_evidence": []
  },
  "Q4": {
    "status": "pass|partial|fail",
    "chain_coverage": {
      "订单/外部数据": "covered|partial|missing",
      "对账单": "covered|partial|missing",
      "审批": "covered|partial|missing",
      "付款申请": "covered|partial|missing",
      "支付": "covered|partial|missing",
      "报表": "covered|partial|missing"
    },
    "supporting_chunk_ids": [],
    "coverage_notes": "",
    "missing_evidence": []
  },
  "Q5": {
    "status": "pass|partial|fail",
    "supporting_chunk_ids": [],
    "coverage_notes": "",
    "missing_evidence": []
  }
}
```

---

## R3 Quality Gate

R3 passes only if:

1. `VISION_LLM_MODEL_ID` is confirmed readable as:

```text
jp.anthropic.claude-sonnet-4-6
```

2. Q1 has `process_evidence` chunks.

3. Q2 has both:

```text
JOURNAL_BASE schema_evidence
JOURNAL_BASE code_evidence
```

4. Q3 has schema or relation evidence chunks for:

```text
SUN_REQUEST
JOURNAL_BASE
RECEIVING_JOURNAL
```

5. Q4 has process-chain chunks covering at least:

```text
订单/外部数据 → 对账单 → 付款申请 → 审批 → 支付
```

and explicitly reports whether `报表` is missing or partial.

6. Q5 has chunks covering:

```text
PAYMENT_REQ
approval
STATUS
BILL_NO
```

7. No `data_sample` chunk has:

```text
should_embed=true
```

8. No `low_value` chunk has:

```text
should_embed=true
```

9. Visual evidence from R2.5 is usable as process-step-level chunks.

10. Java code chunks are not blindly marked `should_embed=true` unless they are explanatory.

11. No embedding, LanceDB write, Neptune operation, graph extraction, QA execution, Bedrock call, or VLM call occurs.

If R3 quality gate fails:

1. do not proceed to R4
2. report missing evidence
3. recommend returning to R2/R2.5 or refining sample selection

---

## Forbidden Actions

R3 must not:

1. call Bedrock
2. run VLM
3. generate embeddings
4. write LanceDB
5. query Neptune
6. write Neptune
7. run graph extraction
8. run QA terminal
9. delete baseline data
10. modify core code unless absolutely necessary
11. proceed to R4 automatically

---

## Allowed Actions

R3 may:

1. read project control files
2. read R2 and R2.5 artifacts
3. run local-only chunking logic
4. create R3 artifacts
5. create R3 reports
6. update `docs/task_state.md`
7. create this prompt file if it does not already exist

---

## Reporting Requirements

At completion, output a Phase R3 report with:

1. whether `VISION_LLM_MODEL_ID` was read successfully
2. number of input documents
3. number of VLM evidence records merged
4. total chunks generated
5. chunk purpose distribution
6. `should_embed=true` count
7. `should_extract_graph=true` count
8. low-value / data-sample count
9. target question coverage summary
10. whether R3 quality gate passed
11. whether R4 summary generation is recommended
12. generated files
13. warnings or risks

---

## State Update

After completing R3, update `docs/task_state.md`:

```markdown
## Current Phase

`R3`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunks_r3.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunk_purpose_distribution.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/low_value_chunks.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_candidates.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/target_question_chunk_coverage.json`
- `docs/murata_rebuild_chunk_quality_report.md`
- `docs/murata_rebuild_target_question_chunk_coverage.md`
- `docs/murata_rebuild_low_value_chunks_report.md`
- `docs/murata_rebuild_r3_recommendation_for_summary_generation.md`

## Latest Findings

Summarize key chunking and coverage findings.

## Risks / Issues

Summarize remaining issues.

## Recommended Next Phase

`R4`

## Next Phase Prompt

`docs/prompts/phase_r4_summary_chunks.md`
```

Then stop and wait for user review.

Do not proceed to R4 automatically.
