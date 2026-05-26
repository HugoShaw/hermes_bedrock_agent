# Phase R9 — Neptune Sample Live Import & Validation

## Objective

Execute a controlled Neptune sample live import using the R8 sample import artifacts, then validate that the imported graph data can be queried correctly.

R9 is a **sample live import and read-back validation phase**.

R9 must not perform full live import by default.  
R9 must not clear Neptune graph by default.  
R9 must not delete baseline data.  
R9 must not run hybrid QA.  
R9 must not run answer generation.  
R9 must not proceed to R10 automatically.

The purpose of R9 is to answer one key question:

> Can the R8 Neptune import artifacts be safely written to Neptune and queried back, without affecting baseline data?

R9 should import only the sample set first:

```text
20 nodes + 30 edges
````

Full import must be deferred until the sample import and read-back validation pass and the user explicitly confirms.

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
```

R8 result:

```text
R8 dry-run passed 25/25 quality gates.
R8 generated Neptune-ready artifacts.
R8 did not query or write Neptune.
R8 recommended sample live import first.
```

---

## Control Files to Read

Before executing R9, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r9_neptune_sample_import_validation.md`

Also read R8 prompt and reports if needed:

```text
docs/prompts/phase_r8_neptune_dryrun_preview.md
docs/murata_rebuild_r8_neptune_dryrun_report.md
docs/murata_rebuild_r8_import_validation_report.md
docs/murata_rebuild_r8_openCypher_preview_report.md
docs/murata_rebuild_r8_q4_csv_report.md
docs/murata_rebuild_r8_rollback_plan.md
docs/murata_rebuild_r8_next_step_recommendation.md
```

Read R8 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_nodes_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edges_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_node_merge_params_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edge_merge_params_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_nodes_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_edges_r8.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_import_preview_r8.cypher
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_rollback_r8.cypher
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_import_manifest_r8.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_import_validation_r8.json
```

If any critical R8 sample import file is missing, stop and report.

---

## R9 Execution Mode

Default R9 mode:

```text
SAMPLE_LIVE_IMPORT_ONLY
```

Allowed by this phase:

```text
1. Neptune connectivity check
2. Count existing murata_rebuild_v1 data
3. Import sample nodes
4. Import sample edges
5. Read-back validation
6. Sample query validation
7. Generate import result reports
```

Not allowed by default:

```text
1. Full import
2. Full graph delete
3. Deleting old murata_rebuild_v1 data
4. Deleting baseline murata_live_v1 data
5. Hybrid QA
6. QA terminal
7. Answer generation
8. Proceeding to R10 automatically
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

All sample nodes and edges must include:

```text
run_id = murata_rebuild_v1
dataset = murata
```

### Do Not Clean Existing Rebuild Data Unless Confirmed

Before sample import, check existing rebuild data count:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS nodes
```

and:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS edges
```

If existing data count > 0:

1. Do not delete it automatically.
2. Report the count.
3. Either:

   * continue with idempotent MERGE sample import, or
   * stop and ask for cleanup confirmation if data conflict is likely.

Default behavior:

```text
Do not rollback automatically.
Do not delete automatically.
MERGE is idempotent, so sample import can proceed if no conflict is detected.
```

### Rollback Script

Rollback script exists from R8:

```text
neptune_rollback_r8.cypher
```

R9 may generate additional rollback notes, but must not execute rollback unless explicitly confirmed.

---

## Neptune Target

Expected Neptune Graph endpoint:

```text
g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com
```

Expected graph ID:

```text
g-nbuyck5yl8
```

Expected region:

```text
ap-northeast-1
```

R9 must verify Neptune configuration from `.env` or project settings.

Possible env/config keys:

```text
NEPTUNE_GRAPH_ENDPOINT
NEPTUNE_ENDPOINT
NEPTUNE_GRAPH_ID
AWS_REGION
```

R9 must report:

1. detected endpoint
2. detected graph ID
3. AWS region
4. Neptune client used
5. authentication method, expected SigV4
6. whether connectivity check succeeded

---

## Required Pre-checks

Before importing anything:

1. Verify R8 sample node file exists.
2. Verify R8 sample edge file exists.
3. Verify sample node count is expected, around 20.
4. Verify sample edge count is expected, around 30.
5. Verify every sample node has:

   * entity_id
   * run_id
   * dataset
   * label/entity_type
   * canonical_name or display_name
6. Verify every sample edge has:

   * relation_id
   * source_entity_id
   * target_entity_id
   * relation_type
   * run_id
   * dataset
7. Verify every sample edge source endpoint exists either:

   * in sample nodes, or
   * already in Neptune under same run_id/dataset
8. Verify every sample edge target endpoint exists either:

   * in sample nodes, or
   * already in Neptune under same run_id/dataset
9. Verify all relation labels are allowed.
10. Verify no `custom` relation type.
11. Verify rollback script exists.
12. Verify no baseline deletion query will be executed.

If pre-check fails, stop before import.

---

## R9 Import Strategy

### Step 1: Connectivity Check

Run a harmless read-only query.

Example:

```cypher
MATCH (n)
RETURN count(n) AS total_nodes
LIMIT 1
```

If this query is too expensive or unsupported, run a minimal metadata / count query supported by the existing Neptune client.

Also check rebuild count:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS rebuild_nodes
```

and:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS rebuild_edges
```

Record results.

### Step 2: Import Sample Nodes

Use the R8 parameterized MERGE pattern:

```cypher
MERGE (n:Label {entity_id: $entity_id})
SET n += $properties
```

Use sample nodes from:

```text
neptune_sample_nodes_r8.jsonl
```

Use parameterized openCypher via Neptune Analytics API with SigV4.

Do not inline unsafe strings.

### Step 3: Validate Sample Nodes

After node import:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS rebuild_nodes
```

Also sample read:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, n.canonical_name, labels(n)
LIMIT 10
```

### Step 4: Import Sample Edges

Use the R8 parameterized MERGE pattern:

```cypher
MATCH (s {entity_id: $source_entity_id})
MATCH (t {entity_id: $target_entity_id})
MERGE (s)-[r:RELATION_TYPE {relation_id: $relation_id}]->(t)
SET r += $properties
```

Use sample edges from:

```text
neptune_sample_edges_r8.jsonl
```

If an edge endpoint is missing, do not create that edge.
Record it in failed edge import report.

### Step 5: Validate Sample Edges

Run:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS rebuild_edges
```

Also sample read:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n.entity_id, type(r), m.entity_id, r.relation_id
LIMIT 10
```

### Step 6: Validate Key Entities

Run sample queries for important entities if present in sample.

JOURNAL_BASE:

```cypher
MATCH (n {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n
LIMIT 5
```

PAYMENT_REQ:

```cypher
MATCH (n {canonical_name: 'PAYMENT_REQ', run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN n
LIMIT 5
```

If these entities are not in the sample import, report:

```text
Not present in sample, will be validated in full import or targeted sample import.
```

### Step 7: Validate Path Query

Try a short path query:

```cypher
MATCH p=(n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r*1..2]-(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN p
LIMIT 5
```

If path query fails due to Neptune Analytics syntax or client limitation, record the exact error and use simpler edge queries instead.

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
2. reduce result size
3. log error
4. continue if safe

For import calls:

1. import nodes sequentially
2. import edges sequentially
3. optional delay 1–3 seconds between calls
4. log every success/failure
5. stop if repeated auth/permission/endpoint errors occur

---

## Required R9 Artifacts

Create artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required files:

```text
neptune_connectivity_check_r9.json
neptune_existing_rebuild_count_r9.json
neptune_sample_node_import_result_r9.jsonl
neptune_sample_edge_import_result_r9.jsonl
neptune_sample_import_failures_r9.jsonl
neptune_sample_readback_nodes_r9.json
neptune_sample_readback_edges_r9.json
neptune_sample_key_entity_queries_r9.json
neptune_sample_path_queries_r9.json
neptune_sample_import_summary_r9.json
neptune_sample_rollback_plan_r9.cypher
```

If an optional output cannot be created because query failed, create a JSON record with the failure reason.

---

## Required R9 Reports

Create reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r9_neptune_sample_import_report.md
docs/murata_rebuild_r9_neptune_connectivity_report.md
docs/murata_rebuild_r9_sample_readback_validation_report.md
docs/murata_rebuild_r9_import_failures_report.md
docs/murata_rebuild_r9_rollback_plan.md
docs/murata_rebuild_r9_next_step_recommendation.md
```

---

## R9 Quality Gate

R9 passes only if:

1. Neptune endpoint and graph ID are detected.
2. Connectivity check succeeds.
3. Existing rebuild data count is reported.
4. Sample nodes file is loaded.
5. Sample edges file is loaded.
6. Sample node pre-check passes.
7. Sample edge pre-check passes or missing endpoints are clearly explained.
8. Sample node import executes.
9. Sample edge import executes.
10. Node import success count is reported.
11. Edge import success count is reported.
12. Read-back node count confirms imported nodes exist.
13. Read-back edge count confirms imported edges exist.
14. Sample node properties are readable.
15. Sample edge properties are readable.
16. Key entity query is attempted and result/failure is reported.
17. Path query is attempted and result/failure is reported.
18. Import failures are logged.
19. Rollback plan is generated and scoped to `run_id=murata_rebuild_v1`.
20. Baseline data is not modified.
21. No full import occurs.
22. No full graph deletion occurs.
23. No Bedrock, embedding, LanceDB, VLM, QA, or final answer operation occurs.

If R9 fails:

1. do not proceed to R10
2. do not full import
3. report failure reason
4. recommend one of:

   * fix Neptune endpoint / VPC / security group
   * fix IAM permissions
   * fix SigV4 client
   * fix openCypher syntax
   * fix property serialization
   * import fewer edges
   * retry sample import after cleanup
   * return to R8 artifact generation

---

## Success Criteria

R9 is successful if:

```text
1. sample import succeeds
2. sample nodes can be read back
3. sample edges can be read back
4. properties are preserved
5. rollback is available but not executed
6. baseline is untouched
```

R9 does not need to prove full QA quality.
R9 only proves Neptune import mechanics.

---

## Post-R9 Recommendation Logic

If R9 sample import passes:

Recommend R10:

```text
R10 — Full Neptune Import or Controlled Full Import + Graph Query Validation
```

If sample import passes but user wants caution:

Recommend:

```text
R9.5 — Targeted sample import for JOURNAL_BASE / PAYMENT_REQ / Q4 path
```

If R9 sample import fails:

Recommend fix based on error category:

```text
network / auth / endpoint / cypher / property / endpoint missing
```

---

## Forbidden Actions

R9 must not:

1. perform full live Neptune import
2. clear Neptune graph
3. delete baseline data
4. execute rollback unless explicitly confirmed
5. call Bedrock
6. generate embeddings
7. write LanceDB
8. run VLM
9. run graph extraction
10. run QA terminal
11. generate final answers
12. proceed to R10 automatically

---

## Allowed Actions

R9 may:

1. read R8 artifacts
2. connect to Neptune
3. run read-only pre-check queries
4. import sample nodes
5. import sample edges
6. run read-back validation queries
7. generate reports
8. update `docs/task_state.md`

---

## State Update

After completing R9, update `docs/task_state.md`:

```markdown
## Current Phase

`R9`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_connectivity_check_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_existing_rebuild_count_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_node_import_result_r9.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_edge_import_result_r9.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_import_failures_r9.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_readback_nodes_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_readback_edges_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_key_entity_queries_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_path_queries_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_import_summary_r9.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_rollback_plan_r9.cypher`
- `docs/murata_rebuild_r9_neptune_sample_import_report.md`
- `docs/murata_rebuild_r9_neptune_connectivity_report.md`
- `docs/murata_rebuild_r9_sample_readback_validation_report.md`
- `docs/murata_rebuild_r9_import_failures_report.md`
- `docs/murata_rebuild_r9_rollback_plan.md`
- `docs/murata_rebuild_r9_next_step_recommendation.md`

## Latest Findings

Summarize sample import, read-back validation, and any Neptune issues.

## Risks / Issues

Summarize failures, partial imports, rollback needs, and full import risks.

## Recommended Next Phase

`R10`

## Next Phase Prompt

`docs/prompts/phase_r10_neptune_full_import_or_hybrid_validation.md`
```

Then stop and wait for user review.

Do not proceed to R10 automatically.
