# Phase R1 — Target-Question-Driven Sample File Selection

## Objective

Select a small but high-value Murata sample document set for rebuilding and evaluating the GraphRAG knowledge base.

This phase must be driven by the target QA questions below.

The goal is not to select files randomly or only by file type.  
The goal is to select documents that can support answering the target questions with evidence from:

- business process documents
- database table definitions
- SQL / Mapper / DAO logic
- Java Action / Service / Model classes
- Excel schema documents
- screenshots or visual documents if relevant
- configuration files if they reveal workflow, routing, DAO, Mapper, or module relationships

This phase is **sample file selection only**.

Do not parse files.  
Do not call Bedrock.  
Do not run VLM.  
Do not generate embeddings.  
Do not write LanceDB.  
Do not query Neptune.  
Do not write Neptune.  
Do not modify core code.

---

## Baseline and Rebuild Context

Baseline:

- baseline run_id: `murata_live_v1`
- baseline LanceDB collection: `murata_e2e_murata_live_v1`

New rebuild target:

- rebuild run_id: `murata_rebuild_v1`
- rebuild LanceDB collection: `murata_e2e_murata_rebuild_v1`
- dataset: `murata`
- S3 source: `s3://s3-hulftchina-rd/Murata/`

---

## Target QA Questions

R1 must select sample files that can support answering the following five target questions.

---

### Q1. 应付管理业务流程

请描述应付管理的业务流程，并要求：

1. 每个流程步骤对应的数据库表
2. 每个步骤涉及的关键字段
3. 如有对应代码模块，请指出类或方法

Expected evidence types:

- business process documents
- payment / accounts payable related source code
- table definitions
- SQL / Mapper / DAO
- workflow-related screenshots if available
- payment / receiving / approval / report related modules

Likely target entities / keywords:

- 应付管理
- AP
- Accounts Payable
- Payment Request
- 付款申请
- 付款申請
- 支払申請
- 对账单
- 対帳単
- 审批
- 承認
- 支付
- 支払
- 报表
- レポート
- PAYMENT_REQ
- PAYMENT_RECEIVING
- SUN_REQUEST
- JOURNAL_BASE
- RECEIVING_JOURNAL

---

### Q2. JOURNAL_BASE 表作用

JOURNAL_BASE 表在系统中的作用是什么？

请结合：

1. 表结构
2. 相关业务流程
3. 调用该表的代码模块进行说明

Expected evidence types:

- table schema / Excel database design
- DDL / SQL
- Java Model / Service / ServiceImpl / Action / DAO / Mapper
- business process references
- receiving / journal / payable flow documents

Likely target entities / keywords:

- JOURNAL_BASE
- JournalBase
- JournalBaseService
- JournalBaseServiceImpl
- JournalBaseAction
- JournalBaseDao
- JournalBaseMapper
- 仕訳基礎
- 仕訳基礎テーブル
- 基础数据表
- receiving journal
- payable flow

---

### Q3. SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联

SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三张表之间，在没有外键的情况下：

1. 通过哪些字段形成关联
2. 这些关联在代码中是如何体现的，例如 SQL 或 Mapper
3. 在业务流程中的数据流转路径

Expected evidence types:

- table definitions
- Excel schema
- DDL / SQL
- Mapper / DAO / query code
- Java Service implementation
- business data flow documents

Likely target entities / keywords:

- SUN_REQUEST
- JOURNAL_BASE
- RECEIVING_JOURNAL
- BILL_NO
- JOURNAL_NO
- REQUEST_NO
- VENDOR
- STATUS
- RECEIVING
- JournalBase
- ReceivingJournal
- SunRequest
- Mapper
- DAO
- SQL

---

### Q4. 应付管理完整业务流程 Semantic Map

请围绕“应付管理完整业务流程”，构建一个 Semantic Map，输出 Neptune CSV。

已知业务主流程为：

订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表

要求：

1. 必须覆盖以上完整流程链，不得缺失步骤
2. 输出：
   - `nodes.csv`，字段：`id,label,type`
   - `edges.csv`，字段：`from,to,relation`
3. 关系仅允许：
   - `generates`
   - `depends_on`
   - `relates_to`
4. 必须体现一条清晰主链，至少包含连续路径 A → B → C → D
5. 不要解释，只输出 CSV

Expected evidence types:

- process documents
- workflow screenshots
- table definitions
- business modules
- code modules showing order / receiving / approval / payment / report flow
- report-related code or SQL if available

Likely target entities / keywords:

- 订单
- Order
- 对账单
- 対帳単
- 审批
- 承認
- 付款申请
- 付款申請
- Payment Request
- 支付
- 支払
- 报表
- report
- workflow
- approval
- SUN_REQUEST
- JOURNAL_BASE
- RECEIVING_JOURNAL
- PAYMENT_REQ
- PAYMENT_RECEIVING

---

### Q5. 付款申请审批迁移到 OA 的系统改造方案

当前系统中，付款申请在应付系统内完成审批。

现在需要进行系统改造：

- 做单仍在应付系统，Payment Request
- 审批流程迁移到 OA 系统
- 审批完成后，审批结果需要回写应付系统

请完成以下内容：

1. 设计新的业务流程
   - 按步骤列出：创建付款申请 → OA 审批 → 回写 → 后续处理
   - 标明每一步所在系统：应付系统 / OA 系统

2. 描述数据流转关系
   - 哪些数据从应付系统传到 OA
   - 哪些数据从 OA 回传
   - 关键字段，如 BILL_NO、STATUS 等

3. 给出系统改造清单
   - 需要新增 / 修改的数据库表或字段
   - 需要修改的现有表，如 PAYMENT_REQ
   - 需要新增的接口 API
   - 需要修改的代码模块，如 Action / Service

4. 说明对现有业务流程的影响
   - 原有流程中哪些步骤被替换或调整
   - 是否影响对账单、付款申请生成等流程

要求：

- 结合现有表结构，如 PAYMENT_REQ、PAYMENT_RECEIVING 等
- 尽量具体，不要泛泛而谈
- 不要只写概念，需要有结构化内容

Expected evidence types:

- Payment Request related code
- approval workflow code
- payment / payable process documents
- table definitions
- API / Action / Service modules
- status fields
- interface / integration-related documents if available

Likely target entities / keywords:

- PAYMENT_REQ
- PAYMENT_RECEIVING
- PaymentRequest
- PaymentRequestAction
- PaymentRequestService
- approval
- approve
- status
- STATUS
- BILL_NO
- OA
- workflow
- callback
- interface
- API
- Action
- Service
- 应付系统
- 付款申请
- 付款申請
- 支払申請
- 审批
- 承認
- 回写

---

## Sample Selection Strategy

R1 must select sample files based on the five target questions.

The selected sample should cover:

1. Business process evidence
2. Database schema evidence
3. SQL / Mapper / DAO evidence
4. Java Action / Service / Model evidence
5. Payment Request / Accounts Payable modules
6. JOURNAL_BASE / RECEIVING_JOURNAL / SUN_REQUEST related logic
7. Visual or screenshot evidence if relevant
8. Report / payment / approval flow evidence if present
9. Configuration files if they reveal module, DAO, Mapper, Spring, Struts, or routing relationships

Recommended sample size:

- Target: 15–25 files
- Minimum: 12 files
- Maximum: 30 files

Do not select too many files in R1.

---

## File Selection Rules

For each selected file, record:

- source_uri
- file_name
- file_type
- module_or_domain
- related_target_questions
- expected_evidence_type
- selection_reason
- priority: high / medium / low
- expected_entities
- risk_or_uncertainty

Priority should be `high` if the file is expected to support multiple target questions.

---

## Required Coverage

The sample must include, if available:

### A. JOURNAL_BASE evidence

At least one of:

- table definition
- Excel schema
- DDL / SQL
- Java Model
- Java Service
- Java ServiceImpl
- Java Action
- Mapper / DAO

### B. PAYMENT_REQ / Payment Request evidence

At least one of:

- table definition
- Excel schema
- Java Action
- Java Service
- Java ServiceImpl
- Java Model
- approval-related code
- SQL / Mapper / DAO

### C. SUN_REQUEST / RECEIVING_JOURNAL evidence

At least one of:

- table definition
- Excel schema
- SQL / Mapper / DAO
- Java Service / Model / Action

### D. 应付管理 process evidence

At least one of:

- business process document
- workflow screenshot
- module document
- code modules that show order / receiving / approval / payment / report flow

### E. System modification evidence for OA approval migration

At least one of:

- existing payment request workflow code
- approval status handling
- API / Action / Service code
- table with STATUS / BILL_NO / request identifiers
- interface or integration documents if available

### F. Semantic Map process-chain evidence

The sample should include enough evidence to support this chain:

订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表

If direct evidence for some steps is missing, R1 must explicitly record missing coverage and identify which file types should be searched later.

---

## Allowed Actions

- Read `.hermes.md`
- Read `docs/task_state.md`
- Read this phase prompt
- Read existing inventory files if available
- Read existing reports / docs
- List S3 files if required and allowed by `docs/task_state.md`
- Use existing `documents.jsonl` from baseline artifacts if available
- Create sample selection output files
- Update `docs/task_state.md`

---

## Forbidden Actions

- Do not parse selected files
- Do not call Bedrock
- Do not run VLM
- Do not generate embeddings
- Do not write LanceDB
- Do not query Neptune
- Do not write Neptune
- Do not delete data
- Do not run graph extraction
- Do not run QA terminal
- Do not modify core code
- Do not proceed to R2 automatically

---

## Preferred Data Source for File Inventory

First try to use existing inventory:

`~/projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts/documents.jsonl`

If this file is unavailable or insufficient, use S3 listing for:

`s3://s3-hulftchina-rd/Murata/`

Only listing is allowed in R1.

Do not download, parse, VLM-process, embed, or graph-extract files in R1 unless explicitly allowed later.

---

## Required Outputs

Create:

1. `data/registry/murata_rebuild_v1_sample_files.jsonl`
2. `docs/murata_rebuild_sample_selection_report.md`

The JSONL file must contain one selected file per line.

Suggested JSONL schema:

```json
{
  "source_uri": "s3://...",
  "file_name": "...",
  "file_type": "java|sql|xlsx|docx|pptx|image|config|text|unknown",
  "module_or_domain": "accounts_payable|journal_base|payment_request|receiving|system_management|approval|reporting|unknown",
  "related_target_questions": ["Q1", "Q2"],
  "expected_evidence_type": ["schema", "code", "business_process"],
  "selection_reason": "...",
  "priority": "high",
  "expected_entities": ["JOURNAL_BASE", "PAYMENT_REQ"],
  "risk_or_uncertainty": "..."
}
````

The Markdown report must include:

1. Summary of selected files
2. Coverage table by target question
3. Coverage table by evidence type
4. Coverage table by business module
5. Files selected with rationale
6. Expected evidence for each question
7. Missing coverage / risks
8. Recommendation for R2
9. Whether existing inventory or S3 listing was used
10. Whether R1 quality gate passed or failed

---

## R1 Quality Gate

R1 passes only if:

1. All five target questions have at least two supporting files.
2. Q2 has at least one JOURNAL_BASE schema file and one JOURNAL_BASE-related code file.
3. Q3 has evidence candidates for SUN_REQUEST, JOURNAL_BASE, and RECEIVING_JOURNAL.
4. Q4 has enough process evidence to cover:
   订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表
5. Q5 has Payment Request and approval/status related evidence.
6. At least one database schema source is selected.
7. At least one Java Action / Service / Model source is selected.
8. At least one SQL / Mapper / DAO source is selected if available.
9. Selected sample size is between 15 and 30 unless explicitly justified.
10. R1 does not execute parsing, embedding, graph extraction, QA, or database writes.

If the quality gate fails, do not proceed to R2.

Instead, report missing coverage and propose how to improve sample selection.

---

## State Update

After completing R1, update `docs/task_state.md`:

* Current Phase Status: completed
* Completed Outputs:

  * `data/registry/murata_rebuild_v1_sample_files.jsonl`
  * `docs/murata_rebuild_sample_selection_report.md`
* Latest Findings
* Risks / Issues
* Recommended Next Phase: R2
* Next Phase Prompt: `docs/prompts/phase_r2_parse_quality_check.md`

Then stop and wait for user review.
