# Phase R11 — Hybrid Retrieval & QA Terminal Validation

## Objective

Validate the rebuilt Murata GraphRAG knowledge base through an end-to-end hybrid retrieval and QA flow.

R11 is a **hybrid retrieval + QA validation phase**.

R11 must not re-import Neptune data.  
R11 must not regenerate embeddings.  
R11 must not write LanceDB.  
R11 must not run graph extraction.  
R11 must not modify baseline data.  
R11 must not proceed to R12 automatically.

The purpose of R11 is to answer one key question:

> Can the rebuilt LanceDB vector store and rebuilt Neptune graph work together to answer the five target QA questions accurately, with clear evidence display?

R11 should validate:

1. Vector retrieval from LanceDB.
2. Graph retrieval from Neptune.
3. Entity extraction / graph search term generation.
4. Context fusion.
5. Answer generation.
6. Evidence display.
7. Debug visibility.
8. Answer quality against the five target QA questions.

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
Neptune Graph ID: g-nbuyck5yl8
Neptune endpoint: g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com
AWS region: ap-northeast-1
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
R7: graph normalization, deduplication, integrity check
R8: Neptune dry-run / import preview
R9: Neptune sample live import and validation
R10: full Neptune import and graph validation
```

R10 result:

```text
R10 full Neptune import passed 26/26 quality gates.
Neptune graph imported:
- 381 rebuild nodes
- 703 rebuild edges

LanceDB vector store from R5:
- 51 vector records
- collection: murata_e2e_murata_rebuild_v1

Baseline data remains untouched.
```

---

## Control Files to Read

Before executing R11, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r11_hybrid_retrieval_qa_validation.md`

Also read previous phase prompts/reports if needed:

```text
docs/prompts/phase_r5_embedding_lancedb.md
docs/prompts/phase_r10_neptune_full_import_validation.md

docs/murata_rebuild_r5_retrieval_quality_report.md
docs/murata_rebuild_r10_full_import_report.md
docs/murata_rebuild_r10_graph_query_validation_report.md
docs/murata_rebuild_r10_next_step_recommendation.md
```

Read artifacts as needed:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/retrieval_results_r5.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/retrieval_metrics_r5.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/embedding_records_r5.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_key_entity_queries_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_neighbor_queries_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q3_path_validation_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q4_path_validation_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q5_oa_validation_r10.json
```

If any critical QA/retrieval configuration file is missing, report it clearly and create only the minimal required validation wrapper if needed.

---

## Required Pre-checks

Before running QA validation, perform these checks.

### 1. Check LanceDB Vector Store

Verify:

```text
LanceDB path: ~/projects/data/vector_store/lancedb
Collection: murata_e2e_murata_rebuild_v1
Expected record count: 51
```

Report:

```text
collection exists
record count
vector dimension
metadata fields available
sample chunk IDs
```

Do not write LanceDB.

### 2. Check Neptune Graph

Verify:

```text
Neptune Graph ID: g-nbuyck5yl8
run_id: murata_rebuild_v1
dataset: murata
Expected nodes: 381
Expected edges: 703
```

Run read-only count queries:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS nodes
```

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS edges
```

Do not write Neptune.

### 3. Check Model Configuration

R11 may call Bedrock text LLM for final answer generation.

Preferred text model:

```text
jp.anthropic.claude-sonnet-4-6
```

Check `.env` / settings for:

```text
TEXT_LLM_MODEL_ID
BEDROCK_MODEL_ID
AWS_REGION
```

Report:

```text
actual text model used
env var source
AWS region
Bedrock client status
```

If the project still uses older Sonnet model, report it clearly.
Do not change model configuration unless explicitly necessary.

### 4. Check QA / Retrieval Components

Locate existing modules or scripts for:

```text
qa_terminal
retrieval chain
LanceDB retriever
NeptuneGraphRetriever
QueryEntityExtractor
ContextBuilder
AnswerGenerator
fusion logic
```

If the existing `scripts/qa_terminal.py` can be configured for rebuild run, use it or create a controlled R11 test runner.

Do not modify core code unless needed to fix configuration bugs.
If modification is required, keep it minimal and report all changed files.

---

## Target QA Questions

R11 must validate the original five target questions.

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

## R11 Scope

R11 includes:

1. Validate LanceDB rebuild collection.
2. Validate Neptune rebuild graph.
3. Configure hybrid retrieval to use:

   * LanceDB collection `murata_e2e_murata_rebuild_v1`
   * Neptune graph `g-nbuyck5yl8`
   * `run_id=murata_rebuild_v1`
   * `dataset=murata`
4. Run retrieval for Q1-Q5.
5. Run graph retrieval for Q1-Q5.
6. Fuse vector and graph evidence.
7. Generate answers for Q1-Q5.
8. Produce debug traces.
9. Produce human-readable QA result report.
10. Evaluate answer quality.
11. Recommend next phase.

R11 excludes:

1. Full Neptune import.
2. Neptune write.
3. Neptune delete.
4. LanceDB write.
5. Embedding generation.
6. Graph extraction.
7. VLM calls.
8. Document parsing.
9. Baseline modification.
10. Proceeding to R12 automatically.

---

## Retrieval Configuration

Use hybrid retrieval.

### Vector Retrieval

Use:

```text
LanceDB collection: murata_e2e_murata_rebuild_v1
top_k_vector: 10
```

For each vector hit, capture:

```text
chunk_id
score / distance
rank
source
source_uri
source_file_name
chunk_purpose
summary_type
related_target_questions
expected_entities
text preview
```

### Graph Retrieval

Use:

```text
Neptune graph ID: g-nbuyck5yl8
run_id: murata_rebuild_v1
dataset: murata
depth: 2
max_edges: 30
```

For each graph hit, capture:

```text
matched entity
entity_id
entity_type
relation path
source node
target node
relation type
evidence preview
source_chunk_ids
related_target_questions
```

### Entity Extraction

For each question, extract or infer:

```text
entity mentions
business terms
table names
field names
code module names
Japanese / Chinese aliases
English aliases
```

Do not rely only on exact string matching.

Special terms:

```text
仕訳基礎 → JOURNAL_BASE
应付管理 / 応付管理 → AP / accounts payable process
付款申请 / 付款申請 / 支払申請 → PAYMENT_REQ / Payment Request
对账单 / 対帳単 → RECEIVING_LIST / receiving list
SUN_REQUEST
RECEIVING_JOURNAL
PAYMENT_RECEIVING
OA系统 / OA系統
```

If current QueryEntityExtractor cannot map these terms, record it as an issue and use fallback search terms.

---

## Context Fusion Requirements

For each question, build a fused context with:

```text
vector evidence
graph evidence
deduplicated sources
source ranking
target-question relevance
evidence type
```

Recommended fusion priority:

### Q1

Priority:

```text
process summaries
business process graph paths
PAYMENT_REQ / PAYMENT_RECEIVING / RECEIVING_LIST / JOURNAL_BASE chunks
Action / Service code summaries
```

### Q2

Priority:

```text
JOURNAL_BASE schema
JOURNAL_BASE graph neighbors
JournalBaseAction / JournalBaseService / JournalBaseServiceImpl
RECEIVING_JOURNAL relation evidence
```

### Q3

Priority:

```text
SUN_REQUEST
JOURNAL_BASE
RECEIVING_JOURNAL
joins_on relations
bridge tables
V_PAYMENT_REQ_FILE / V_RECEIVING_LIST
SQL / schema raw chunks
```

### Q4

Priority:

```text
semantic_map_summary
Q4 graph path
BusinessStep nodes
generates / depends_on / relates_to
Q4 CSV preview if available
```

### Q5

Priority:

```text
oa_migration_summary
OA nodes and API endpoints
PAYMENT_REQ
PAYMENT_RECEIVING
STATUS
BILL_NO
APPROVAL_BY / APPROVAL_TIME / APPROVAL_REMARK
PaymentReqAction / PaymentReqService
```

---

## Answer Generation Requirements

R11 may use Bedrock text LLM to generate final answers.

Answers must be grounded in retrieved evidence.

Each answer must include:

```text
1. direct answer
2. structured details
3. evidence references
4. limitations / uncertainties
```

For Q4, answer must output CSV only in the final answer body, but the R11 report may include debug notes separately.

For Q4 final answer, enforce:

```text
nodes.csv
id,label,type

edges.csv
from,to,relation

relation ∈ {generates, depends_on, relates_to}
```

For Q5, answer should be structured into:

```text
1. 新业务流程
2. 数据流转关系
3. 系统改造清单
4. 对现有流程影响
5. 风险 / 待确认点
```

---

## Debug Display Requirements

R11 must produce readable debug output for each question.

For each Q1-Q5, record:

```text
question
detected language
extracted entity mentions
graph search terms
matched graph entities
vector evidence top-k
graph evidence top-k
fusion result
answer
citations / evidence ids
latency
warnings
```

The output must be easy to inspect.

Avoid dumping unreadable huge JSON only.

---

## Evaluation Criteria

For each answer, evaluate manually/rule-based against target requirements.

### Scoring

Use 0–5 scale:

```text
5 = excellent, fully grounded, complete
4 = good, minor gaps
3 = usable, some missing detail
2 = weak, major gaps
1 = poor
0 = failed
```

### Per-question pass criteria

Q1 passes if answer includes:

```text
process steps
tables per step
key fields
code modules where available
```

Q2 passes if answer includes:

```text
JOURNAL_BASE role
schema / key fields
business process relation
code modules
```

Q3 passes if answer includes:

```text
SUN_REQUEST
JOURNAL_BASE
RECEIVING_JOURNAL
association fields
SQL/Mapper/code evidence
data flow path
```

Q4 passes if answer includes:

```text
nodes.csv
edges.csv
only allowed relation types
continuous path A → B → C → D
complete business chain or clearly marked partial
```

Q5 passes if answer includes:

```text
new process
AP system vs OA system boundary
data sent to OA
data returned from OA
key fields
DB changes
API changes
code module changes
business impact
```

R11 overall passes if:

```text
at least 4/5 questions score >= 4
no question score < 3
Q3 score >= 4
Q4 score >= 4
Q5 score >= 4
```

If R11 fails, recommend targeted fixes.

---

## Baseline Comparison

If feasible, compare against previous baseline behavior.

Baseline:

```text
run_id: murata_live_v1
LanceDB collection: murata_e2e_murata_live_v1
Neptune graph contains baseline nodes/edges
```

Comparison is optional.

If implemented, compare:

```text
rebuild vector hits vs baseline vector hits
rebuild graph hits vs baseline graph hits
answer quality
entity match quality
noise level
```

Do not modify baseline.

If baseline comparison is too risky or time-consuming, skip and report that it was not performed.

---

## Required R11 Artifacts

Create artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required files:

```text
hybrid_retrieval_results_r11.jsonl
vector_retrieval_results_r11.jsonl
graph_retrieval_results_r11.jsonl
fusion_contexts_r11.jsonl
qa_answers_r11.jsonl
qa_evaluation_r11.json
qa_debug_traces_r11.jsonl
qa_failures_r11.jsonl
qa_latency_metrics_r11.json
```

Optional files:

```text
baseline_comparison_r11.json
qa_terminal_config_r11.json
```

---

## Required R11 Reports

Create reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r11_hybrid_retrieval_report.md
docs/murata_rebuild_r11_qa_answers_report.md
docs/murata_rebuild_r11_qa_evaluation_report.md
docs/murata_rebuild_r11_debug_trace_report.md
docs/murata_rebuild_r11_failures_report.md
docs/murata_rebuild_r11_next_step_recommendation.md
```

---

## R11 Quality Gate

R11 passes only if:

1. LanceDB rebuild collection is accessible.
2. LanceDB rebuild collection has expected records or count is explained.
3. Neptune rebuild graph is accessible.
4. Neptune rebuild graph has expected nodes or count is explained.
5. Neptune rebuild graph has expected edges or count is explained.
6. Q1-Q5 vector retrieval runs.
7. Q1-Q5 graph retrieval runs.
8. Q1-Q5 fusion contexts are generated.
9. Q1-Q5 answers are generated.
10. Q1 score >= 3.
11. Q2 score >= 3.
12. Q3 score >= 4.
13. Q4 score >= 4.
14. Q5 score >= 4.
15. At least 4/5 questions score >= 4.
16. No hallucinated table / field / code module dominates final answer.
17. Q4 relation types are restricted to `generates`, `depends_on`, `relates_to`.
18. Q5 clearly separates existing system evidence from proposed OA migration design.
19. Debug traces are generated.
20. No Neptune writes occur.
21. No LanceDB writes occur.
22. No embedding generation occurs.
23. No graph extraction occurs.
24. No VLM calls occur.
25. No baseline data is modified.
26. R11 does not proceed to R12 automatically.

If R11 fails:

1. do not proceed to R12
2. report failure reasons
3. recommend one of:

   * improve entity extraction / alias mapping
   * improve graph retrieval query templates
   * improve vector metadata filtering
   * adjust fusion ranking
   * regenerate selected summaries
   * add missing chunks
   * refine answer prompt
   * create R11.5 debug / tuning phase

---

## Success Criteria

R11 is successful if:

```text
1. hybrid retrieval works end-to-end
2. vector and graph evidence are both visible
3. Q1-Q5 answers are grounded
4. Q3/Q4/Q5 answers are strong enough for demo
5. debug display is readable
6. no baseline is modified
```

R11 proves that the rebuilt GraphRAG can support the target Murata QA scenarios.

---

## Post-R11 Recommendation Logic

If R11 passes:

Recommend one of:

```text
R12 — QA Terminal UX Improvement + Demo Packaging
```

or:

```text
R12 — Full Murata Expansion Plan
```

depending on user goal.

If R11 passes but UI/debug display is weak:

Recommend:

```text
R11.5 — QA Terminal Display Enhancement
```

If R11 retrieval is good but answer quality is weak:

Recommend:

```text
R11.5 — Answer Prompt / Context Fusion Tuning
```

If graph retrieval is weak:

Recommend:

```text
R11.5 — Entity Extraction and Graph Query Template Tuning
```

---

## Forbidden Actions

R11 must not:

1. write Neptune
2. delete Neptune data
3. write LanceDB
4. regenerate embeddings
5. run graph extraction
6. run VLM
7. parse documents
8. modify baseline data
9. proceed to R12 automatically

---

## Allowed Actions

R11 may:

1. read LanceDB rebuild collection
2. query Neptune rebuild graph
3. call Bedrock text LLM for final answers
4. run retrieval-only and QA validation scripts
5. create debug traces
6. create reports
7. update `docs/task_state.md`

---

## State Update

After completing R11, update `docs/task_state.md`:

```markdown
## Current Phase

`R11`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/hybrid_retrieval_results_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/vector_retrieval_results_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/graph_retrieval_results_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/fusion_contexts_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_answers_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_evaluation_r11.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_debug_traces_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_failures_r11.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_latency_metrics_r11.json`
- `docs/murata_rebuild_r11_hybrid_retrieval_report.md`
- `docs/murata_rebuild_r11_qa_answers_report.md`
- `docs/murata_rebuild_r11_qa_evaluation_report.md`
- `docs/murata_rebuild_r11_debug_trace_report.md`
- `docs/murata_rebuild_r11_failures_report.md`
- `docs/murata_rebuild_r11_next_step_recommendation.md`

## Latest Findings

Summarize hybrid retrieval quality, QA results, and evidence quality.

## Risks / Issues

Summarize weak questions, retrieval gaps, answer issues, and UI/debug issues.

## Recommended Next Phase

`R12`

## Next Phase Prompt

`docs/prompts/phase_r12_qa_terminal_demo_packaging.md`
```

Then stop and wait for user review.

Do not proceed to R12 automatically.
