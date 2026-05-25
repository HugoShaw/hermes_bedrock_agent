 
# Phase R5 — Embedding Generation + LanceDB Storage + Retrieval Validation

## Objective

Generate embeddings for the approved R4 embedding input candidates, write them into the local LanceDB vector store, and validate retrieval recall for the five target QA questions.

R5 is a **vector retrieval validation phase**.

R5 must not perform graph extraction.  
R5 must not query or write Neptune.  
R5 must not run final QA answer generation.  
R5 must not run QA terminal.  
R5 must not proceed to R6 automatically.

The purpose of R5 is to answer one key question:

> Are the R3/R4 chunks good enough for vector retrieval before we proceed to graph extraction and Neptune loading?

If R5 retrieval quality is poor, stop and recommend improvements before moving forward.

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
LanceDB collection: murata_e2e_murata_rebuild_v1
LanceDB path: ~/projects/data/vector_store/lancedb
```

R3 generated rule-based chunks:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunks_r3.jsonl
```

R4 generated summary chunks and embedding input candidates:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_chunks_r4.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_input_candidates_r4.jsonl
```

R4 reported:

* 38 R3 chunks marked `should_embed=true`
* 13 R4 summary chunks marked `should_embed=true`
* total embedding input candidates: 51

---

## Control Files to Read

Before executing R5, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r5_embedding_lancedb.md`

Also read the previous phase prompt files if needed:

```text
docs/prompts/phase_r3_chunking_quality.md
docs/prompts/phase_r4_summary_chunks.md
```

Read R4 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_input_candidates_r4.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_chunks_r4.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunks_r3.jsonl
```

Read R4 reports if needed:

```text
docs/murata_rebuild_r4_summary_quality_report.md
docs/murata_rebuild_r4_target_question_summary_coverage.md
docs/murata_rebuild_r4_embedding_input_recommendation.md
```

---

## Required Pre-checks

Before generating embeddings, perform these checks.

### 1. Confirm Embedding Model

Verify the embedding model from `.env` / settings.

Expected model:

```text
amazon.titan-embed-text-v2:0
```

Likely environment variable:

```text
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
```

If the project uses a different setting name, report the actual setting name and value.

R5 must report:

* embedding model ID
* embedding provider
* AWS region
* embedding dimension if known
* whether the Bedrock embedding client initializes successfully

### 2. Confirm Text LLM Model for Future Phases

R4 used:

```text
apac.anthropic.claude-sonnet-4-20250514-v1:0
```

This is acceptable and R4 must not be rerun by default.

For future LLM phases, prefer:

```text
jp.anthropic.claude-sonnet-4-6
```

Before R5, check which text LLM model is configured:

* `TEXT_LLM_MODEL_ID`
* `BEDROCK_MODEL_ID`
* or another settings field

Do not rerun R4 in this phase.

Only report whether future text LLM phases are configured to use Sonnet 4.6.

### 3. Validate Input Candidates

Load:

```text
embedding_input_candidates_r4.jsonl
```

Validate:

1. All records have a chunk ID.
2. All records have text or summary text suitable for embedding.
3. All records have `run_id=murata_rebuild_v1`.
4. All records have `dataset=murata`.
5. All records have source metadata:

   * source_uri
   * source_file_name
   * source type
   * related_target_questions
6. All R4 summary chunks have:

   * `is_summary=true`
   * `should_embed=true`
   * `parent_chunk_ids`
7. No `data_sample` or `low_value` chunk is embedded.
8. Total candidate count is expected to be around 51.

If validation fails, stop and report the problem.

---

## Target QA Questions

R5 retrieval validation must use the original five target QA questions.

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

## R5 Scope

R5 includes:

1. Validate R4 embedding input candidates.
2. Generate embeddings for approved candidates.
3. Write vectors to local LanceDB collection:
   `murata_e2e_murata_rebuild_v1`
4. Preserve rich metadata for each vector.
5. Run retrieval-only validation for Q1–Q5.
6. Compare retrieval results with expected evidence.
7. Produce retrieval quality reports.
8. Recommend whether to proceed to R6.

R5 excludes:

1. Graph extraction.
2. Neptune query.
3. Neptune write.
4. QA answer generation.
5. QA terminal.
6. VLM calls.
7. Summary regeneration, unless R5 retrieval clearly fails and only a recommendation is made.
8. Automatic progression to R6.

---

## Embedding Input Strategy

Use:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_input_candidates_r4.jsonl
```

This file should contain:

1. R3 raw chunks with `should_embed=true`
2. R4 summary chunks with `should_embed=true`

R4 summaries should **supplement**, not replace, parent R3 chunks.

Reason:

* R3 raw chunks preserve exact SQL / code / schema details.
* R4 summary chunks improve semantic retrieval.
* Together they support hybrid semantic + keyword-like recall.

---

## Embedding Record Schema

Each LanceDB record must include at least:

```json
{
  "chunk_id": "chunk_or_summary_id",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "text": "...",
  "vector": [0.0],
  "source": "r3_chunk|r4_summary",
  "source_uri": "s3://...",
  "source_file_name": "...",
  "source_type": "code|sql|spreadsheet|docx|pptx|visual|config|mixed",
  "chunk_purpose": "schema_evidence|code_evidence|process_evidence|summary|visual_evidence|config_evidence",
  "summary_type": "code_summary|schema_summary|process_summary|semantic_map_summary|oa_migration_summary|null",
  "is_summary": true,
  "parent_chunk_ids": ["chunk_r3_xxx"],
  "related_target_questions": ["Q1", "Q2"],
  "expected_entities": ["JOURNAL_BASE", "PAYMENT_REQ"],
  "key_tables": ["..."],
  "key_fields": ["..."],
  "key_code_modules": ["..."],
  "should_embed": true,
  "should_extract_graph": true,
  "evidence_strength": "strong|medium|weak",
  "metadata": {
    "original_chunk_id": "...",
    "summary_source": "llm|rule_based|null",
    "model_id": "...",
    "confidence": 0.0
  }
}
```

If LanceDB schema has limitations, preserve fields under metadata, but do not discard:

* `chunk_id`
* `run_id`
* `dataset`
* `source_uri`
* `related_target_questions`
* `expected_entities`
* `chunk_purpose`
* `is_summary`
* `parent_chunk_ids`

---

## LanceDB Requirements

Use local LanceDB.

Default path:

```text
~/projects/data/vector_store/lancedb
```

Collection/table name:

```text
murata_e2e_murata_rebuild_v1
```

Before writing:

1. Check whether the collection already exists.
2. If it exists for the same `run_id=murata_rebuild_v1`, either:

   * drop/recreate it, if explicitly safe for rebuild collection only
   * or create a timestamped backup
   * or delete only records with `run_id=murata_rebuild_v1`

Never modify:

```text
murata_e2e_murata_live_v1
```

Never delete baseline data.

R5 must report which storage action was taken.

---

## Retrieval Validation Queries

After writing LanceDB, run retrieval-only tests.

Do not generate final answers.

Run these test queries:

### Q1 Query Set

```text
应付管理的业务流程是什么？每个步骤对应哪些表和字段？
```

```text
付款申请从对账单到审批再到支付的流程是什么？
```

Expected retrieval should include:

* process evidence
* PAYMENT_REQ
* PAYMENT_RECEIVING
* RECEIVING_LIST
* JOURNAL_BASE
* approval / STATUS
* code modules if available

---

### Q2 Query Set

```text
JOURNAL_BASE表在系统中的作用是什么？
```

```text
JOURNAL_BASE被哪些代码模块调用？它和对账单有什么关系？
```

Expected retrieval should include:

* JOURNAL_BASE schema summary
* JOURNAL_BASE schema evidence
* JournalBaseAction / JournalBaseService / JournalBaseServiceImpl
* RECEIVING_JOURNAL relation
* process evidence explaining JOURNAL_BASE role

---

### Q3 Query Set

```text
SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL三张表通过哪些字段关联？
```

```text
SUN_REQUEST和JOURNAL_BASE、RECEIVING_JOURNAL之间没有外键时，代码或SQL里如何关联？
```

Expected retrieval should include:

* SUN_REQUEST
* JOURNAL_BASE
* RECEIVING_JOURNAL
* join fields
* SQL / view evidence
* bridge table logic
* V_PAYMENT_REQ_FILE or related view if relevant

---

### Q4 Query Set

```text
请构建应付管理完整业务流程的Semantic Map，主链为订单、对账单、审批、付款申请、审批、支付、报表。
```

```text
应付管理从订单到对账单、付款申请、审批、支付、报表的主流程链是什么？
```

Expected retrieval should include:

* semantic_map_summary
* process_summary
* process chain chunks
* nodes / edges candidates
* relation candidates using generates / depends_on / relates_to

---

### Q5 Query Set

```text
付款申请审批迁移到OA系统，需要修改哪些表、接口和代码模块？
```

```text
如果付款申请在应付系统做单，OA系统审批并回写结果，应如何设计流程和数据流？
```

Expected retrieval should include:

* oa_migration_summary
* PAYMENT_REQ
* PAYMENT_RECEIVING
* STATUS
* BILL_NO
* approval fields
* PaymentReqAction
* PaymentReqService
* callback / API candidates

---

## Retrieval Test Parameters

Use:

```text
top_k = 10
```

Optionally also test:

```text
top_k = 5
top_k = 20
```

For each query, record:

1. query text
2. detected target question
3. retrieved chunk IDs
4. rank
5. score / distance / similarity
6. source type
7. whether each retrieved item is R3 raw or R4 summary
8. related_target_questions
9. expected_entities
10. source_uri
11. text preview
12. relevance judgment:

    * highly_relevant
    * partially_relevant
    * irrelevant
13. missing expected evidence

Relevance judgment can be rule-based using expected entities and target question metadata, but the report should still be human-reviewable.

---

## Retrieval Quality Metrics

Calculate per target question:

```text
top_5_hit
top_10_hit
expected_entity_coverage
summary_hit_count
raw_chunk_hit_count
irrelevant_count
missing_evidence
```

Also calculate overall:

```text
total_queries
top_5_success_rate
top_10_success_rate
average_relevant_items_top10
summary_vs_raw_ratio
```

Expected minimum quality gate:

1. Each target question has at least one highly relevant result in top 5.
2. Each target question has at least three relevant results in top 10.
3. Q2 retrieves `JOURNAL_BASE` evidence in top 5.
4. Q3 retrieves `SUN_REQUEST`, `JOURNAL_BASE`, and `RECEIVING_JOURNAL` evidence in top 10.
5. Q4 retrieves `semantic_map_summary` or process-chain evidence in top 5.
6. Q5 retrieves `oa_migration_summary` or OA/payment approval evidence in top 5.
7. No query top 10 is dominated by irrelevant raw code chunks.
8. R4 summary chunks appear in retrieval results for semantic questions.
9. LanceDB write succeeds.
10. No Neptune, graph extraction, QA answer generation, or QA terminal is executed.

If R5 quality gate fails:

1. do not proceed to R6
2. identify weak queries
3. identify missing evidence
4. recommend one of:

   * regenerate specific summaries with better prompt
   * add missing chunks to embedding input
   * remove noisy chunks
   * adjust metadata filtering
   * adjust query rewriting
   * return to R3 or R4

---

## Required Outputs

Artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required files:

```text
embedding_records_r5.jsonl
embedding_failures_r5.jsonl
lancedb_load_report_r5.json
retrieval_results_r5.jsonl
retrieval_metrics_r5.json
weak_queries_r5.jsonl
```

Reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r5_embedding_report.md
docs/murata_rebuild_r5_lancedb_load_report.md
docs/murata_rebuild_r5_retrieval_quality_report.md
docs/murata_rebuild_r5_weak_queries_report.md
docs/murata_rebuild_r5_next_step_recommendation.md
```

---

## Forbidden Actions

R5 must not:

1. run graph extraction
2. query Neptune
3. write Neptune
4. run QA terminal
5. generate final answers
6. call VLM
7. regenerate summaries unless only as a recommendation
8. delete baseline LanceDB collection
9. delete baseline artifacts
10. proceed to R6 automatically

---

## Allowed Actions

R5 may:

1. read R3/R4 artifacts
2. call Bedrock embedding model
3. write to local LanceDB rebuild collection
4. run LanceDB retrieval tests
5. create reports
6. update `docs/task_state.md`

---

## R5 Quality Gate

R5 passes only if:

1. Embedding model is confirmed.
2. Input candidates are validated.
3. Embeddings are generated for all valid candidates or failures are clearly reported.
4. LanceDB collection `murata_e2e_murata_rebuild_v1` is created or updated.
5. Retrieval validation runs for all Q1–Q5 query sets.
6. Each target question has at least one highly relevant result in top 5.
7. Each target question has at least three relevant results in top 10.
8. Q2 retrieves `JOURNAL_BASE` evidence in top 5.
9. Q3 retrieves `SUN_REQUEST`, `JOURNAL_BASE`, and `RECEIVING_JOURNAL` evidence in top 10.
10. Q4 retrieves `semantic_map_summary` or process-chain evidence in top 5.
11. Q5 retrieves `oa_migration_summary` or OA/payment approval evidence in top 5.
12. R4 summary chunks are actually retrieved for semantic / process questions.
13. No forbidden operations are executed.

If R5 fails, stop and report improvement options.

---

## Reporting Requirements

At completion, output a Phase R5 report with:

1. embedding model used
2. number of input candidates
3. number of embeddings generated
4. embedding failures
5. LanceDB path and collection name
6. number of vectors written
7. retrieval queries tested
8. per-question retrieval metrics
9. weak queries
10. whether R5 quality gate passed
11. whether R6 graph extraction is recommended
12. generated files
13. warnings and risks

---

## State Update

After completing R5, update `docs/task_state.md`:

```markdown
## Current Phase

`R5`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_records_r5.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_failures_r5.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/lancedb_load_report_r5.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/retrieval_results_r5.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/retrieval_metrics_r5.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/weak_queries_r5.jsonl`
- `docs/murata_rebuild_r5_embedding_report.md`
- `docs/murata_rebuild_r5_lancedb_load_report.md`
- `docs/murata_rebuild_r5_retrieval_quality_report.md`
- `docs/murata_rebuild_r5_weak_queries_report.md`
- `docs/murata_rebuild_r5_next_step_recommendation.md`

## Latest Findings

Summarize embedding and retrieval validation results.

## Risks / Issues

Summarize weak queries and missing evidence.

## Recommended Next Phase

`R6`

## Next Phase Prompt

`docs/prompts/phase_r6_graph_extraction.md`
```

Then stop and wait for user review.

Do not proceed to R6 automatically.

 
