# Phase R4 — Summary Chunk Generation

## Objective

Generate high-quality summary chunks from the R3 `summary_candidate` chunks.

R4 exists to convert dense code / schema / process / visual evidence into answer-friendly summary chunks before embedding and graph extraction.

R4 must not perform embedding.  
R4 must not write LanceDB.  
R4 must not query or write Neptune.  
R4 must not run graph extraction.  
R4 must not run QA terminal.

The output of R4 will be reviewed before moving to R5.

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
future LanceDB collection: murata_e2e_murata_rebuild_v1
```

R3 generated:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunks_r3.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/r3_summary_candidates.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/r3_chunk_distribution.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/r3_coverage_report.json
```

R3 identified:

* 52 total chunks
* 11 summary candidates
* 38 chunks marked `should_embed=true`
* 46 chunks marked `should_extract_graph=true`

R4 should process only the R3 summary candidates, plus any directly related source chunks needed for context.

---

## Control Files to Read

Before executing R4, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r4_summary_chunks.md`
4. `docs/prompts/phase_r3_chunking_quality.md`

Also read:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/chunks_r3.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/r3_summary_candidates.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/r3_coverage_report.json
```

Read R2/R2.5 reports if needed:

```text
docs/murata_rebuild_target_question_evidence_matrix.md
docs/murata_rebuild_vlm_quality_report.md
docs/murata_rebuild_process_chain_evidence_report.md
```

---

## Required Pre-checks

Before summarization:

1. Confirm that all summary candidate chunk IDs exist in `chunks_r3.jsonl`.

2. Confirm that all referenced key chunks in the R3 report exist.

3. Confirm that original target question mapping is preserved:

   * Q1: 应付管理业务流程
   * Q2: JOURNAL_BASE 表作用
   * Q3: SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联
   * Q4: 应付管理完整业务流程 Semantic Map
   * Q5: 付款申请审批迁移到 OA 的系统改造方案

4. If R3 report labels differ from the original question meanings, do not rewrite R3 artifacts, but record the mismatch in the R4 report and use the original Q1–Q5 definitions for all R4 summaries.

---

## Target QA Questions

R4 summaries must support the original five target QA questions.

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

## R4 Scope

R4 includes:

1. Load R3 chunks.
2. Load R3 summary candidates.
3. Generate summary chunks only for `summary_candidate=true` chunks.
4. Produce target-question-focused summaries.
5. Preserve provenance from original chunks.
6. Create summary quality reports.
7. Prepare the clean input set for R5 embedding.

R4 excludes:

1. Embedding generation.
2. LanceDB writes.
3. Neptune queries.
4. Neptune writes.
5. Graph extraction.
6. QA terminal.
7. Full answer generation.
8. Full document re-parsing.
9. VLM calls.

---

## LLM Usage Policy

R4 may use Bedrock Claude text model for summary generation.

R4 must not use VLM.

Before calling the LLM, confirm which text model is used from config / `.env`.

Recommended model source:

```text
TEXT_LLM_MODEL_ID or BEDROCK_MODEL_ID
```

If the model is not configured, stop and report.

All LLM outputs must be saved with enough metadata for review.

If live LLM is disabled or unavailable, R4 may generate rule-based extractive summaries, but must clearly mark:

```text
summary_source = rule_based
```

If LLM is used:

```text
summary_source = llm
```

---

## Summary Chunk Types

R4 should generate the following summary chunk types as applicable:

### `code_summary`

For Java Action / Service / ServiceImpl / DAO / Mapper chunks.

Purpose:

* explain what the code does
* identify tables accessed
* identify key fields
* identify status transitions
* identify methods/classes involved
* connect code to target questions

### `schema_summary`

For dense DDL / table / view / Excel schema chunks.

Purpose:

* explain table role
* list key fields
* list join keys
* list status fields
* explain relationship to business process

### `process_summary`

For VLM / DOCX / PPTX / business process chunks.

Purpose:

* explain workflow steps
* list systems
* list inputs/outputs
* identify related tables
* identify target question support

### `semantic_map_summary`

For chunks supporting Q4.

Purpose:

* extract candidate nodes
* extract candidate edges
* map process chain steps
* restrict relation candidates to:

  * generates
  * depends_on
  * relates_to

### `oa_migration_summary`

For chunks supporting Q5.

Purpose:

* identify current approval flow
* identify tables/fields impacted by OA migration
* identify API candidates
* identify Action / Service modules to modify
* identify callback / status update requirements

---

## Summary Output Schema

Create:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_chunks_r4.jsonl
```

Each line must follow this schema:

```json
{
  "chunk_id": "summary_r4_xxx",
  "run_id": "murata_rebuild_v1",
  "dataset": "murata",
  "summary_type": "code_summary|schema_summary|process_summary|semantic_map_summary|oa_migration_summary",
  "is_summary": true,
  "parent_chunk_ids": ["chunk_r3_xxx"],
  "source_uri": "s3://...",
  "source_file_name": "...",
  "source_type": "code|sql|spreadsheet|docx|pptx|visual|config|mixed",
  "text": "...",
  "summary_text": "...",
  "chunk_purpose": "summary",
  "chunk_quality": "high|medium|low",
  "quality_score": 0.0,
  "should_embed": true,
  "should_extract_graph": true,
  "related_target_questions": ["Q1", "Q2"],
  "expected_entities": ["JOURNAL_BASE", "PAYMENT_REQ"],
  "key_tables": ["..."],
  "key_fields": ["..."],
  "key_code_modules": ["..."],
  "candidate_graph_nodes": [
    {
      "id": "...",
      "label": "...",
      "type": "..."
    }
  ],
  "candidate_graph_edges": [
    {
      "from": "...",
      "to": "...",
      "relation": "generates|depends_on|relates_to|reads_from|writes_to|calls|contains|references"
    }
  ],
  "evidence_strength": "strong|medium|weak",
  "summary_source": "llm|rule_based",
  "model_id": "...",
  "confidence": 0.0,
  "warnings": []
}
```

If some fields are not applicable, use empty arrays or null values.

---

## LLM Prompt Requirements

For each summary candidate, the LLM prompt must instruct the model:

1. Do not invent facts.
2. Use only the source chunk content.
3. Preserve technical names exactly.
4. Preserve table names exactly.
5. Preserve field names exactly.
6. Preserve class and method names exactly.
7. If uncertain, say `"unknown"` or leave the field empty.
8. Focus on the five target QA questions.
9. Produce structured JSON only.
10. Keep summary concise but evidence-rich.

The LLM should not produce final answers to Q1–Q5.
It should produce reusable summary chunks for retrieval.

---

## R4 Summary Generation Strategy

For each summary candidate:

1. Inspect chunk metadata.

2. Determine summary type:

   * code evidence → `code_summary`
   * schema evidence → `schema_summary`
   * process / visual evidence → `process_summary`
   * Q4-specific evidence → also produce or enrich `semantic_map_summary`
   * Q5-specific evidence → also produce or enrich `oa_migration_summary`

3. Generate one summary chunk per candidate unless the candidate supports multiple very different target questions.

4. If one source chunk is dense and supports multiple questions, it may produce multiple summary chunks, but do not overproduce.

Recommended max output:

```text
11 source candidates → 11 to 20 summary chunks
```

Do not generate more than 30 summary chunks in R4 unless explicitly justified.

---

## R4 Quality Gate

R4 passes only if:

1. All R3 summary candidates are either summarized or explicitly skipped with reason.
2. `summary_chunks_r4.jsonl` is created.
3. At least one summary chunk supports Q1.
4. At least one summary chunk supports Q2.
5. At least one summary chunk supports Q3.
6. At least one summary chunk supports Q4.
7. At least one summary chunk supports Q5.
8. Summary chunks preserve source provenance with `parent_chunk_ids`.
9. Summary chunks preserve exact technical names, including table names and fields.
10. Summary chunks are marked `should_embed=true`.
11. Summary chunks are marked `is_summary=true`.
12. Any LLM raw outputs or failures are logged.
13. No embedding, LanceDB, Neptune, graph extraction, or QA operations are executed.

If R4 quality gate fails, do not proceed to R5.

---

## Required Outputs

Artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required:

```text
summary_chunks_r4.jsonl
summary_generation_failures_r4.jsonl
summary_llm_raw_outputs_r4.jsonl
embedding_input_candidates_r4.jsonl
```

Reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required:

```text
docs/murata_rebuild_r4_summary_quality_report.md
docs/murata_rebuild_r4_target_question_summary_coverage.md
docs/murata_rebuild_r4_embedding_input_recommendation.md
```

`embedding_input_candidates_r4.jsonl` should include:

1. all R3 chunks with `should_embed=true`
2. all R4 summary chunks with `should_embed=true`
3. exclude R3 raw chunks that should be replaced by summary chunks if appropriate
4. mark replacement relationship:

```json
{
  "input_chunk_id": "summary_r4_xxx",
  "source": "r4_summary",
  "replaces_or_supplements": ["chunk_r3_xxx"],
  "recommended_for_embedding": true
}
```

---

## Forbidden Actions

R4 must not:

1. generate embeddings
2. write LanceDB
3. query Neptune
4. write Neptune
5. run graph extraction
6. run QA terminal
7. run VLM
8. delete baseline data
9. modify core code unless absolutely necessary
10. proceed to R5 automatically

---

## Allowed Actions

R4 may:

1. read R3 artifacts
2. read R2/R2.5 reports
3. call Bedrock text LLM for summarization
4. create summary artifacts
5. create embedding input candidate artifacts
6. create reports
7. update `docs/task_state.md`

---

## Reporting Requirements

At completion, output a Phase R4 report with:

1. number of R3 summary candidates
2. number of candidates summarized
3. number of summary chunks generated
4. summary type distribution
5. target question coverage
6. key tables preserved
7. key fields preserved
8. key code modules preserved
9. LLM model used
10. LLM failures or fallbacks
11. whether R4 quality gate passed
12. whether R5 embedding is recommended
13. generated files
14. warnings and risks

---

## State Update

After completing R4, update `docs/task_state.md`:

```markdown
## Current Phase

`R4`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_chunks_r4.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_generation_failures_r4.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/summary_llm_raw_outputs_r4.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_input_candidates_r4.jsonl`
- `docs/murata_rebuild_r4_summary_quality_report.md`
- `docs/murata_rebuild_r4_target_question_summary_coverage.md`
- `docs/murata_rebuild_r4_embedding_input_recommendation.md`

## Latest Findings

Summarize summary generation quality and coverage.

## Risks / Issues

Summarize remaining risks.

## Recommended Next Phase

`R5`

## Next Phase Prompt

`docs/prompts/phase_r5_embedding_lancedb.md`
```

Then stop and wait for user review.

Do not proceed to R5 automatically.
