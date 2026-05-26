# Master Task: Refactor Current Dual-Path GraphRAG into Business Semantic Graph + Implementation Graph + Vector Evidence Store

## 1. Mission

Refactor the current enterprise GraphRAG project from a chunk-driven dual-path RAG system into a layered enterprise knowledge architecture:

```text
Business Semantic Graph + Implementation Graph + Vector Evidence Store
````

The current system has problems because:

1. Vector DB and Graph DB are both overly dependent on the same small chunks.
2. Graph extraction from many small chunks produces fragmented, noisy, weakly connected entities and relations.
3. Chunk-level extraction causes weak business readability.
4. Business Semantic Map and evidence graph are not clearly separated.
5. Query answering receives mixed and noisy graph/vector context.
6. The graph is difficult to use for enterprise reasoning, impact analysis, and future EAI workflow generation.

The refactor should produce a more stable architecture where:

```text
Vector DB = evidence retrieval
Business Semantic Graph = business structure retrieval
Implementation Graph = system/API/code/DB structure retrieval
Evidence Linker = connects graph items back to source evidence
Query Router = chooses the right retrieval path
Hybrid Context Builder = creates clean structured context for answer generation
```

---

## 2. Default Dataset and Run ID

Use the following default values:

```text
dataset = murata
run_id = murata_semantic_v2
```

Main output directory:

```text
data/outputs/murata_semantic_v2/
```

Project-level documents:

```text
docs/
```

Prompt files:

```text
docs/prompts/
```

Task state file:

```text
docs/task_state.md
```

Project instruction file:

```text
.hermes.md
```

---

## 3. Target Architecture

The refactored architecture should follow this structure:

```text
Raw Enterprise Documents / Source Code / SQL / API Docs
    ↓
Document Parser / Normalizer
    ↓
Document Object Model
    ↓
├── Vector Evidence Store Builder
│      ├── document summary chunks
│      ├── section chunks
│      ├── small evidence chunks
│      ├── table chunks
│      ├── code chunks
│      ├── SQL chunks
│      └── API chunks
│
└── Graph Builder
       ├── Business Semantic Graph Builder
       │      ├── BusinessDomain
       │      ├── BusinessProcess
       │      ├── BusinessStep
       │      ├── BusinessRule
       │      ├── BusinessTerm
       │      ├── Function
       │      ├── Screen
       │      ├── Role
       │      └── Organization
       │
       ├── Implementation Graph Builder
       │      ├── System
       │      ├── Module
       │      ├── API
       │      ├── Service
       │      ├── Class
       │      ├── Method
       │      ├── Table
       │      ├── Column
       │      ├── SQL
       │      ├── Job
       │      ├── File
       │      ├── Config
       │      └── ExternalSystem
       │
       └── Evidence Linker
              ├── Graph Node -> evidence_chunk_ids
              ├── Graph Edge -> evidence_chunk_ids
              └── evidence_id / source_id / section_id / chunk_id
```

---

## 4. Overall Execution Rule

Execute the refactor stage by stage.

Do not try to complete all stages in one run unless explicitly instructed.

For each stage:

1. Read `.hermes.md`.
2. Read this `docs/prompts/00_master_task.md`.
3. Read `docs/task_state.md`.
4. Read the stage prompt.
5. Execute only that stage.
6. Generate required outputs.
7. Update `docs/task_state.md`.
8. Stop and report the result.

Do not jump ahead to future stages unless the user explicitly asks.

---

## 5. Stage List

### Stage 01: Project Scan

Prompt file:

```text
docs/prompts/01_scan_project.md
```

Goal:

```text
Understand the current project structure, current pipeline, existing modules, Murata data path, and reusable components.
```

Expected output:

```text
docs/refactor_scan_report.md
```

Do not modify code in this stage.

---

### Stage 02: V2 Refactor Plan

Prompt file:

```text
docs/prompts/02_refactor_plan.md
```

Goal:

```text
Design the V2 architecture based on the actual current project structure.
```

Expected output:

```text
docs/v2_refactor_plan.md
```

The plan should include:

```text
current module mapping
new v2 module mapping
files to reuse
files to create
files to modify
risk points
execution order
```

---

### Stage 03: Schema Design

Prompt file:

```text
docs/prompts/03_schema_design.md
```

Goal:

```text
Implement or define schemas for Document, Section, EvidenceChunk, GraphNode, GraphEdge, retrieval objects, and QA debug records.
```

Expected outputs may include:

```text
app/schemas/document_schema.py
app/schemas/evidence_schema.py
app/schemas/graph_schema.py
app/schemas/retrieval_schema.py
app/schemas/qa_schema.py
```

If the project uses a different structure, adapt while keeping responsibilities clear.

---

### Stage 04: Vector Evidence Store

Prompt file:

```text
docs/prompts/04_vector_evidence_store.md
```

Goal:

```text
Build a Vector Evidence Store pipeline using summary chunks, section chunks, small chunks, table chunks, code chunks, SQL chunks, and API chunks.
```

Expected outputs:

```text
data/outputs/{run_id}/documents.jsonl
data/outputs/{run_id}/sections.jsonl
data/outputs/{run_id}/evidence_chunks.jsonl
data/outputs/{run_id}/vector_index_report.md
```

Do not perform graph extraction in this stage.

---

### Stage 05: Business Semantic Graph

Prompt file:

```text
docs/prompts/05_business_semantic_graph.md
```

Goal:

```text
Build business-readable semantic graph from business documents, document summaries, section summaries, glossary, function list, process documents, and test cases.
```

Expected outputs:

```text
data/outputs/{run_id}/business_nodes.jsonl
data/outputs/{run_id}/business_edges.jsonl
data/outputs/{run_id}/business_graph_report.md
```

Business graph should not be built by blindly extracting from all small chunks.

---

### Stage 06: Implementation Graph

Prompt file:

```text
docs/prompts/06_implementation_graph.md
```

Goal:

```text
Build implementation graph from API documents, DDL, data dictionary, SQL, source code, workflow configs, and system design documents.
```

Expected outputs:

```text
data/outputs/{run_id}/implementation_nodes.jsonl
data/outputs/{run_id}/implementation_edges.jsonl
data/outputs/{run_id}/implementation_graph_report.md
```

---

### Stage 07: Entity Resolution and Graph Quality Filter

Prompt file:

```text
docs/prompts/07_entity_resolution_and_quality.md
```

Goal:

```text
Normalize and merge duplicate entities, filter low-quality graph items, reject schema-invalid nodes and edges, and generate quality reports.
```

Expected outputs:

```text
data/outputs/{run_id}/entity_aliases.jsonl
data/outputs/{run_id}/entity_resolution_report.md
data/outputs/{run_id}/graph_quality_report.md
data/outputs/{run_id}/filtered_graph_nodes.jsonl
data/outputs/{run_id}/filtered_graph_edges.jsonl
data/outputs/{run_id}/rejected_graph_items.jsonl
```

---

### Stage 08: Evidence Linker

Prompt file:

```text
docs/prompts/08_evidence_linker.md
```

Goal:

```text
Ensure graph nodes and graph edges are linked to evidence chunks.
```

Expected outputs:

```text
data/outputs/{run_id}/graph_nodes_linked.jsonl
data/outputs/{run_id}/graph_edges_linked.jsonl
data/outputs/{run_id}/evidence_links.jsonl
data/outputs/{run_id}/evidence_link_report.md
```

---

### Stage 09: Neptune Export and Loader

Prompt file:

```text
docs/prompts/09_neptune_loader.md
```

Goal:

```text
Export graph data to Neptune-compatible Cypher and optionally load to Neptune.
```

Expected outputs:

```text
data/outputs/{run_id}/load_neptune.cypher
data/outputs/{run_id}/neptune_load_report.md
```

Rules:

```text
Do not clear Neptune by default.
Do not load Neptune by default.
Support dry-run.
Support Cypher export.
Support --layer business / implementation / evidence / all.
```

---

### Stage 10: Retriever V2

Prompt file:

```text
docs/prompts/10_retriever_v2.md
```

Goal:

```text
Implement Query Router, Business Graph Retriever, Implementation Graph Retriever, Vector Evidence Retriever, Context Reranker, and Hybrid Context Builder.
```

Expected output:

```text
data/outputs/{run_id}/retrieval_test_report.md
```

Retrieval should not simply concatenate vector topK and graph topK.

---

### Stage 11: QA Terminal V2

Prompt file:

```text
docs/prompts/11_qa_terminal_v2.md
```

Goal:

```text
Create or modify QA terminal for the new architecture.
```

Expected runnable command:

```bash
python scripts/qa_terminal_v2.py \
  --run-id murata_semantic_v2 \
  --dataset murata \
  --view debug
```

Debug output should include:

```text
query intent
primary retrieval path
matched graph entities
graph paths
evidence chunks
final context size
answer
```

---

### Stage 12: Murata E2E Test

Prompt file:

```text
docs/prompts/12_murata_e2e_test.md
```

Goal:

```text
Run end-to-end test using Murata documents and the V2 architecture.
```

Expected command:

```bash
python scripts/rebuild_murata_v2.py \
  --run-id murata_semantic_v2 \
  --dataset murata
```

Expected report:

```text
data/outputs/murata_semantic_v2/qa_e2e_test_report.md
```

Required test questions:

```text
Q1. 仕訳基礎とは何ですか？
Q2. 支払申請の業務プロセスを説明してください。
Q3. payment または 支払 に関連する業務機能、API、テーブルを整理してください。
Q4. 付款申请相关的业务流程、系统模块和数据表之间是什么关系？
Q5. 某个业务流程如果要外移到 OA，当前系统中可能影响哪些功能、API、表和代码模块？
Q6. 当前 Murata 项目中，业务层 Semantic Map 和实现层 Implementation Graph 分别包含哪些主要节点？
Q7. 当前图谱中有哪些节点没有 evidence，需要后续人工补充文档？
```

---

### Stage 13: Visualization Export

Prompt file:

```text
docs/prompts/13_visualization_export.md
```

Goal:

```text
Export business graph, implementation graph, evidence-linked graph, and query-focused subgraph.
```

Expected outputs:

```text
data/outputs/{run_id}/business_semantic_graph.mmd
data/outputs/{run_id}/implementation_graph.mmd
data/outputs/{run_id}/business_semantic_graph.html
data/outputs/{run_id}/implementation_graph.html
```

At minimum, Mermaid output is required.

---

### Stage 99: Acceptance Checklist

Prompt file:

```text
docs/prompts/99_acceptance_checklist.md
```

Goal:

```text
Check whether all required files, reports, commands, and quality metrics are available.
```

Expected output:

```text
data/outputs/{run_id}/final_refactor_report.md
```

The final report must include:

```text
1. What was completed
2. What files were added or modified
3. New architecture flow
4. How to rebuild Murata knowledge base
5. How to export/load Neptune
6. How to start QA Terminal V2
7. Murata test results
8. Old vs new architecture comparison
9. Current limitations
10. Next recommendations
```

---

## 6. Recommended V2 Directory Structure

Try to adapt the current project to the following structure.

If the project already has similar modules, reuse and adapt them.

```text
app/
├── schemas/
│   ├── document_schema.py
│   ├── evidence_schema.py
│   ├── graph_schema.py
│   ├── retrieval_schema.py
│   └── qa_schema.py
│
├── ingestion/
│   ├── document_loader.py
│   ├── document_normalizer.py
│   ├── document_structure_parser.py
│   └── murata_loader.py
│
├── evidence/
│   ├── chunk_builder.py
│   ├── summary_builder.py
│   ├── evidence_store_builder.py
│   ├── evidence_index.py
│   └── evidence_linker.py
│
├── graph/
│   ├── schema_registry.py
│   ├── business_graph_builder.py
│   ├── implementation_graph_builder.py
│   ├── graph_entity_resolver.py
│   ├── graph_quality_filter.py
│   ├── graph_evidence_linker.py
│   ├── graph_exporter.py
│   └── neptune_loader.py
│
├── retrieval/
│   ├── query_router.py
│   ├── vector_evidence_retriever.py
│   ├── business_graph_retriever.py
│   ├── implementation_graph_retriever.py
│   ├── hybrid_context_builder.py
│   └── context_reranker.py
│
├── qa/
│   ├── answer_generator.py
│   └── qa_terminal_v2.py
│
└── pipelines/
    ├── build_vector_evidence_store.py
    ├── build_business_semantic_graph.py
    ├── build_implementation_graph.py
    ├── link_graph_evidence.py
    ├── load_neptune_v2.py
    ├── qa_e2e_test_v2.py
    └── rebuild_murata_v2.py
```

Scripts can be placed under:

```text
scripts/
```

if the current project already uses script-based execution.

---

## 7. Required Commands

Eventually the following commands should work.

### 7.1 Rebuild Murata V2

```bash
python scripts/rebuild_murata_v2.py \
  --run-id murata_semantic_v2 \
  --dataset murata
```

### 7.2 QA Terminal V2

```bash
python scripts/qa_terminal_v2.py \
  --run-id murata_semantic_v2 \
  --dataset murata \
  --view debug
```

### 7.3 Neptune Export Dry Run

```bash
python scripts/load_neptune_v2.py \
  --run-id murata_semantic_v2 \
  --dataset murata \
  --layer all \
  --dry-run \
  --export-cypher data/outputs/murata_semantic_v2/load_neptune.cypher
```

Actual Neptune load should require explicit user instruction.

---

## 8. Required Output Files

At the end of the full refactor, these files should exist:

```text
data/outputs/murata_semantic_v2/documents.jsonl
data/outputs/murata_semantic_v2/sections.jsonl
data/outputs/murata_semantic_v2/evidence_chunks.jsonl

data/outputs/murata_semantic_v2/business_nodes.jsonl
data/outputs/murata_semantic_v2/business_edges.jsonl

data/outputs/murata_semantic_v2/implementation_nodes.jsonl
data/outputs/murata_semantic_v2/implementation_edges.jsonl

data/outputs/murata_semantic_v2/entity_aliases.jsonl
data/outputs/murata_semantic_v2/filtered_graph_nodes.jsonl
data/outputs/murata_semantic_v2/filtered_graph_edges.jsonl
data/outputs/murata_semantic_v2/rejected_graph_items.jsonl

data/outputs/murata_semantic_v2/graph_nodes_linked.jsonl
data/outputs/murata_semantic_v2/graph_edges_linked.jsonl
data/outputs/murata_semantic_v2/evidence_links.jsonl

data/outputs/murata_semantic_v2/load_neptune.cypher

data/outputs/murata_semantic_v2/vector_index_report.md
data/outputs/murata_semantic_v2/business_graph_report.md
data/outputs/murata_semantic_v2/implementation_graph_report.md
data/outputs/murata_semantic_v2/entity_resolution_report.md
data/outputs/murata_semantic_v2/graph_quality_report.md
data/outputs/murata_semantic_v2/evidence_link_report.md
data/outputs/murata_semantic_v2/neptune_load_report.md
data/outputs/murata_semantic_v2/retrieval_test_report.md
data/outputs/murata_semantic_v2/qa_e2e_test_report.md
data/outputs/murata_semantic_v2/final_refactor_report.md
```

---

## 9. Required Quality Metrics

The final reports should include:

```text
business nodes count
business edges count
implementation nodes count
implementation edges count
evidence chunks count
linked node ratio
linked edge ratio
rejected node count
rejected edge count
duplicated entity merge count
top 20 high-degree nodes
top 20 low-confidence edges
top 20 nodes without evidence
top 20 edges without evidence
```

---

## 10. Important Safety Rules

Do not:

```text
delete existing pipeline
clear Neptune automatically
load Neptune automatically
overwrite old outputs without explicit run_id isolation
invent graph schema freely
build the business graph from all small chunks
skip evidence linking
claim success if tests fail
```

Always:

```text
use run_id-specific output directory
write intermediate JSONL files
generate Markdown reports
record errors
update docs/task_state.md
provide reproducible commands
```

---

## 11. Current Status Tracking

Progress is tracked in:

```text
docs/task_state.md
```

Before starting any stage, read it.

After completing any stage, update it.

The task state file is the single source of truth for:

```text
current stage
completed stages
modified files
generated files
open issues
next action
```

---

## 12. Final Goal

The final system should support questions like:

```text
What is this business concept?
What is the business process?
Which functions support this process?
Which APIs, services, tables, and code modules are related?
Which evidence chunks support this answer?
What would be impacted if this process is moved to OA?
```

The final answer should be grounded in:

```text
Business Graph Context
Implementation Graph Context
Vector Evidence Context
```

The refactored system should be more useful for:

```text
enterprise knowledge QA
business process understanding
impact analysis
system migration analysis
EAI workflow generation
operation troubleshooting
```
