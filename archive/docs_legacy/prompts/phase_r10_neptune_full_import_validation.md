# Phase R10 — Full Neptune Import & Graph Validation

## Objective

Execute the full Neptune import for the Murata rebuild graph and validate that the complete graph can be queried correctly.

R10 is a **full Neptune import and graph validation phase**.

R10 must not run hybrid QA.  
R10 must not run final answer generation.  
R10 must not run QA terminal.  
R10 must not call Bedrock.  
R10 must not generate embeddings.  
R10 must not write LanceDB.  
R10 must not proceed to R11 automatically.

The purpose of R10 is to answer one key question:

> Can the complete R7/R8 canonical graph be imported into Neptune and validated with graph queries, without modifying baseline data?

R10 should import the full canonical graph:

```text
381 nodes + 703 edges
````

R10 should use MERGE+SET so that the 20 sample nodes and 10 sample edges imported in R9 are updated idempotently, not duplicated.

---

## Project Context

Project root:

```text
~/projects/hermes_bedrock_agent
```

Rebuild target:

```text
run_id: murata_rebuild_v1
dataset: murata
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
```

R9 result:

```text
R9 sample live import passed 23/23 quality gates.
Neptune connectivity: SUCCESS
Sample nodes imported: 20/20
Sample edges created: 10/30 attempted
Failures: 0
Read-back nodes: 20
Read-back edges: 10
JOURNAL_BASE found: YES
PAYMENT_REQ found: YES
Path traversal works.
Baseline was not modified.
```

R10 should proceed with full import without rolling back the R9 sample data by default.

---

## Control Files to Read

Before executing R10, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r10_neptune_full_import_validation.md`

Also read previous phase prompts/reports if needed:

```text
docs/prompts/phase_r8_neptune_dryrun_preview.md
docs/prompts/phase_r9_neptune_sample_import_validation.md
docs/murata_rebuild_r8_neptune_dryrun_report.md
docs/murata_rebuild_r8_import_validation_report.md
docs/murata_rebuild_r9_neptune_sample_import_report.md
docs/murata_rebuild_r9_sample_readback_validation_report.md
docs/murata_rebuild_r9_next_step_recommendation.md
```

Read R8/R9 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_nodes_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edges_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_node_merge_params_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edge_merge_params_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_rollback_r8.cypher
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_import_manifest_r8.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_import_validation_r8.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_import_summary_r9.json
```

If any critical R8 full import file is missing, stop and report.

---

## R10 Execution Mode

Default R10 mode:

```text
FULL_NEPTUNE_IMPORT_AND_GRAPH_VALIDATION
```

Allowed by this phase:

```text
1. Neptune connectivity check
2. Count existing murata_rebuild_v1 data
3. Full node import with MERGE+SET
4. Full edge import with MERGE+SET
5. Read-back validation
6. Graph structure validation
7. Q1-Q5 graph query validation
8. Q4 path validation
9. Generate import reports
```

Not allowed by default:

```text
1. Full graph clear
2. Deleting baseline data
3. Deleting existing rebuild data unless explicitly confirmed
4. Hybrid QA
5. QA terminal
6. Answer generation
7. Bedrock calls
8. Embedding generation
9. LanceDB writes
10. Proceeding to R11 automatically
```

---

## Explicit Safety Rules

### Do Not Touch Baseline

Never delete, overwrite, or modify baseline data:

```text
run_id = murata_live_v1
LanceDB collection = murata_e2e_murata_live_v1
```

### Always Scope to Rebuild Run

All imported full graph records must have:

```text
run_id = murata_rebuild_v1
dataset = murata
```

### Do Not Rollback by Default

R9 sample data should remain in Neptune.

Reason:

```text
MERGE+SET is idempotent.
The full import will update the 20 sample nodes / 10 sample edges, not duplicate them.
```

Before full import, check existing rebuild data count.

Expected from R9:

```text
nodes = 20
edges = 10
```

If actual count differs:

1. Do not delete automatically.
2. Report the count.
3. Continue if MERGE import is still safe.
4. Stop only if there is a clear data conflict or inconsistent run_id/dataset.

### Rollback Script

Rollback script exists from R8:

```text
neptune_rollback_r8.cypher
```

R10 may generate or update a rollback note, but must not execute rollback unless explicitly confirmed by the user.

---

## Neptune Target

Expected Neptune Graph endpoint:

```text
g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com
```

Expected Graph ID:

```text
g-nbuyck5yl8
```

Expected region:

```text
ap-northeast-1
```

R10 must verify Neptune configuration from `.env` or project settings.

Possible env/config keys:

```text
NEPTUNE_GRAPH_ENDPOINT
NEPTUNE_ENDPOINT
NEPTUNE_GRAPH_ID
AWS_REGION
```

R10 must report:

1. detected endpoint
2. detected graph ID
3. AWS region
4. Neptune client used
5. authentication method, expected SigV4
6. whether connectivity check succeeded

---

## Required Pre-checks

Before importing anything:

1. Verify full node file exists:

```text
neptune_nodes_r8.jsonl
```

2. Verify full edge file exists:

```text
neptune_edges_r8.jsonl
```

3. Verify full node merge params exist:

```text
neptune_node_merge_params_r8.jsonl
```

4. Verify full edge merge params exist:

```text
neptune_edge_merge_params_r8.jsonl
```

5. Verify expected counts:

```text
nodes: 381
edges: 703
```

6. Verify every full node has:

   * entity_id
   * run_id
   * dataset
   * label/entity_type
   * canonical_name or display_name

7. Verify every full edge has:

   * relation_id
   * source_entity_id
   * target_entity_id
   * relation_type
   * run_id
   * dataset

8. Verify every full edge source endpoint exists in full node set.

9. Verify every full edge target endpoint exists in full node set.

10. Verify all relation labels are allowed.

11. Verify no `custom` relation type.

12. Verify rollback script exists.

13. Verify no baseline deletion query will be executed.

If pre-check fails, stop before full import.

---

## R10 Import Strategy

### Step 1: Connectivity Check

Run a harmless read-only query:

```cypher
RETURN 1 AS ok
```

If unsupported, use a minimal query supported by the Neptune client.

Then check current rebuild count:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS rebuild_nodes
```

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS rebuild_edges
```

Record results.

### Step 2: Import All Nodes

Use R8 node MERGE params:

```text
neptune_node_merge_params_r8.jsonl
```

Use parameterized openCypher via Neptune Analytics API with SigV4.

Pattern:

```cypher
MERGE (n:Label {entity_id: $entity_id})
SET n += $properties
```

Requirements:

1. Import all 381 nodes.
2. Execute sequentially.
3. Use 1–2 second delay between calls unless current performance shows delay is unnecessary.
4. Retry transient failures.
5. Log every success/failure.
6. Stop if repeated auth/permission/syntax errors occur.

### Step 3: Validate Full Node Import

After node import:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS rebuild_nodes
```

Expected:

```text
381
```

Also sample read:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, n.canonical_name, labels(n)
LIMIT 20
```

### Step 4: Import All Edges

Use R8 edge MERGE params:

```text
neptune_edge_merge_params_r8.jsonl
```

Use pattern:

```cypher
MATCH (s {entity_id: $source_entity_id})
MATCH (t {entity_id: $target_entity_id})
MERGE (s)-[r:RELATION_TYPE {relation_id: $relation_id}]->(t)
SET r += $properties
```

Requirements:

1. Import all 703 edges.
2. Execute sequentially.
3. Use 1–2 second delay between calls unless current performance shows delay is unnecessary.
4. Retry transient failures.
5. If an edge endpoint is missing, record failure and continue only if failure count is low.
6. Stop if repeated systematic endpoint failures occur.

### Step 5: Validate Full Edge Import

After edge import:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS rebuild_edges
```

Expected:

```text
703
```

Also sample read:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, type(r), m.entity_id, r.relation_id
LIMIT 20
```

---

## Timeout and Retry Policy

Use conservative request settings:

```text
connect_timeout: 30s
read_timeout: 600s
max_attempts: 3
```

If a query times out:

1. retry once
2. reduce result size if read query
3. log error
4. continue if safe

For import calls:

1. import nodes sequentially
2. import edges sequentially
3. optional delay 1–2 seconds between calls
4. log every success/failure
5. stop if repeated auth/permission/endpoint/syntax errors occur

---

## Full Import Validation Queries

After full import, run validation queries.

### Count Validation

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS nodes
```

Expected:

```text
381
```

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS edges
```

Expected:

```text
703
```

### Baseline Count Check

Run read-only check for baseline if safe:

```cypher
MATCH (n {run_id: 'murata_live_v1'})
RETURN count(n) AS baseline_nodes
```

Expected:

```text
unchanged from R9 / prior baseline count
```

Do not modify baseline.

### Key Entity Queries

JOURNAL_BASE:

```cypher
MATCH (n {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, n.canonical_name, labels(n)
LIMIT 10
```

PAYMENT_REQ:

```cypher
MATCH (n {canonical_name: 'PAYMENT_REQ', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, n.canonical_name, labels(n)
LIMIT 10
```

SUN_REQUEST:

```cypher
MATCH (n {canonical_name: 'SUN_REQUEST', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, n.canonical_name, labels(n)
LIMIT 10
```

RECEIVING_JOURNAL:

```cypher
MATCH (n {canonical_name: 'RECEIVING_JOURNAL', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, n.canonical_name, labels(n)
LIMIT 10
```

### Neighbor Queries

JOURNAL_BASE neighbors:

```cypher
MATCH (n {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]-(m)
RETURN n.canonical_name, type(r), m.canonical_name, m.entity_type
LIMIT 30
```

PAYMENT_REQ neighbors:

```cypher
MATCH (n {canonical_name: 'PAYMENT_REQ', run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]-(m)
RETURN n.canonical_name, type(r), m.canonical_name, m.entity_type
LIMIT 30
```

### Q3 Three-Table Relation Validation

Check whether three required tables exist and have relations:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
WHERE n.canonical_name IN ['SUN_REQUEST', 'JOURNAL_BASE', 'RECEIVING_JOURNAL']
RETURN n.canonical_name, n.entity_id, labels(n)
```

Then query paths among them:

```cypher
MATCH p=(a {canonical_name: 'SUN_REQUEST', run_id: 'murata_rebuild_v1', dataset: 'murata'})-[*1..4]-(b {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN p
LIMIT 10
```

```cypher
MATCH p=(a {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1', dataset: 'murata'})-[*1..4]-(b {canonical_name: 'RECEIVING_JOURNAL', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN p
LIMIT 10
```

If variable-length paths fail due to syntax/client limitation, use fixed-depth or neighbor queries and record the limitation.

### Q4 Business Flow Path Validation

Try to validate at least one path involving AP business flow nodes.

Candidate names may include:

```text
応付管理
应付管理
付款申請創建
付款申请创建
PAYMENT_REQ
OA系統
OA系统
審批
审批
支付
報表
报表
```

Run flexible existence queries:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
WHERE n.canonical_name CONTAINS '応付'
   OR n.canonical_name CONTAINS '应付'
   OR n.canonical_name CONTAINS '付款'
   OR n.canonical_name CONTAINS 'PAYMENT'
   OR n.canonical_name CONTAINS '审批'
   OR n.canonical_name CONTAINS '審批'
RETURN n.entity_id, n.canonical_name, n.entity_type, labels(n)
LIMIT 30
```

Then run path query among selected nodes if possible.

If Q4 full path cannot be expressed in one query, validate by:

1. key business nodes exist
2. Q4 relation types exist
3. at least one path length >= 4 exists among rebuild nodes

### Q5 OA Migration Validation

Check OA-related nodes:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
WHERE n.canonical_name CONTAINS 'OA'
   OR n.display_name CONTAINS 'OA'
RETURN n.entity_id, n.canonical_name, n.entity_type, labels(n)
LIMIT 30
```

Check approval fields:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
WHERE n.canonical_name IN ['APPROVAL_BY', 'APPROVAL_TIME', 'APPROVAL_REMARK', 'STATUS', 'BILL_NO']
RETURN n.entity_id, n.canonical_name, n.entity_type, labels(n)
LIMIT 30
```

---

## Required R10 Artifacts

Create artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required files:

```text
neptune_full_connectivity_check_r10.json
neptune_pre_full_import_count_r10.json
neptune_full_node_import_result_r10.jsonl
neptune_full_edge_import_result_r10.jsonl
neptune_full_import_failures_r10.jsonl
neptune_full_readback_counts_r10.json
neptune_full_key_entity_queries_r10.json
neptune_full_neighbor_queries_r10.json
neptune_full_q3_path_validation_r10.json
neptune_full_q4_path_validation_r10.json
neptune_full_q5_oa_validation_r10.json
neptune_full_import_summary_r10.json
neptune_full_rollback_plan_r10.cypher
```

If an optional query fails due to syntax or client limitation, create a JSON record with:

```json
{
  "status": "failed",
  "reason": "...",
  "query": "...",
  "fallback_used": true,
  "fallback_result": {}
}
```

---

## Required R10 Reports

Create reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r10_full_import_report.md
docs/murata_rebuild_r10_connectivity_report.md
docs/murata_rebuild_r10_full_readback_validation_report.md
docs/murata_rebuild_r10_graph_query_validation_report.md
docs/murata_rebuild_r10_import_failures_report.md
docs/murata_rebuild_r10_rollback_plan.md
docs/murata_rebuild_r10_next_step_recommendation.md
```

---

## R10 Quality Gate

R10 passes only if:

1. Neptune endpoint and graph ID are detected.
2. Connectivity check succeeds.
3. Existing rebuild data count is reported before full import.
4. Full node file is loaded.
5. Full edge file is loaded.
6. Full node pre-check passes.
7. Full edge pre-check passes.
8. Full node import executes.
9. Full edge import executes.
10. Node import success count is reported.
11. Edge import success count is reported.
12. Full read-back node count equals expected 381 or is explicitly explained.
13. Full read-back edge count equals expected 703 or is explicitly explained.
14. Sample node properties are readable after full import.
15. Sample edge properties are readable after full import.
16. JOURNAL_BASE query is attempted and result/failure is reported.
17. PAYMENT_REQ query is attempted and result/failure is reported.
18. SUN_REQUEST and RECEIVING_JOURNAL query is attempted and result/failure is reported.
19. Q3 path/neighbor validation is attempted and result/failure is reported.
20. Q4 path validation is attempted and result/failure is reported.
21. Q5 OA validation is attempted and result/failure is reported.
22. Import failures are logged.
23. Rollback plan is generated and scoped to `run_id=murata_rebuild_v1`.
24. Baseline data is not modified.
25. No full graph deletion occurs.
26. No Bedrock, embedding, LanceDB, VLM, QA terminal, or final answer operation occurs.

If R10 fails:

1. do not proceed to R11
2. do not run QA
3. report failure reason
4. recommend one of:

   * retry failed node/edge imports
   * reduce delay or increase delay
   * fix Neptune endpoint / VPC / security group
   * fix IAM permissions
   * fix SigV4 client
   * fix openCypher syntax
   * fix property serialization
   * rollback only if explicitly confirmed
   * return to R8/R9 artifact generation

---

## Success Criteria

R10 is successful if:

```text
1. full import succeeds
2. 381 rebuild nodes are present
3. 703 rebuild edges are present
4. key entities are queryable
5. graph traversal works
6. Q3/Q4/Q5 validation queries produce useful results
7. rollback is available but not executed
8. baseline is untouched
```

R10 does not need to prove final QA quality.
R10 proves full Neptune graph import and graph query readiness.

---

## Post-R10 Recommendation Logic

If R10 full import passes:

Recommend R11:

```text
R11 — Hybrid Retrieval + QA Terminal Validation
```

R11 should combine:

```text
LanceDB vector retrieval from R5
Neptune graph retrieval from R10
fusion/context builder
answer generation
debug terminal display
```

If R10 full import passes but graph query validation is weak:

Recommend:

```text
R10.5 — Graph Query Tuning / Cypher Template Fixes
```

If R10 full import fails:

Recommend fix based on error category:

```text
network / auth / endpoint / cypher / property / endpoint missing / timeout
```

---

## Forbidden Actions

R10 must not:

1. clear Neptune graph
2. delete baseline data
3. execute rollback unless explicitly confirmed
4. call Bedrock
5. generate embeddings
6. write LanceDB
7. run VLM
8. run graph extraction
9. run QA terminal
10. generate final answers
11. proceed to R11 automatically

---

## Allowed Actions

R10 may:

1. read R8 full import artifacts
2. connect to Neptune
3. run read-only pre-check queries
4. import full nodes
5. import full edges
6. run read-back validation queries
7. run graph structure validation queries
8. generate reports
9. update `docs/task_state.md`

---

## State Update

After completing R10, update `docs/task_state.md`:

```markdown
## Current Phase

`R10`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_connectivity_check_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_pre_full_import_count_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_node_import_result_r10.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_edge_import_result_r10.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_import_failures_r10.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_readback_counts_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_key_entity_queries_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_neighbor_queries_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q3_path_validation_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q4_path_validation_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q5_oa_validation_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_import_summary_r10.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_rollback_plan_r10.cypher`
- `docs/murata_rebuild_r10_full_import_report.md`
- `docs/murata_rebuild_r10_connectivity_report.md`
- `docs/murata_rebuild_r10_full_readback_validation_report.md`
- `docs/murata_rebuild_r10_graph_query_validation_report.md`
- `docs/murata_rebuild_r10_import_failures_report.md`
- `docs/murata_rebuild_r10_rollback_plan.md`
- `docs/murata_rebuild_r10_next_step_recommendation.md`

## Latest Findings

Summarize full import, read-back validation, graph query validation, and any Neptune issues.

## Risks / Issues

Summarize failures, partial imports, rollback needs, graph query limitations, and R11 readiness.

## Recommended Next Phase

`R11`

## Next Phase Prompt

`docs/prompts/phase_r11_hybrid_retrieval_qa_validation.md`
```

Then stop and wait for user review.

Do not proceed to R11 automatically.
