# Phase R8 — Neptune Dry-Run / Import Preview

## Objective

Generate and validate Neptune import artifacts from the R7 canonical graph.

R8 is a **Neptune dry-run and import-preview phase**.

R8 must not perform full live import by default.  
R8 must not delete existing Neptune data by default.  
R8 must not run QA terminal.  
R8 must not generate final answers.  
R8 must not proceed to R9 automatically.

The purpose of R8 is to answer one key question:

> Can the R7 canonical graph be safely converted into Neptune-ready openCypher import scripts / payloads and optionally validated with a small sample live import?

R8 should prepare the graph for Neptune loading while protecting existing data.

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
graph target: Neptune Analytics / Neptune Graph
future QA target: Hybrid GraphRAG with LanceDB + Neptune
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
```

R7 result:

```text
canonical entities: 381
canonical relations: 703
canonical evidence: 181
rejected relations: 0
pending relations: 4
pending entity merges: 0
custom relation types: 0
related_to percentage: 3.1%
Q1-Q5 coverage: full
Neptune preview CSV files generated
Q4 final preview generated
```

R8 should use the R7 canonical outputs as the source of truth.

---

## Control Files to Read

Before executing R8, read:

1. `.hermes.md`
2. `docs/task_state.md`
3. `docs/prompts/phase_r8_neptune_dryrun_preview.md`

Also read R7 prompt and reports if needed:

```text
docs/prompts/phase_r7_normalization_integrity.md
docs/murata_rebuild_r7_normalization_report.md
docs/murata_rebuild_r7_integrity_report.md
docs/murata_rebuild_r7_neptune_preview_report.md
docs/murata_rebuild_r7_next_step_recommendation.md
```

Read R7 artifacts:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/entities_r7.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/relations_r7.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/evidence_r7.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_nodes_preview_r7.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edges_preview_r7.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_nodes_final_preview_r7.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_edges_final_preview_r7.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/integrity_check_r7.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/target_question_graph_coverage_r7.json
```

If any critical R7 canonical graph file is missing, stop and report.

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

R8 must verify Neptune configuration from `.env` or project settings.

Possible env/config keys:

```text
NEPTUNE_GRAPH_ENDPOINT
NEPTUNE_ENDPOINT
NEPTUNE_GRAPH_ID
AWS_REGION
```

R8 must report:

1. Neptune endpoint detected.
2. Neptune graph ID detected.
3. AWS region.
4. Neptune client class or script to be used.
5. Whether this phase is dry-run only or sample live import is explicitly enabled.

If Neptune config is missing, R8 can still complete dry-run artifact generation, but must skip live sample import and report missing config.

---

## R8 Execution Modes

R8 has three possible modes.

### Mode 1: Dry-Run Only — Default

This is the default mode.

Allowed:

* Generate openCypher scripts.
* Generate parameterized import payloads.
* Validate node/edge CSV schemas.
* Validate Cypher syntax structurally.
* Validate no missing IDs.
* Validate no missing edge endpoints.
* Validate property serialization.
* Create dry-run reports.

Forbidden:

* Do not query Neptune.
* Do not write Neptune.
* Do not delete Neptune data.

### Mode 2: Connectivity Check — Optional

Only perform if explicitly allowed by user or `docs/task_state.md`.

Allowed:

* Check Neptune connection.
* Run a harmless read-only query, such as a small metadata query.
* Do not write.

Forbidden:

* Do not create nodes.
* Do not create edges.
* Do not delete.

### Mode 3: Sample Live Import — Optional and Requires Explicit Confirmation

Only perform if all are true:

1. `docs/task_state.md` or user prompt explicitly says sample live import is allowed.
2. `--confirm-sample-live-import` or equivalent confirmation is present.
3. Sample size is limited.
4. The import is tagged with:

   * `run_id=murata_rebuild_v1`
   * `dataset=murata`
5. Rollback query is generated before import.

Default sample size:

```text
20 nodes
30 edges
```

Forbidden unless explicitly confirmed:

* Full import.
* Full delete.
* Deleting any baseline or non-current run.
* Writing untagged data.

---

## Strict Safety Rules

R8 must never modify baseline data.

Never delete or overwrite:

```text
run_id = murata_live_v1
LanceDB collection = murata_e2e_murata_live_v1
```

R8 must not perform a full Neptune clear.

Any cleanup query must be scoped to:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
DETACH DELETE n
```

But R8 must not execute this cleanup unless explicitly confirmed.

R8 must generate rollback scripts but not execute them by default.

---

## R8 Scope

R8 includes:

1. Load R7 canonical graph artifacts.
2. Validate canonical entities and relations.
3. Validate Neptune node preview CSV.
4. Validate Neptune edge preview CSV.
5. Validate Q4 final preview CSV.
6. Generate openCypher MERGE scripts.
7. Generate parameterized import payloads.
8. Generate rollback scripts scoped to `run_id=murata_rebuild_v1`.
9. Generate sample import scripts.
10. Optionally perform read-only connectivity check if allowed.
11. Optionally perform sample live import if explicitly confirmed.
12. Produce import preview and validation reports.
13. Update `docs/task_state.md`.

R8 excludes:

1. Full live import by default.
2. Full graph deletion.
3. QA terminal.
4. Hybrid retrieval.
5. Answer generation.
6. Bedrock calls.
7. Embedding generation.
8. LanceDB writes.
9. Graph extraction.
10. Proceeding to R9 automatically.

---

## Input Validation

Validate `entities_r7.jsonl`.

Each entity must have:

```text
entity_id
run_id
dataset
canonical_name
display_name or canonical_name
entity_type
layer
source_chunk_ids
source_uris
```

Validate `relations_r7.jsonl`.

Each relation must have:

```text
relation_id
run_id
dataset
source_entity_id
target_entity_id
relation_type
source_chunk_ids
evidence_ids
confidence_avg or confidence_max
```

Validate relation endpoints:

```text
source_entity_id exists in entities_r7.jsonl
target_entity_id exists in entities_r7.jsonl
```

Validate `evidence_r7.jsonl`.

Each evidence record should have:

```text
evidence_id
source_chunk_id
source_uri
evidence_text
related_target_questions
```

---

## Neptune Label Mapping

Map canonical entity types to Neptune labels.

Recommended mapping:

```text
BusinessProcess  -> BusinessProcess
BusinessStep     -> BusinessStep
BusinessObject   -> BusinessObject
BusinessRule     -> BusinessRule
System           -> System
Module           -> Module
Screen           -> Screen
API              -> API
Action           -> Action
Service          -> Service
ServiceImpl      -> ServiceImpl
DAO              -> DAO
Mapper           -> Mapper
Class            -> Class
Method           -> Method
Table            -> Table
View             -> View
Column           -> Column
Field            -> Field
Status           -> Status
EnumValue        -> EnumValue
Document         -> Document
File             -> File
ExternalSystem   -> ExternalSystem
Interface        -> Interface
Report           -> Report
Evidence         -> Evidence
```

If label contains invalid characters, normalize it.

Do not create arbitrary labels.

---

## Neptune Relation Label Mapping

Use normalized relation labels from R7.

Allowed relation labels:

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

R8 must validate:

```text
custom relation count = 0
unsupported relation labels = 0
```

For Q4 final CSV, use only:

```text
generates
depends_on
relates_to
```

---

## Node Property Strategy

For each Neptune node, include:

```text
entity_id
canonical_name
display_name
entity_type
layer
run_id
dataset
aliases_json
source_chunk_ids_json
source_uris_json
related_target_questions_json
confidence_avg
confidence_max
support_count
created_by_phase = R8
```

Avoid very large property values.

For arrays, serialize to JSON strings unless Neptune loader supports arrays safely.

---

## Edge Property Strategy

For each Neptune edge, include:

```text
relation_id
relation_type
run_id
dataset
source_chunk_ids_json
evidence_ids_json
evidence_texts_json
related_target_questions_json
confidence_avg
confidence_max
support_count
created_by_phase = R8
```

Avoid very large `evidence_texts_json` if too long.

If evidence text is large, truncate preview property and preserve full evidence in `evidence_r7.jsonl`.

Recommended:

```text
evidence_preview
evidence_ids_json
```

---

## OpenCypher Generation

Generate a node MERGE script.

For each entity:

```cypher
MERGE (n:Label {entity_id: $entity_id})
SET n += $properties
```

Generate an edge MERGE script.

For each relation:

```cypher
MATCH (s {entity_id: $source_entity_id})
MATCH (t {entity_id: $target_entity_id})
MERGE (s)-[r:RELATION_TYPE {relation_id: $relation_id}]->(t)
SET r += $properties
```

Important:

* Use parameterized queries where possible.
* Do not inline unsafe strings directly into Cypher.
* Validate escaping for CSV/script preview.
* Use stable `entity_id` and `relation_id`.
* Keep `run_id` and `dataset` on both nodes and edges.

---

## Required R8 Artifacts

Create artifacts under:

```text
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
```

Required files:

```text
neptune_nodes_r8.jsonl
neptune_edges_r8.jsonl
neptune_node_merge_params_r8.jsonl
neptune_edge_merge_params_r8.jsonl
neptune_node_merge_preview_r8.cypher
neptune_edge_merge_preview_r8.cypher
neptune_rollback_r8.cypher
neptune_sample_nodes_r8.jsonl
neptune_sample_edges_r8.jsonl
neptune_sample_import_preview_r8.cypher
neptune_import_validation_r8.json
neptune_import_manifest_r8.json
q4_nodes_neptune_csv_r8.csv
q4_edges_neptune_csv_r8.csv
```

If optional connectivity or sample import is executed, also create:

```text
neptune_connectivity_check_r8.json
neptune_sample_import_result_r8.json
```

If not executed, create a note in the validation report.

---

## Required R8 Reports

Create reports under:

```text
~/projects/hermes_bedrock_agent/docs/
```

Required reports:

```text
docs/murata_rebuild_r8_neptune_dryrun_report.md
docs/murata_rebuild_r8_import_validation_report.md
docs/murata_rebuild_r8_openCypher_preview_report.md
docs/murata_rebuild_r8_q4_csv_report.md
docs/murata_rebuild_r8_rollback_plan.md
docs/murata_rebuild_r8_next_step_recommendation.md
```

---

## Q4 CSV Requirement

R8 must generate final Q4 Neptune CSV output from R7 Q4 preview.

Output:

```text
q4_nodes_neptune_csv_r8.csv
q4_edges_neptune_csv_r8.csv
```

Q4 nodes columns:

```csv
id,label,type
```

Q4 edges columns:

```csv
from,to,relation
```

Q4 edge relation must only be one of:

```text
generates
depends_on
relates_to
```

Validate:

1. No missing node IDs.
2. No missing edge endpoints.
3. Every edge endpoint exists in nodes.
4. At least one continuous path A → B → C → D exists.
5. Relation values are restricted to the three allowed values.

---

## Rollback Plan

R8 must generate rollback scripts but not execute them by default.

Rollback script:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
DETACH DELETE n
```

Also generate a safer preview-count query:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS nodes
```

If edge-specific rollback is needed, document it.

Rollback report must clearly state:

```text
Do not execute rollback unless user explicitly confirms.
Rollback is scoped only to run_id=murata_rebuild_v1 and dataset=murata.
```

---

## Optional Sample Live Import Policy

By default, R8 does not do live import.

If the user explicitly allows sample live import, then:

1. Import only sample nodes/edges.
2. Default sample:

   * 20 nodes
   * 30 edges
3. Use only `run_id=murata_rebuild_v1`.
4. Generate rollback before import.
5. After import, run read-only validation queries.
6. Do not full import.
7. Stop after sample import.

Sample validation queries:

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS nodes
```

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS edges
```

```cypher
MATCH (n {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1'})
RETURN n LIMIT 5
```

```cypher
MATCH p=(n {canonical_name: 'JOURNAL_BASE', run_id: 'murata_rebuild_v1'})-[r*1..2]-(m)
RETURN p LIMIT 10
```

---

## R8 Quality Gate

R8 passes if:

1. R7 canonical entities are loaded.
2. R7 canonical relations are loaded.
3. Entity count matches or is explained.
4. Relation count matches or is explained.
5. No missing node IDs.
6. No duplicate node IDs.
7. No missing relation IDs.
8. No duplicate relation IDs.
9. No edge endpoint missing.
10. No unsupported node labels.
11. No unsupported relation labels.
12. `custom` relation count is 0.
13. `run_id=murata_rebuild_v1` exists on all node and edge payloads.
14. `dataset=murata` exists on all node and edge payloads.
15. Node MERGE params are generated.
16. Edge MERGE params are generated.
17. OpenCypher preview scripts are generated.
18. Rollback script is generated and scoped correctly.
19. Q4 CSV output is generated.
20. Q4 edge relation values are only `generates`, `depends_on`, `relates_to`.
21. Q4 edge endpoints all exist in Q4 nodes.
22. At least one Q4 continuous path A → B → C → D exists.
23. No full Neptune live import occurs unless explicitly confirmed.
24. No baseline data is modified.
25. No Bedrock, embedding, LanceDB, graph extraction, QA terminal, or final answer operation occurs.

If R8 fails:

1. Do not proceed to R9.
2. Report failure reasons.
3. Recommend one of:

   * fix CSV escaping
   * fix property serialization
   * fix label mapping
   * fix missing edge endpoints
   * return to R7 normalization
   * reduce import payload size
   * perform sample import only after fix

---

## Reporting Requirements

At completion, output a Phase R8 report with:

1. execution mode:

   * dry-run only
   * connectivity check
   * sample live import
2. Neptune endpoint / graph ID detected
3. node count
4. edge count
5. unsupported labels count
6. unsupported relation count
7. missing endpoint count
8. duplicate ID count
9. generated Cypher preview files
10. generated parameter payload files
11. Q4 CSV validation result
12. rollback script path
13. whether optional connectivity/sample import was executed
14. whether R8 quality gate passed
15. whether R9 hybrid retrieval / graph validation is recommended
16. generated files
17. warnings and risks

---

## Forbidden Actions

R8 must not:

1. perform full live Neptune import by default
2. clear Neptune graph
3. delete any baseline data
4. query Neptune unless connectivity check is explicitly allowed
5. write Neptune unless sample live import is explicitly confirmed
6. call Bedrock
7. generate embeddings
8. write LanceDB
9. run VLM
10. run graph extraction
11. run QA terminal
12. generate final answers
13. proceed to R9 automatically

---

## Allowed Actions

R8 may:

1. read R7 canonical graph artifacts
2. generate Neptune-ready JSONL payloads
3. generate openCypher preview scripts
4. generate rollback scripts
5. validate CSV and property serialization
6. generate Q4 final CSV files
7. optionally perform read-only Neptune connectivity check if explicitly allowed
8. optionally perform sample live import only if explicitly confirmed
9. create reports
10. update `docs/task_state.md`

---

## State Update

After completing R8, update `docs/task_state.md`:

```markdown
## Current Phase

`R8`

## Current Phase Status

completed or failed

## Completed Outputs

- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_nodes_r8.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edges_r8.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_node_merge_params_r8.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edge_merge_params_r8.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_node_merge_preview_r8.cypher`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_edge_merge_preview_r8.cypher`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_rollback_r8.cypher`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_nodes_r8.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_edges_r8.jsonl`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_import_preview_r8.cypher`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_import_validation_r8.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_import_manifest_r8.json`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_nodes_neptune_csv_r8.csv`
- `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_edges_neptune_csv_r8.csv`
- `docs/murata_rebuild_r8_neptune_dryrun_report.md`
- `docs/murata_rebuild_r8_import_validation_report.md`
- `docs/murata_rebuild_r8_openCypher_preview_report.md`
- `docs/murata_rebuild_r8_q4_csv_report.md`
- `docs/murata_rebuild_r8_rollback_plan.md`
- `docs/murata_rebuild_r8_next_step_recommendation.md`

## Latest Findings

Summarize Neptune import readiness, validation results, and Q4 CSV status.

## Risks / Issues

Summarize any import risks, schema issues, endpoint issues, and whether live import is safe.

## Recommended Next Phase

`R9`

## Next Phase Prompt

`docs/prompts/phase_r9_neptune_sample_import_or_hybrid_validation.md`
```

Then stop and wait for user review.

Do not proceed to R9 automatically.
