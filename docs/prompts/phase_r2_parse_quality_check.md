# Phase R2 — Parse / VLM Quality Check

## Objective

Parse the selected Murata rebuild sample files and evaluate whether the parsed outputs are good enough to support the five target QA questions.

This phase is not just a parse-success check.

R2 must verify whether the selected files actually contain usable evidence for the target QA questions.

## Context

Baseline run:

- baseline run_id: `murata_live_v1`
- baseline LanceDB collection: `murata_e2e_murata_live_v1`

Rebuild target:

- rebuild run_id: `murata_rebuild_v1`
- rebuild LanceDB collection: `murata_e2e_murata_rebuild_v1`
- dataset: `murata`
- S3 source: `s3://s3-hulftchina-rd/Murata/`

Input sample registry:

- `data/registry/murata_rebuild_v1_sample_files.jsonl`

## Target QA Questions

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

订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表

要求：

1. 必须覆盖以上完整流程链，不得缺失步骤
2. 输出 `nodes.csv`，字段：`id,label,type`
3. 输出 `edges.csv`，字段：`from,to,relation`
4. 关系仅允许：
   - `generates`
   - `depends_on`
   - `relates_to`
5. 必须体现一条清晰主链，至少包含连续路径 A → B → C → D
6. 不要解释，只输出 CSV

### Q5. 付款申请审批迁移到 OA 的系统改造方案

当前系统中，付款申请在应付系统内完成审批。

现在需要进行系统改造：

- 做单仍在应付系统，Payment Request
- 审批流程迁移到 OA 系统
- 审批完成后，审批结果需要回写应付系统

请完成以下内容：

1. 设计新的业务流程
2. 描述数据流转关系
3. 给出系统改造清单
4. 说明对现有业务流程的影响

要求：

- 结合现有表结构，如 PAYMENT_REQ、PAYMENT_RECEIVING 等
- 尽量具体，不要泛泛而谈
- 不要只写概念，需要有结构化内容

## Allowed Actions

- Read `.hermes.md`
- Read `docs/task_state.md`
- Read this phase prompt
- Read `data/registry/murata_rebuild_v1_sample_files.jsonl`
- Read selected files from S3 or local cache as required for parsing
- Run parser on selected sample files only
- Run VLM only for selected image/PDF/PPTX/XLSX/DOCX files if needed and allowed by configuration
- Create parse artifacts for `murata_rebuild_v1`
- Create parse quality reports
- Update `docs/task_state.md`

## Forbidden Actions

- Do not generate embeddings
- Do not write LanceDB
- Do not query Neptune
- Do not write Neptune
- Do not run graph extraction
- Do not run chunking beyond parser-created document sections
- Do not run QA terminal
- Do not delete any baseline data
- Do not modify core code unless explicitly required and reported
- Do not proceed to R3 automatically

## Required Inputs

- `data/registry/murata_rebuild_v1_sample_files.jsonl`

## Required Outputs

Create artifacts under a rebuild run directory, for example:

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/normalized_documents.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/visual_blocks.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/parser_failed.jsonl`
- `docs/murata_rebuild_parse_quality_report.md`
- `docs/murata_rebuild_target_question_evidence_matrix.md`
- `docs/murata_rebuild_missing_evidence_report.md`

## Parse Quality Checks

For each selected file, evaluate:

- parse_success: true / false
- parser_used
- source_type
- content_length
- section_count
- visual_block_count
- tables_extracted
- code_structure_extracted
- sql_structure_extracted
- obvious_garbled_text
- empty_or_low_value_content
- requires_vlm
- vlm_used
- parse_risk

## Target Question Evidence Checks

R2 must produce a target-question evidence matrix.

For each target question, identify whether parsed content contains usable evidence.

### Q1 evidence check

Look for:

- accounts payable process steps
- order / receiving / reconciliation / approval / payment / report flow
- tables per step
- key fields per step
- code modules per step

### Q2 evidence check

Look for:

- JOURNAL_BASE table structure
- JOURNAL_BASE fields
- JournalBase Java classes
- Service / Action / DAO / Mapper references to JOURNAL_BASE
- business usage of JOURNAL_BASE

### Q3 evidence check

Look for:

- SUN_REQUEST schema or references
- JOURNAL_BASE schema or references
- RECEIVING_JOURNAL schema or references
- common fields linking these tables
- SQL / Mapper / DAO logic showing joins or data flow
- code logic moving data between these tables

### Q4 evidence check

Look for coverage of:

- 订单
- 对账单
- 审批
- 付款申请
- 审批
- 支付
- 报表

The report must explicitly mark each step as:

- covered
- partially covered
- missing

### Q5 evidence check

Look for:

- PAYMENT_REQ
- PAYMENT_RECEIVING
- approval status
- BILL_NO
- STATUS
- PaymentRequest Action / Service / Model
- API / interface candidates
- existing approval flow
- impact on payment request generation or receiving flow

## Quality Gate

R2 passes only if:

1. All selected files are either parsed successfully or failures are clearly explained.
2. JOURNAL_BASE schema evidence is parsed.
3. JOURNAL_BASE code evidence is parsed.
4. PAYMENT_REQ or payment request evidence is parsed.
5. SUN_REQUEST / RECEIVING_JOURNAL evidence is either found or missing coverage is explicitly reported.
6. Q4 process chain coverage is evaluated step by step.
7. Report-related evidence gap is confirmed or resolved.
8. Files requiring VLM are identified.
9. Parsed outputs are sufficient to proceed to chunking for at least Q1, Q2, and Q5.
10. No embeddings, LanceDB writes, Neptune queries/writes, or graph extraction are executed.

If R2 quality gate fails, do not proceed to R3. Report missing coverage and recommend returning to R1 for sample expansion.

## State Update

After completing R2, update `docs/task_state.md`:

- Current Phase Status: completed
- Completed Outputs:
  - normalized_documents.jsonl
  - visual_blocks.jsonl
  - parser_failed.jsonl
  - docs/murata_rebuild_parse_quality_report.md
  - docs/murata_rebuild_target_question_evidence_matrix.md
  - docs/murata_rebuild_missing_evidence_report.md
- Latest Findings
- Risks / Issues
- Recommended Next Phase
- Next Phase Prompt: `docs/prompts/phase_r3_chunking_quality.md`

Then stop and wait for user review.
