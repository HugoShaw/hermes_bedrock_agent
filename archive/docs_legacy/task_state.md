# GraphRAG V2 Refactor Task State

## 1. Project

```text
Project Name: Enterprise GraphRAG V2 Refactor
Target Architecture: Business Semantic Graph + Implementation Graph + Vector Evidence Store
Dataset: murata
Run ID: murata_semantic_v2
````

---

## 2. Current Objective

Refactor the current dual-path GraphRAG system into a layered architecture:

```text
Business Semantic Graph + Implementation Graph + Vector Evidence Store
```

The main idea is:

```text
Vector Store finds evidence.
Business Semantic Graph finds business structure.
Implementation Graph finds system/API/code/data structure.
Evidence Linker connects graph knowledge back to source text.
Query Router decides the retrieval path.
Hybrid Context Builder organizes final context for answer generation.
```

---

## 3. Current Stage

```text
Current Stage: Completed
Current Status: Done
Last Updated: 2026-05-19
Updated By: Hermes Agent
Stage 02 Completion: Done (2026-05-19)
Stage 03 Completion: Done (2026-05-19)
Stage 04 Completion: Done (2026-05-19)
Stage 05 Completion: Done (2026-05-19)
Stage 06 Completion: Done (2026-05-19)
Stage 07 Completion: Done (2026-05-19)
Stage 08 Completion: Done (2026-05-19)
Stage 09 Completion: Done (2026-05-19)
Stage 10 Completion: Done (2026-05-19)
Stage 11 Completion: Done (2026-05-19)
Stage 12 Completion: Done (2026-05-19)
Stage 99 Completion: Done (2026-05-19)
P0 Fix Completion: Done (2026-05-19)
```

---

## 4. Stage Progress

| Stage | Name                          | Status      | Prompt File                                      | Main Output                           | Notes                                       |
| ----- | ----------------------------- | ----------- | ------------------------------------------------ | ------------------------------------- | ------------------------------------------- |
| 00    | Initial Setup                 | Done        | docs/prompts/00_master_task.md                   | docs/task_state.md                    | Prepare project instructions and task state |
| 01    | Project Scan                  | Done        | docs/prompts/01_scan_project.md                  | docs/refactor_scan_report.md          | No code modification                        |
| 02    | V2 Refactor Plan              | Done        | docs/prompts/02_refactor_plan.md                 | docs/v2_refactor_plan.md              | 35 new files planned, 0 V1 modifications    |
| 03    | Schema Design                 | Done        | docs/prompts/03_schema_design.md                 | app/schemas/*                         | V2 Pydantic schemas + registry + config     |
| 04    | Vector Evidence Store         | Done        | docs/prompts/04_vector_evidence_store.md         | evidence_chunks.jsonl                 | 153 docs → 13010 sections → 26570 chunks    |
| 05    | Business Semantic Graph       | Done        | docs/prompts/05_business_semantic_graph.md       | business_nodes/edges.jsonl            | 76 nodes, 28 edges, heuristic mode          |
| 06    | Implementation Graph          | Done        | docs/prompts/06_implementation_graph.md          | implementation_nodes/edges.jsonl      | 588 nodes, 521 edges, heuristic mode        |
| 07    | Entity Resolution and Quality | Done        | docs/prompts/07_entity_resolution_and_quality.md | filtered_graph_nodes/edges.jsonl      | 664 nodes, 549 edges, 0 rejected, 359 aliases |
| 08    | Evidence Linker               | Done        | docs/prompts/08_evidence_linker.md               | graph_nodes_linked/edges_linked.jsonl | 6521 links, 100% coverage, 0 dump artifacts |
| 09    | Neptune Export and Loader     | Done        | docs/prompts/09_neptune_loader.md                | load_neptune.cypher                   | 5280 stmts, dry-run, 0 skipped edges        |
| 10    | Retriever V2                  | Done        | docs/prompts/10_retriever_v2.md                  | retrieval_test_report.md              | 7 queries, heuristic, 23.6s, all pass       |
| 11    | QA Terminal V2                | Done        | docs/prompts/11_qa_terminal_v2.md                | qa_e2e_test_report.md                 | LLM mode 7/7 pass, context budget enforced  |
| 12    | Murata E2E Test               | Done        | docs/prompts/12_murata_e2e_test.md               | murata_e2e_validation_report.md       | CONDITIONAL GO: 6/7 Pass, 1 Partial, avg 8.7/10 |
| 13    | Visualization Export          | Pending     | docs/prompts/13_visualization_export.md          | *.mmd / *.html                        | Mermaid or HTML graph export                |
| 99    | Acceptance Checklist          | Done        | docs/prompts/99_acceptance_checklist.md          | final_refactor_report.md              | CONDITIONAL GO, avg 8.7/10                  |

Status values:

```text
Not Started
Pending
In Progress
Blocked
Done
Done With Issues
Skipped
Failed
```

---

## 5. Global Configuration

```text
dataset = murata
run_id = murata_semantic_v2
output_dir = data/outputs/murata_semantic_v2
docs_dir = docs
prompts_dir = docs/prompts
task_state_file = docs/task_state.md
```

---

## 6. Environment Information

Fill this section during Stage 01.

```text
Project Root: /home/ubuntu/projects/hermes_bedrock_agent
Python Version: 3.11.15
Virtual Environment: .venv (uv-managed)
Package Manager: uv + hatchling
AWS Region: ap-northeast-1
Neptune Graph ID: g-nbuyck5yl8
Vector Store Backend: lancedb (local)
Embedding Model: amazon.titan-embed-text-v2:0 (1024 dims)
LLM Model: jp.anthropic.claude-sonnet-4-6 (Bedrock inference profile)
Murata Data Path: s3://s3-hulftchina-rd/Murata/ (25 sample files curated)
Existing Output Path: ~/projects/data/vector_store/lancedb/murata_e2e_murata_rebuild_v1.lance
```

---

## 7. Existing Project Scan Summary

Fill this section during Stage 01.

```text
Current document parser: src/hermes_bedrock_agent/parsers/ (PDF, text, VLM, image, merge)
Current chunking module: src/hermes_bedrock_agent/chunking/chunker.py (structure-aware)
Current embedding module: src/hermes_bedrock_agent/embedding/embedder.py (Titan v2)
Current vector store module: src/hermes_bedrock_agent/vector_store/lancedb_store.py
Current graph extraction module: src/hermes_bedrock_agent/graph/extractor.py (LLM-based)
Current Neptune loader: src/hermes_bedrock_agent/graph/neptune_loader.py (parameterized Cypher)
Current entity index module: src/hermes_bedrock_agent/retrieval/query_entity_extractor.py
Current graph retriever: src/hermes_bedrock_agent/retrieval/graph_retriever.py (Neptune)
Current vector retriever: src/hermes_bedrock_agent/retrieval/text_retriever.py (LanceDB)
Current context builder: src/hermes_bedrock_agent/retrieval/context_builder.py
Current QA terminal: scripts/qa_terminal.py
Current config files: configs/{graph_schema,ingestion,llm,enrichment,murata_rebuild_v1}.yaml
```

---

## 8. V2 Module Mapping

Fill this section during Stage 02.

| V2 Responsibility              | Existing Module | Reuse / Modify / New | Target File | Notes |
| ------------------------------ | --------------- | -------------------- | ----------- | ----- |
| Document schema                | schemas/document.py | New | src/.../v2/schemas/document_schema.py | Pydantic DocumentRecord, SectionRecord |
| Evidence schema                | schemas/chunk.py | New | src/.../v2/schemas/evidence_schema.py | EvidenceChunk with V2 ChunkType enum |
| Graph schema                   | schemas/graph.py | New | src/.../v2/schemas/graph_schema.py | GraphNode, GraphEdge with layer field |
| Document loader                | ingestion/ + clients/s3 | Reuse | (existing) | S3 scan + file routing unchanged |
| Document normalizer            | parsers/ + ingestion/ | Reuse | (existing) | Text/PDF/VLM parsers unchanged |
| Chunk builder                  | chunking/chunker.py | New wrapper | src/.../v2/evidence/chunk_builder.py | Wraps existing chunker + adds V2 types |
| Evidence store builder         | embedding/ + vector_store/ | New orchestrator | src/.../v2/evidence/evidence_store_builder.py | Coordinates chunk→embed→store |
| Summary builder                | — | New | src/.../v2/evidence/summary_builder.py | LLM doc+section summaries |
| Business graph builder         | graph/extractor.py | New | src/.../v2/graph/business_graph_builder.py | Summary-first, schema-constrained |
| Implementation graph builder   | graph/extractor.py | New | src/.../v2/graph/implementation_graph_builder.py | Code/API/DDL focused |
| Entity resolver                | graph/normalizer.py | New | src/.../v2/graph/entity_resolver.py | CJK alias + merge report |
| Quality filter                 | graph/quality_review.py | New | src/.../v2/graph/quality_filter.py | Expanded for V2 schema |
| Evidence linker                | — | New | src/.../v2/graph/evidence_linker.py | Graph↔chunk linking |
| Neptune loader                 | graph/neptune_loader.py | Reuse | (existing) + scripts/load_neptune_v2.py | Dry-run + layer filter wrapper |
| Query router                   | retrieval/intent_router.py | New | src/.../v2/retrieval/query_router.py | V2 intents + layer routing |
| Vector evidence retriever      | retrieval/text_retriever.py | New wrapper | src/.../v2/retrieval/vector_evidence_retriever.py | Evidence-typed search |
| Business graph retriever       | retrieval/graph_retriever.py | New | src/.../v2/retrieval/business_graph_retriever.py | Business layer scoped |
| Implementation graph retriever | retrieval/graph_retriever.py | New | src/.../v2/retrieval/implementation_graph_retriever.py | Impl layer scoped |
| Hybrid context builder         | retrieval/context_builder.py | New | src/.../v2/retrieval/hybrid_context_builder.py | 3-section structured context |
| QA terminal v2                 | scripts/qa_terminal.py | New | scripts/qa_terminal_v2.py | Debug mode + layer visibility |

---

## 9. Generated Files

Append generated files here after each stage.

| Stage | File                           | Purpose                          | Status  |
| ----- | ------------------------------ | -------------------------------- | ------- |
| 00    | .hermes.md                     | Project-level Hermes instruction | Done    |
| 00    | docs/prompts/00_master_task.md | Master task prompt               | Done    |
| 00    | docs/task_state.md             | Task progress tracker            | Done    |
| 01    | docs/refactor_scan_report.md   | Project scan report              | Done    |
| 02    | docs/v2_refactor_plan.md       | V2 architecture and module plan  | Done    |
| 03    | src/hermes_bedrock_agent/v2/__init__.py | V2 package init | Done |
| 03    | src/hermes_bedrock_agent/v2/schemas/__init__.py | Schema exports | Done |
| 03    | src/hermes_bedrock_agent/v2/schemas/document_schema.py | DocumentRecord, SectionRecord | Done |
| 03    | src/hermes_bedrock_agent/v2/schemas/evidence_schema.py | EvidenceChunk | Done |
| 03    | src/hermes_bedrock_agent/v2/schemas/graph_schema.py | GraphNode, GraphEdge | Done |
| 03    | src/hermes_bedrock_agent/v2/schemas/retrieval_schema.py | QueryIntent, RetrievalPlan, RetrievalResult, HybridContext | Done |
| 03    | src/hermes_bedrock_agent/v2/schemas/qa_schema.py | QADebugRecord | Done |
| 03    | src/hermes_bedrock_agent/v2/graph/__init__.py | Graph package init | Done |
| 03    | src/hermes_bedrock_agent/v2/graph/schema_registry.py | Labels, relations, layers, validation | Done |
| 03    | configs/murata_semantic_v2.yaml | V2 run configuration | Done |
| 03    | data/outputs/murata_semantic_v2/schema_design_report.md | Stage 03 report | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/__init__.py | Evidence package init | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/jsonl_io.py | JSONL read/write utilities | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/document_loader.py | S3 document loader | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/document_structure_parser.py | Section parser | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/summary_builder.py | Extractive summary builder | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/chunk_builder.py | Evidence chunk builder | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/evidence_store_builder.py | Pipeline orchestrator | Done |
| 04    | src/hermes_bedrock_agent/v2/evidence/evidence_index.py | LanceDB vector index adapter | Done |
| 04    | src/hermes_bedrock_agent/v2/pipelines/__init__.py | Pipelines package init | Done |
| 04    | src/hermes_bedrock_agent/v2/pipelines/build_vector_evidence_store.py | Pipeline entry point | Done |
| 04    | scripts/build_vector_evidence_store_v2.py | CLI wrapper script | Done |
| 04    | data/outputs/murata_semantic_v2/documents.jsonl | 153 document records | Done |
| 04    | data/outputs/murata_semantic_v2/sections.jsonl | 13010 section records | Done |
| 04    | data/outputs/murata_semantic_v2/evidence_chunks.jsonl | 26570 evidence chunks | Done |
| 04    | data/outputs/murata_semantic_v2/vector_index_report.md | Stage 04 report | Done |
| 05    | src/hermes_bedrock_agent/v2/graph/business_evidence_selector.py | Business evidence selection/filter | Done |
| 05    | src/hermes_bedrock_agent/v2/graph/business_extraction_prompts.py | LLM extraction prompt templates | Done |
| 05    | src/hermes_bedrock_agent/v2/graph/business_graph_builder.py | Business graph heuristic builder | Done |
| 05    | src/hermes_bedrock_agent/v2/graph/business_graph_reporter.py | Report generator | Done |
| 05    | src/hermes_bedrock_agent/v2/pipelines/build_business_semantic_graph.py | Pipeline entry point | Done |
| 05    | scripts/build_business_semantic_graph_v2.py | CLI wrapper script | Done |
| 05    | data/outputs/murata_semantic_v2/business_candidate_evidence.jsonl | 554 selected candidate chunks | Done |
| 05    | data/outputs/murata_semantic_v2/business_nodes.jsonl | 76 business nodes | Done |
| 05    | data/outputs/murata_semantic_v2/business_edges.jsonl | 28 business edges | Done |
| 05    | data/outputs/murata_semantic_v2/rejected_business_graph_items.jsonl | 0 rejected items | Done |
| 05    | data/outputs/murata_semantic_v2/business_graph_report.md | Stage 05 report | Done |
| 06    | src/hermes_bedrock_agent/v2/graph/implementation_evidence_selector.py | Implementation evidence selection/filter | Done |
| 06    | src/hermes_bedrock_agent/v2/graph/implementation_extraction_prompts.py | LLM extraction prompt templates | Done |
| 06    | src/hermes_bedrock_agent/v2/graph/implementation_graph_builder.py | Heuristic graph building (DDL, code, config) | Done |
| 06    | src/hermes_bedrock_agent/v2/graph/implementation_graph_reporter.py | Report generator | Done |
| 06    | src/hermes_bedrock_agent/v2/pipelines/build_implementation_graph.py | Pipeline orchestration module | Done |
| 06    | scripts/build_implementation_graph_v2.py | CLI wrapper (--dry-run, --config) | Done |
| 06    | data/outputs/murata_semantic_v2/implementation_candidate_evidence.jsonl | 1161 candidate chunks selected | Done |
| 06    | data/outputs/murata_semantic_v2/implementation_nodes.jsonl | 588 implementation nodes | Done |
| 06    | data/outputs/murata_semantic_v2/implementation_edges.jsonl | 521 implementation edges | Done |
| 06    | data/outputs/murata_semantic_v2/rejected_implementation_graph_items.jsonl | 0 rejected items | Done |
| 06    | data/outputs/murata_semantic_v2/implementation_graph_report.md | Stage 06 report | Done |
| 07    | src/hermes_bedrock_agent/v2/graph/graph_merge_utils.py | Normalization and merge utilities | Done |
| 07    | src/hermes_bedrock_agent/v2/graph/graph_entity_resolver.py | Entity resolution (dedup, aliases) | Done |
| 07    | src/hermes_bedrock_agent/v2/graph/graph_quality_filter.py | Quality filter (schema, evidence, orphans) | Done |
| 07    | src/hermes_bedrock_agent/v2/graph/graph_quality_reporter.py | Report generator (resolution + quality) | Done |
| 07    | src/hermes_bedrock_agent/v2/pipelines/resolve_and_filter_graph.py | Pipeline orchestration module | Done |
| 07    | scripts/resolve_and_filter_graph_v2.py | CLI wrapper (--dry-run, --config) | Done |
| 07    | data/outputs/murata_semantic_v2/entity_aliases.jsonl | 359 alias records | Done |
| 07    | data/outputs/murata_semantic_v2/filtered_graph_nodes.jsonl | 664 filtered nodes | Done |
| 07    | data/outputs/murata_semantic_v2/filtered_graph_edges.jsonl | 549 filtered edges | Done |
| 07    | data/outputs/murata_semantic_v2/rejected_graph_items.jsonl | 0 rejected items | Done |
| 07    | data/outputs/murata_semantic_v2/entity_resolution_report.md | Entity resolution report | Done |
| 07    | data/outputs/murata_semantic_v2/graph_quality_report.md | Graph quality report | Done |
| 08    | src/hermes_bedrock_agent/v2/graph/graph_evidence_linker.py | Evidence linker (5 strategies) | Done |
| 08    | src/hermes_bedrock_agent/v2/graph/evidence_link_reporter.py | Report generator | Done |
| 08    | src/hermes_bedrock_agent/v2/pipelines/link_graph_evidence.py | Pipeline orchestration | Done |
| 08    | scripts/link_graph_evidence_v2.py | CLI wrapper (--dry-run, --config) | Done |
| 08    | data/outputs/murata_semantic_v2/graph_nodes_linked.jsonl | 664 linked nodes | Done |
| 08    | data/outputs/murata_semantic_v2/graph_edges_linked.jsonl | 549 linked edges | Done |
| 08    | data/outputs/murata_semantic_v2/evidence_links.jsonl | 6521 evidence links | Done |
| 08    | data/outputs/murata_semantic_v2/evidence_link_report.md | Evidence link report | Done |
| 09    | src/hermes_bedrock_agent/v2/graph/neptune_cypher_exporter.py | Cypher export (MERGE, layer filter) | Done |
| 09    | src/hermes_bedrock_agent/v2/graph/neptune_loader.py | Safe loader (dry-run/execute/clear guards) | Done |
| 09    | src/hermes_bedrock_agent/v2/graph/neptune_load_reporter.py | Load report generator | Done |
| 09    | src/hermes_bedrock_agent/v2/pipelines/load_neptune_v2.py | Pipeline orchestration | Done |
| 09    | scripts/load_neptune_v2.py | CLI wrapper (--dry-run, --execute, --layer, --clear-before-load) | Done |
| 09    | data/outputs/murata_semantic_v2/load_neptune.cypher | 5280 statements, all layers | Done |
| 09    | data/outputs/murata_semantic_v2/load_neptune_business.cypher | 104 statements, business layer | Done |
| 09    | data/outputs/murata_semantic_v2/load_neptune_implementation.cypher | 1109 statements, impl layer | Done |
| 09    | data/outputs/murata_semantic_v2/load_neptune_evidence.cypher | 0 statements (evidence-only) | Done |
| 09    | data/outputs/murata_semantic_v2/neptune_load_report.md | Dry-run load report | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/__init__.py | Retrieval package init | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/query_router.py | Heuristic intent classifier + plan builder | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/vector_evidence_retriever.py | JSONL keyword retriever for evidence chunks | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/business_graph_retriever.py | JSONL keyword retriever for business graph | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/implementation_graph_retriever.py | JSONL keyword retriever for impl graph | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/context_reranker.py | Deterministic reranker + dedup | Done |
| 10    | src/hermes_bedrock_agent/v2/retrieval/hybrid_context_builder.py | Multi-path context assembly | Done |
| 10    | src/hermes_bedrock_agent/v2/pipelines/test_retriever_v2.py | Test pipeline with 7 queries | Done |
| 10    | scripts/test_retriever_v2.py | CLI wrapper (--query, --debug) | Done |
| 10    | data/outputs/murata_semantic_v2/retrieval_test_report.md | 492 lines, full test results | Done |
| 11    | src/hermes_bedrock_agent/v2/qa/__init__.py | QA package init | Done |
| 11    | src/hermes_bedrock_agent/v2/qa/qa_prompts.py | Prompt templates (system prompt, structured context format, no-llm preview) | Done |
| 11    | src/hermes_bedrock_agent/v2/qa/answer_generator.py | AnswerGeneratorV2 with context budgeting, LLM/no-LLM modes | Done |
| 11    | src/hermes_bedrock_agent/v2/qa/qa_terminal_v2.py | Interactive QA terminal with debug mode | Done |
| 11    | src/hermes_bedrock_agent/v2/pipelines/qa_e2e_test_v2.py | E2E test pipeline (7 queries, report generation) | Done |
| 11    | scripts/qa_terminal_v2.py | CLI wrapper (--view debug, --no-llm, --query) | Done |
| 11    | scripts/qa_e2e_test_v2.py | CLI wrapper (--no-llm mode) | Done |
| 11    | data/outputs/murata_semantic_v2/qa_e2e_test_report.md | LLM mode 7/7 pass, all budget compliant | Done |
| 12    | data/outputs/murata_semantic_v2/murata_e2e_validation_report.md | CONDITIONAL GO, 6 Pass / 1 Partial, avg 8.7/10 | Done |
| 99    | data/outputs/murata_semantic_v2/final_refactor_report.md | Full acceptance report, architecture, metrics, recommendations | Done |
| 99    | data/outputs/murata_semantic_v2/acceptance_checklist.md | Concise checklist of all completed/remaining items | Done |
| P0    | src/hermes_bedrock_agent/v2/retrieval/evidence_coverage_stats.py | Evidence coverage stats computation | Done |
| P0    | scripts/test_evidence_coverage_query_v2.py | P0 regression test script | Done |
| P0    | data/outputs/murata_semantic_v2/p0_evidence_coverage_fix_report.md | P0 fix report | Done |

---

## 10. Modified Files

Append modified files here after each stage.

| Stage | File | Summary of Change | Risk Level |
| ----- | ---- | ----------------- | ---------- |
| 05    | docs/task_state.md | Updated Stage 05 status to Done, added generated files, commands, metrics | Low |
| 06    | docs/task_state.md | Updated Stage 06 status to Done, added generated files, metrics (588 nodes, 521 edges) | Low |
| 07    | docs/task_state.md | Updated Stage 07 status to Done, added generated files, metrics (664 nodes, 549 edges, 0 rejected) | Low |
| 08    | docs/task_state.md | Updated Stage 08 status to Done, evidence links (6521), 100% coverage | Low |
| 09    | docs/task_state.md | Updated Stage 09 status to Done, Cypher export (5280 stmts), dry-run only | Low |
| 10    | docs/task_state.md | Updated Stage 10 status to Done, retriever V2 (7 queries pass) | Low |
| 11    | docs/task_state.md | Updated Stage 11 status to Done, QA terminal + E2E test (7/7 LLM pass) | Low |
| 12    | docs/task_state.md | Updated Stage 12 status to Done, CONDITIONAL GO recommendation | Low |
| P0    | src/hermes_bedrock_agent/v2/schemas/retrieval_schema.py | Added evidence_coverage to ALLOWED_INTENTS | Low |
| P0    | src/hermes_bedrock_agent/v2/retrieval/query_router.py | New evidence_coverage intent classification + plan builder | Low |
| P0    | src/hermes_bedrock_agent/v2/retrieval/hybrid_context_builder.py | Import evidence_coverage_stats, special path for evidence_coverage intent | Low |
| P0    | src/hermes_bedrock_agent/v2/qa/qa_prompts.py | Evidence Coverage Rules in SYSTEM_PROMPT, no-LLM handler | Low |
| P0    | docs/task_state.md | Updated P0 fix status, generated files, modified files | Low |

Risk level values:

```text
Low
Medium
High
```

---

## 11. Commands Run

Append commands here after each stage.

| Stage | Command | Result | Notes |
| ----- | ------- | ------ | ----- |
| 04    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile |
| 04    | `PYTHONPATH=src python scripts/build_vector_evidence_store_v2.py --config configs/murata_semantic_v2.yaml --run-id murata_semantic_v2 --dataset murata --jsonl-only` | OK (11.4s) | 153 docs, 13010 sections, 26570 chunks |
| 05    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 05) |
| 05    | `PYTHONPATH=src python scripts/build_business_semantic_graph_v2.py --config configs/murata_semantic_v2.yaml --run-id murata_semantic_v2 --dataset murata --dry-run` | OK (1.5s) | 554 candidates selected |
| 05    | `PYTHONPATH=src python scripts/build_business_semantic_graph_v2.py --config configs/murata_semantic_v2.yaml --run-id murata_semantic_v2 --dataset murata` | OK (1.6s) | 76 nodes, 28 edges, 0 rejected |
| 06    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 06) |
| 06    | `PYTHONPATH=src python scripts/build_implementation_graph_v2.py --config configs/murata_semantic_v2.yaml --run-id murata_semantic_v2 --dataset murata --dry-run` | OK (2.0s) | 1161 candidates selected |
| 06    | `PYTHONPATH=src python scripts/build_implementation_graph_v2.py --config configs/murata_semantic_v2.yaml --run-id murata_semantic_v2 --dataset murata` | OK (2.4s) | 588 nodes, 521 edges, 0 rejected |
| 06    | Validation script (node/edge layer, label, relation, run_id, dataset, evidence checks) | ALL PASSED | 100% evidence coverage, 0 dump row nodes |
| 07    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 07) |
| 07    | `PYTHONPATH=src python scripts/resolve_and_filter_graph_v2.py --dry-run` | OK (0.0s) | 664 nodes, 549 edges, 359 aliases |
| 07    | `PYTHONPATH=src python scripts/resolve_and_filter_graph_v2.py` | OK (0.1s) | 664 nodes, 549 edges, 0 rejected |
| 07    | Validation script (schema, orphans, evidence, SQL dump, JOURNAL_BASE) | ALL PASSED | 100% evidence, 0 artifacts |
| 08    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 08) |
| 08    | `PYTHONPATH=src python scripts/link_graph_evidence_v2.py --dry-run` | OK (1.2s) | 6521 links, 100% coverage |
| 08    | `PYTHONPATH=src python scripts/link_graph_evidence_v2.py` | OK (1.3s) | 6521 links, 0 validation errors |
| 08    | Validation script (topology, links, chunks, JOURNAL_BASE, run_id) | ALL PASSED | 100% coverage, 0 contamination |
| 09    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 09) |
| 09    | `scripts/load_neptune_v2.py --layer all --dry-run` | OK (0.7s) | 5280 stmts, 0 skipped edges |
| 09    | `scripts/load_neptune_v2.py --layer business --dry-run` | OK (0.6s) | 104 stmts |
| 09    | `scripts/load_neptune_v2.py --layer implementation --dry-run` | OK (0.7s) | 1109 stmts |
| 09    | `scripts/load_neptune_v2.py --layer evidence --dry-run` | OK (0.7s) | 0 stmts (expected) |
| 09    | Validation script (MERGE, labels, safety, no-execute) | ALL PASSED | 0 raw SQL, 0 JOURNAL_BASE |
| 10    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 10) |
| 10    | `scripts/test_retriever_v2.py --dataset murata` (full suite) | OK (23.6s) | 7/7 queries pass |
| 10    | `scripts/test_retriever_v2.py --query "支払申請..." --debug` | OK (4.1s) | intent=business_process, 63 items |
| 11    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile (incl Stage 11) |
| 11    | `scripts/qa_e2e_test_v2.py --no-llm` | OK (10.9s) | 7/7 pass, all budget-compliant, modes={no_llm} |
| 11    | `scripts/qa_e2e_test_v2.py` (LLM mode) | OK (160s) | 7/7 pass, model=jp.anthropic.claude-sonnet-4-6, modes={llm} |
| 12    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile clean |
| 12    | `grep -c <chunk_id> evidence_chunks.jsonl` (x5) | OK | All referenced chunk_ids exist |
| 12    | `grep -c <source_path> documents.jsonl` (x3) | OK | All referenced source_paths exist |
| 12    | Evidence coverage check (664/664 nodes, 549/549 edges) | OK | 100% evidence link coverage confirmed |
| 99    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile clean |
| 99    | File existence check (14 JSONL + 11 reports + 1 cypher + 9 scripts) | OK | All required files present |
| 99    | MERGE statement count in load_neptune.cypher | 1,312 | Verified |
| 99    | HAS_EVIDENCE count in load_neptune.cypher | 3,421 | Verified |
| 11    | `scripts/qa_terminal_v2.py --view debug --no-llm --query "仕訳基礎..."` | OK (1.7s) | Debug trace + no-llm preview |
| P0    | `python -m compileall src/hermes_bedrock_agent/v2` | OK | All V2 files compile clean (including new module) |
| P0    | `scripts/test_evidence_coverage_query_v2.py --no-llm --debug` | PASS 4/4 | All evidence coverage queries return correct answer |
| P0    | `scripts/test_evidence_coverage_query_v2.py --debug --query Q7` | PASS 1/1 | LLM mode also correct (18.12s) |
| P0    | `scripts/qa_e2e_test_v2.py --no-llm` (full 7-query suite) | OK 7/7 | Q1-Q6 unchanged, Q7 now uses evidence_coverage intent |

---

## 12. Errors and Issues

Append errors here.

| Stage | Error / Issue | Likely Cause | Resolution / Next Action | Status |
| ----- | ------------- | ------------ | ------------------------ | ------ |
| 04    | JOURNAL_BASE20180530.SQL produced 21633 chunks (81% of all chunks) | Data dump file with many INSERT statements creating individual sql chunks per row | Consider filtering data-dump SQL files in Stage 05 graph extraction; keep them in evidence store for completeness | Deferred |
| 04    | Binary/office files (.xlsx, .pptx) get 3 chunks each (metadata-only) | Cannot extract text from binary office files without specialized parsers | Consider adding python-docx/openpyxl parsers in future; current coverage sufficient for graph extraction | Deferred |

Status values:

```text
Open
Investigating
Resolved
Deferred
Won't Fix
```

---

## 13. Open Questions

Use this section to record unclear items.

| Question                                | Owner         | Needed For            | Status   |
| --------------------------------------- | ------------- | --------------------- | -------- |
| What is the current Murata data path?   | Hermes        | Stage 01              | Resolved |
| What is the current Neptune Graph ID?   | User / Hermes | Stage 09              | Resolved |
| What vector backend is currently used?  | Hermes        | Stage 04              | Resolved |
| What embedding model is currently used? | Hermes        | Stage 04              | Resolved |
| What LLM model is currently configured? | Hermes        | Graph extraction / QA | Resolved |

---

## 14. Required Output Checklist

### 14.1 Core JSONL Outputs

| File                                                       | Required | Status  |
| ---------------------------------------------------------- | -------: | ------- |
| data/outputs/murata_semantic_v2/documents.jsonl            |      Yes | Done    |
| data/outputs/murata_semantic_v2/sections.jsonl             |      Yes | Done    |
| data/outputs/murata_semantic_v2/evidence_chunks.jsonl      |      Yes | Done    |
| data/outputs/murata_semantic_v2/business_nodes.jsonl       |      Yes | Done    |
| data/outputs/murata_semantic_v2/business_edges.jsonl       |      Yes | Done    |
| data/outputs/murata_semantic_v2/implementation_nodes.jsonl |      Yes | Done |
| data/outputs/murata_semantic_v2/implementation_edges.jsonl |      Yes | Done |
| data/outputs/murata_semantic_v2/entity_aliases.jsonl       |      Yes | Done |
| data/outputs/murata_semantic_v2/filtered_graph_nodes.jsonl |      Yes | Done |
| data/outputs/murata_semantic_v2/filtered_graph_edges.jsonl |      Yes | Done |
| data/outputs/murata_semantic_v2/rejected_graph_items.jsonl |      Yes | Done |
| data/outputs/murata_semantic_v2/graph_nodes_linked.jsonl   |      Yes | Done |
| data/outputs/murata_semantic_v2/graph_edges_linked.jsonl   |      Yes | Done |
| data/outputs/murata_semantic_v2/evidence_links.jsonl       |      Yes | Done |
| data/outputs/murata_semantic_v2/load_neptune.cypher        |      Yes | Done |

---

### 14.2 Report Outputs

| File                                                           | Required | Status  |
| -------------------------------------------------------------- | -------: | ------- |
| docs/refactor_scan_report.md                                   |      Yes | Done    |
| docs/v2_refactor_plan.md                                       |      Yes | Done    |
| data/outputs/murata_semantic_v2/vector_index_report.md         |      Yes | Done    |
| data/outputs/murata_semantic_v2/business_graph_report.md       |      Yes | Done    |
| data/outputs/murata_semantic_v2/implementation_graph_report.md |      Yes | Done |
| data/outputs/murata_semantic_v2/entity_resolution_report.md    |      Yes | Done |
| data/outputs/murata_semantic_v2/graph_quality_report.md        |      Yes | Done |
| data/outputs/murata_semantic_v2/evidence_link_report.md        |      Yes | Done |
| data/outputs/murata_semantic_v2/neptune_load_report.md         |      Yes | Done |
| data/outputs/murata_semantic_v2/retrieval_test_report.md        |      Yes | Done |
| data/outputs/murata_semantic_v2/qa_e2e_test_report.md          |      Yes | Done |
| data/outputs/murata_semantic_v2/final_refactor_report.md       |      Yes | Pending |

---

### 14.3 Visualization Outputs

| File                                                         |    Required | Status  |
| ------------------------------------------------------------ | ----------: | ------- |
| data/outputs/murata_semantic_v2/business_semantic_graph.mmd  | Recommended | Pending |
| data/outputs/murata_semantic_v2/implementation_graph.mmd     | Recommended | Pending |
| data/outputs/murata_semantic_v2/business_semantic_graph.html |    Optional | Pending |
| data/outputs/murata_semantic_v2/implementation_graph.html    |    Optional | Pending |

---

## 15. Required Commands Checklist

| Command                                                                                                                                                                    | Required | Status  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------: | ------- |
| `python scripts/rebuild_murata_v2.py --run-id murata_semantic_v2 --dataset murata`                                                                                         |      Yes | Pending |
| `python scripts/qa_terminal_v2.py --run-id murata_semantic_v2 --dataset murata --view debug`                                                                               |      Yes | Pending |
| `python scripts/load_neptune_v2.py --run-id murata_semantic_v2 --dataset murata --layer all --dry-run --export-cypher data/outputs/murata_semantic_v2/load_neptune.cypher` |      Yes | Pending |

---

## 16. Quality Metrics

Fill this section after graph building and QA testing.

```text
business_nodes_count = 76
business_edges_count = 28
implementation_nodes_count = 588
implementation_edges_count = 521
evidence_chunks_count = 26570
documents_count = 153
sections_count = 13010
chunks_by_type_summary = 13161
chunks_by_type_sql = 12723
chunks_by_type_small = 400
chunks_by_type_code = 206
chunks_by_type_operation = 48
chunks_by_type_section = 20
chunks_by_type_config = 12
avg_chunk_length_chars = 746
max_chunk_length_chars = 3000
min_chunk_length_chars = 1
linked_node_ratio = 100% (664/664)
linked_edge_ratio = 100% (549/549)
rejected_node_count = 0
rejected_edge_count = 0
duplicate_entity_merge_count = 359 aliases
top_high_degree_nodes = TODO
top_low_confidence_edges = TODO
top_nodes_without_evidence = 0
top_edges_without_evidence = 0
```

---

## 17. Murata E2E Test Results

Fill this section during Stage 12.

| Question                                                                 | Intent | Primary Path | Result Status | Notes |
| ------------------------------------------------------------------------ | ------ | ------------ | ------------- | ----- |
| Q1. 仕訳基礎とは何ですか？                                                          | definition   | vector_evidence         | Pass       | LLM answer with table schema evidence |
| Q2. 支払申請の業務プロセスを説明してください。                                                | business_process | business_graph      | Pass       | LLM structured business process answer |
| Q3. payment または 支払 に関連する業務機能、API、テーブルを整理してください。                          | relationship | hybrid                  | Pass       | API warning present (0 API nodes) |
| Q4. 付款申请相关的业务流程、系统模块和数据表之间是什么关系？                                         | relationship | hybrid                  | Pass       | Budget: 26031→4 evidence chunks |
| Q5. 某个业务流程如果要外移到 OA，当前系统中可能影响哪些功能、API、表和代码模块？                            | impact_analysis | hybrid               | Pass       | API warning, 5649→5 evidence chunks |
| Q6. 当前 Murata 项目中，业务層 Semantic Map 和実現層 Implementation Graph 分別包含哪些主要節點？ | relationship | hybrid                  | Pass       | Budget: 26570→3 evidence chunks |
| Q7. 当前图谱中有哪些节点没有 evidence，需要后续人工补充文档？                                    | relationship | hybrid                  | Pass       | Budget: 19349→12 evidence chunks |

Result status values:

```text
Pass
Partial
Fail
Blocked
Pending
```

---

## 18. Current Risks

| Risk                                                               | Impact | Mitigation                                           | Status |
| ------------------------------------------------------------------ | ------ | ---------------------------------------------------- | ------ |
| Current graph pipeline may be tightly coupled to chunk extraction  | High   | Add v2 pipeline instead of replacing old one         | Open   |
| Murata data path may be unclear                                    | Medium | Identify during Stage 01                             | Open   |
| Neptune graph ID may be missing                                    | Medium | Keep Neptune load optional and support Cypher export | Open   |
| Vector backend details may be unclear                              | Medium | Reuse existing vector backend after scan             | Open   |
| LLM schema-constrained extraction may need prompt/schema tuning    | High   | Use strict schema registry and rejected items log    | Open   |
| Entity resolution across Japanese/Chinese/English may be imperfect | Medium | Add alias file and report unresolved entities        | Open   |

---

## 19. Next Action

```text
Next Recommended Action:
V2 Refactor Complete (CONDITIONAL GO → P0 FIXED).
P0: DONE — Evidence coverage query handler fixed, regression passes.
P1 (optional): Load Neptune, build vector index, add API docs.
P2 (future): Neptune-backed retriever, LLM-enhanced extraction, graph visualization.
```
```

---

## 20. Stage Completion Template

When completing a stage, update this file using the following template.

````markdown
## Stage XX Completion Note

### Stage

Stage XX: <name>

### Status

Done / Done With Issues / Failed / Blocked

### Summary

<short summary>

### Files Modified

- file 1
- file 2

### Files Generated

- file 1
- file 2

### Commands Run

```bash
command here
````

### Errors

* error or none

### Open Issues

* issue or none

### Next Recommended Action

<next stage or fix>
```
```

---

## New Project: sample_20260519

```text
Project: sample_20260519
Dataset: sample_20260519
Run ID: sample_20260519_excel_v1
S3 URI: s3://s3-hulftchina-rd/サンプル20260519/
Config: configs/sample_20260519_excel_v1.yaml
Output Dir: data/outputs/sample_20260519_excel_v1/
```

### Stage X0: Excel Parser Optimization and Workbook Profiling

```text
Status: Done
Date: 2026-05-19
```

#### Files Created

- configs/sample_20260519_excel_v1.yaml
- src/hermes_bedrock_agent/v2/excel/__init__.py
- src/hermes_bedrock_agent/v2/excel/excel_schema.py
- src/hermes_bedrock_agent/v2/excel/s3_excel_discovery.py
- src/hermes_bedrock_agent/v2/excel/workbook_loader.py
- src/hermes_bedrock_agent/v2/excel/sheet_profiler.py
- src/hermes_bedrock_agent/v2/excel/table_region_detector.py
- src/hermes_bedrock_agent/v2/excel/header_detector.py
- src/hermes_bedrock_agent/v2/excel/row_normalizer.py
- src/hermes_bedrock_agent/v2/excel/excel_evidence_builder.py
- src/hermes_bedrock_agent/v2/excel/excel_reporter.py
- src/hermes_bedrock_agent/v2/pipelines/profile_excel_workbook.py
- scripts/profile_excel_workbook_v2.py
- data/outputs/sample_20260519_excel_v1/s3_file_manifest.jsonl
- data/outputs/sample_20260519_excel_v1/s3_discovery_report.md
- data/outputs/sample_20260519_excel_v1/excel_workbooks.jsonl
- data/outputs/sample_20260519_excel_v1/excel_sheets.jsonl
- data/outputs/sample_20260519_excel_v1/excel_table_regions.jsonl
- data/outputs/sample_20260519_excel_v1/excel_rows_normalized.jsonl
- data/outputs/sample_20260519_excel_v1/excel_cells_sample.jsonl
- data/outputs/sample_20260519_excel_v1/evidence_chunks.jsonl
- data/outputs/sample_20260519_excel_v1/excel_profile_report.md
- data/outputs/sample_20260519_excel_v1/excel_evidence_design.md
- data/outputs/sample_20260519_excel_v1/excel_parser_review_report.md

#### S3 Access Status

- S3 path accessible: Yes
- IAM Role: hulftchina-ec2-ssm-role
- Region: ap-northeast-1

#### Excel Files Discovered

1. サンプル20260519/01_基本設計/M社様_DSSスクリプト改修概要_フローチャート.xlsx (65 KB)
2. サンプル20260519/02_詳細設計/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx (1.5 MB)

#### Profiling Results

- Workbook count: 2
- Total sheet count: 29 (all visible, 0 hidden)
- Table regions detected: 27
- Multi-row headers detected: 25/27 regions
- Merged cell ranges found: 8,131
- Normalized rows: 1,458
- Cell samples collected: 4,087
- Evidence chunks generated: 190

#### Evidence Chunk Breakdown

- summary: 2
- section: 29
- table: 142
- api: 17

#### Sheet Types Detected

- field_mapping_sheet: 19 sheets
- business_rule_sheet: 4 sheets
- api_interface_sheet: 3 sheets
- business_process_sheet: 1 sheet
- unknown_sheet: 2 sheets

#### Parser Gaps Remaining

- .xls (legacy format) not supported
- Formula evaluation not performed
- Chart/image content not extracted
- VBA macros not parsed
- Large sheets capped at 1000 rows

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- Neptune — NOT loaded, NOT cleared

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/profile_excel_workbook.py scripts/profile_excel_workbook_v2.py
PYTHONPATH=src python -c "import openpyxl; print(openpyxl.__version__)"
PYTHONPATH=src python scripts/profile_excel_workbook_v2.py --config configs/sample_20260519_excel_v1.yaml --s3-uri "s3://s3-hulftchina-rd/サンプル20260519/" --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --clean-output --verbose
```

### Next Recommended Action

→ Superseded by X1 below.

---

### Stage X1: Excel Evidence Quality Review and GraphRAG Readiness

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Quality Metrics

- Total evidence chunks reviewed: 190
- Average quality score: 0.971
- Ready (score >= 0.8): 189
- Caution (score 0.6-0.8): 1
- Exclude (score < 0.6): 0
- Duplicate chunks: 0
- Invalid chunks: 0

#### Quality Flags Found

- merged_cell_heavy: 94 chunks (low severity — mapping sheets naturally merge-heavy)
- unclear_sheet_type: 2 chunks (metadata/changelog sheets, minor)
- too_large: 2 chunks (slightly over 3000 chars, acceptable)
- weak_text: 1 chunk (single section chunk with limited content)

#### GraphRAG Readiness

- Business Graph candidate sheets: 5
  - フローチャート (business_process_sheet, conf=0.5)
  - データ取得条件（納品一覧取得） (business_rule_sheet, conf=0.8)
  - データ取得条件（納品明細） (business_rule_sheet, conf=0.8)
  - データ取得条件（発注明細） (business_rule_sheet, conf=0.8)
  - データ取得条件（発注一覧取得） (business_rule_sheet, conf=0.8)

- Implementation Graph candidate sheets: 22
  - API呼出順序 (api_interface_sheet, conf=0.5)
  - マッピングシート（SAP→中間F） (field_mapping_sheet, conf=0.6)
  - マッピングシート（中間F→Andpad）【登録】 (field_mapping_sheet, conf=0.6)
  - マッピングシート（発注情報登録） (field_mapping_sheet, conf=0.6)
  - ... plus 18 more field_mapping and api_interface sheets

- Manual review required: 4 sheets
  - 概要 (low confidence, no normalized rows)
  - 変更履歴 (unknown_sheet, sparse)
  - DataSpider開発仕様 (low confidence)
  - 補足事項(DataSpider) (unknown_sheet, sparse)

#### Files Created

- src/hermes_bedrock_agent/v2/excel/excel_evidence_quality_reviewer.py
- src/hermes_bedrock_agent/v2/excel/excel_graphrag_readiness.py
- src/hermes_bedrock_agent/v2/excel/excel_sample_exporter.py
- src/hermes_bedrock_agent/v2/pipelines/review_excel_evidence_quality.py
- scripts/review_excel_evidence_quality_v2.py
- data/outputs/sample_20260519_excel_v1/excel_evidence_quality.jsonl
- data/outputs/sample_20260519_excel_v1/excel_sheet_readiness.jsonl
- data/outputs/sample_20260519_excel_v1/excel_evidence_quality_report.md
- data/outputs/sample_20260519_excel_v1/excel_graphrag_readiness_report.md
- data/outputs/sample_20260519_excel_v1/evidence_chunks_reviewed.jsonl
- data/outputs/sample_20260519_excel_v1/excel_sheets_reviewed.jsonl
- data/outputs/sample_20260519_excel_v1/review_samples/evidence_chunk_samples.md
- data/outputs/sample_20260519_excel_v1/review_samples/table_region_samples.md
- data/outputs/sample_20260519_excel_v1/review_samples/row_normalization_samples.md
- data/outputs/sample_20260519_excel_v1/review_samples/sheet_type_samples.md

#### Safe Fixes Applied

- Added dataset/run_id to all chunk metadata (in evidence_chunks_reviewed.jsonl)
- Added business_graph_candidate / implementation_graph_candidate flags to sheets (in excel_sheets_reviewed.jsonl)
- Original X0 files untouched

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- Neptune — NOT loaded, NOT cleared

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/review_excel_evidence_quality_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --sample-size 30 --export-samples --fix-safe-issues --verbose
```

### Next Recommended Action

→ Superseded by X2 below.

---

### Stage X2: Excel Implementation Graph Extraction

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Graph Metrics

- Implementation nodes: 579
- Implementation edges: 912
- MAPS_TO edges (field mappings): 195
- Evidence coverage (nodes): 100%
- Evidence coverage (edges): 100%
- Rejected items: 0
- Low-confidence items: 0
- Validation errors: 0

#### Node Count by Label

- Column: 553
- Message: 19
- System: 3 (SAP, 中間F, Andpad)
- File: 3
- API: 1

#### Edge Count by Relation

- HAS_FIELD: 709
- MAPS_TO: 195
- CONTAINS: 8

#### Candidate Selection

- Total evidence chunks: 190
- Selected for implementation: 173
- Excluded: 17 (overview, changelog, unknown_sheet types)
- Sheets processed: 22
- Manual-review sheets excluded: 4

#### Systems Detected

- SAP (source ERP system)
- 中間F (intermediate format/file)
- Andpad (target construction management system)

#### Files Created

- src/hermes_bedrock_agent/v2/excel/excel_implementation_evidence_selector.py
- src/hermes_bedrock_agent/v2/excel/excel_mapping_extractor.py
- src/hermes_bedrock_agent/v2/excel/excel_api_sequence_extractor.py
- src/hermes_bedrock_agent/v2/excel/excel_implementation_graph_builder.py
- src/hermes_bedrock_agent/v2/excel/excel_implementation_graph_reporter.py
- src/hermes_bedrock_agent/v2/pipelines/build_excel_implementation_graph.py
- scripts/build_excel_implementation_graph_v2.py
- data/outputs/sample_20260519_excel_v1/excel_implementation_candidate_evidence.jsonl
- data/outputs/sample_20260519_excel_v1/implementation_nodes.jsonl
- data/outputs/sample_20260519_excel_v1/implementation_edges.jsonl
- data/outputs/sample_20260519_excel_v1/rejected_excel_implementation_graph_items.jsonl
- data/outputs/sample_20260519_excel_v1/low_confidence_excel_implementation_items.jsonl
- data/outputs/sample_20260519_excel_v1/excel_implementation_graph_report.md

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- Neptune — NOT loaded, NOT cleared

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/build_excel_implementation_graph_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --dry-run --verbose
PYTHONPATH=src python scripts/build_excel_implementation_graph_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --verbose
```

### Next Recommended Action

→ Superseded by X3 below.

---

### Stage X3: Excel Business Graph Extraction

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Graph Metrics

- Business nodes: 78
- Business edges: 157
- BusinessProcess: 1
- BusinessStep: 0
- BusinessRule: 42
- BusinessTerm: 28
- Function: 4
- BusinessDomain: 2
- Project: 1
- Evidence coverage (nodes): 100%
- Evidence coverage (edges): 100%
- Rejected items: 0
- Low-confidence items: 0
- Validation errors: 0

#### Edge Count by Relation

- MENTIONED_IN: 81
- HAS_RULE: 42
- HAS_TERM: 28
- HAS_FUNCTION: 4
- CONTAINS: 2

#### Candidate Selection

- Total evidence chunks: 190
- Selected for business: 13
- Excluded: 177 (field_mapping, api_interface, unknown sheets)
- Sheets processed: 5 (フローチャート, データ取得条件 x4)
- Manual-review sheets excluded: 4

#### Business Domains Detected

- 発注情報連携 (purchase order data integration)
- 納品情報連携 (delivery data integration)

#### Functions Extracted

- 納品一覧取得
- 納品明細
- 発注明細
- 発注一覧取得

#### Files Created

- src/hermes_bedrock_agent/v2/excel/excel_business_evidence_selector.py
- src/hermes_bedrock_agent/v2/excel/excel_flowchart_extractor.py
- src/hermes_bedrock_agent/v2/excel/excel_business_rule_extractor.py
- src/hermes_bedrock_agent/v2/excel/excel_business_graph_builder.py
- src/hermes_bedrock_agent/v2/excel/excel_business_graph_reporter.py
- src/hermes_bedrock_agent/v2/pipelines/build_excel_business_graph.py
- scripts/build_excel_business_graph_v2.py
- data/outputs/sample_20260519_excel_v1/excel_business_candidate_evidence.jsonl
- data/outputs/sample_20260519_excel_v1/business_nodes.jsonl
- data/outputs/sample_20260519_excel_v1/business_edges.jsonl
- data/outputs/sample_20260519_excel_v1/rejected_excel_business_graph_items.jsonl
- data/outputs/sample_20260519_excel_v1/low_confidence_excel_business_items.jsonl
- data/outputs/sample_20260519_excel_v1/excel_business_graph_report.md

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- X2 implementation_nodes/edges — UNTOUCHED (579/912)
- Neptune — NOT loaded, NOT cleared

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/build_excel_business_graph_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --dry-run --verbose
PYTHONPATH=src python scripts/build_excel_business_graph_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --verbose
```

### Next Recommended Action

→ Superseded by X4 below.

---

### Stage X4: Excel Entity Resolution + Cross-Layer Linking + Evidence Link

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Graph Metrics

- Input business nodes/edges: 78 / 157
- Input implementation nodes/edges: 579 / 912
- Entity merged nodes: 5
- Entity merged edges: 0
- Alias records: 5
- Cross-layer links: 16 (4 exact_name_match, 6 domain_system_match, 6 substring_match)
- Filtered nodes: 652
- Filtered edges: 1059
- Rejected items: 26 (MENTIONED_IN edges targeting chunk_ids not in node set)
- Evidence links: 2404
- Node evidence coverage: 100%
- Edge evidence coverage: 100%
- Duplicate edge IDs: 0
- Invalid labels: 0
- Invalid relations: 0

#### Node Labels (Unified)

| Label | Count |
|-------|-------|
| Column | 548 |
| BusinessRule | 42 |
| BusinessTerm | 28 |
| Message | 19 |
| Function | 4 |
| System | 3 |
| File | 3 |
| BusinessDomain | 2 |
| API | 1 |
| BusinessProcess | 1 |
| Project | 1 |

#### Edge Relations (Unified)

| Relation | Count |
|----------|-------|
| HAS_FIELD | 695 |
| MAPS_TO | 183 |
| MENTIONED_IN | 81 |
| HAS_RULE | 42 |
| HAS_TERM | 28 |
| RELATED_TO | 16 |
| CONTAINS | 10 |
| HAS_FUNCTION | 4 |

#### Cross-Layer Links Generated

- Function:納品一覧取得 → Message:マッピングシート（納品一覧取得）
- Function:納品明細 → Message:マッピングシート（納品明細）
- Function:発注明細 → Message:マッピングシート（発注明細）
- Function:発注一覧取得 → Message:マッピングシート（発注一覧取得）
- BusinessDomain:発注情報連携 → System:SAP/中間F/Andpad
- BusinessDomain:納品情報連携 → System:SAP/中間F/Andpad
- BusinessTerm substring matches → Messages (6 links)

#### Files Created

- src/hermes_bedrock_agent/v2/excel/excel_entity_resolver.py
- src/hermes_bedrock_agent/v2/excel/excel_cross_layer_linker.py
- src/hermes_bedrock_agent/v2/excel/excel_graph_quality_filter.py
- src/hermes_bedrock_agent/v2/excel/excel_evidence_linker.py
- src/hermes_bedrock_agent/v2/excel/excel_unified_graph_reporter.py
- src/hermes_bedrock_agent/v2/pipelines/unify_excel_graph.py
- scripts/unify_excel_graph_v2.py
- data/outputs/sample_20260519_excel_v1/filtered_graph_nodes.jsonl (652)
- data/outputs/sample_20260519_excel_v1/filtered_graph_edges.jsonl (1059)
- data/outputs/sample_20260519_excel_v1/graph_nodes_linked.jsonl (652)
- data/outputs/sample_20260519_excel_v1/graph_edges_linked.jsonl (1059)
- data/outputs/sample_20260519_excel_v1/evidence_links.jsonl (2404)
- data/outputs/sample_20260519_excel_v1/entity_aliases.jsonl (5)
- data/outputs/sample_20260519_excel_v1/cross_layer_links.jsonl (16)
- data/outputs/sample_20260519_excel_v1/rejected_graph_items.jsonl (26)
- data/outputs/sample_20260519_excel_v1/excel_graph_quality_report.md
- data/outputs/sample_20260519_excel_v1/excel_evidence_link_report.md
- data/outputs/sample_20260519_excel_v1/excel_unified_graph_report.md

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- X2 implementation_nodes/edges — UNTOUCHED (579/912)
- X3 business_nodes/edges — UNTOUCHED (78/157)
- Neptune — NOT loaded, NOT cleared

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/unify_excel_graph_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --dry-run --verbose
PYTHONPATH=src python scripts/unify_excel_graph_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1 --verbose
```

### Next Recommended Action

→ Superseded by X5 below.

---

### Stage X5: Excel Neptune Export and Real Load

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Goal

Export unified graph (652 nodes + 1059 edges + 134 evidence chunks + 2404 evidence links)
into Neptune graph database (g-nbuyck5yl8, ap-northeast-1).

#### Results

| Metric | Value |
|--------|-------|
| Neptune cleared | YES |
| Neptune loaded | YES |
| Total nodes in Neptune | 786 (652 graph + 134 evidence) |
| Total relationships in Neptune | 2059 (978 graph + 1081 HAS_EVIDENCE) |
| EvidenceChunk nodes | 134 |
| HAS_EVIDENCE edges | 1081 |
| MAPS_TO edges | 183 |
| Cross-layer RELATED_TO | 16 |
| Run ID verified | 786/786 = 100% |
| Dataset verified | 786/786 = 100% |
| Murata contamination | 0 (CLEAN) |

#### Files Created

- src/hermes_bedrock_agent/v2/excel/excel_neptune_exporter.py
- src/hermes_bedrock_agent/v2/excel/excel_neptune_loader.py
- src/hermes_bedrock_agent/v2/excel/excel_neptune_load_reporter.py
- src/hermes_bedrock_agent/v2/pipelines/load_excel_neptune.py
- scripts/load_excel_neptune_v2.py
- data/outputs/sample_20260519_excel_v1/load_neptune.cypher (2845 statements)
- data/outputs/sample_20260519_excel_v1/neptune_load_report.md
- data/outputs/sample_20260519_excel_v1/neptune_load_validation_report.md

#### Files Modified

- src/hermes_bedrock_agent/v2/graph/neptune_cypher_exporter.py (edge MERGE fix: relation_id instead of ~id; heading_path list→string)
- configs/sample_20260519_excel_v1.yaml (added neptune section)

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- X2 implementation_nodes/edges — UNTOUCHED (579/912)
- X3 business_nodes/edges — UNTOUCHED (78/157)
- Neptune — CLEARED and reloaded with sample_20260519_excel_v1

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/load_excel_neptune_v2.py --config configs/sample_20260519_excel_v1.yaml --dry-run --export-cypher data/outputs/sample_20260519_excel_v1/load_neptune.cypher
PYTHONPATH=src python scripts/load_excel_neptune_v2.py --config configs/sample_20260519_excel_v1.yaml --execute --clear-before-load --export-cypher data/outputs/sample_20260519_excel_v1/load_neptune.cypher
```

#### Bugs Fixed During Load

1. Neptune Analytics does not support custom `~id` on relationships → fixed to use `{relation_id: $edge_id}` as MERGE key
2. Neptune does not support array property values → fixed `heading_path` list to joined string

#### Next Recommended Action

→ Superseded by X6 below.

---

### Stage X6: Neptune Full Graph HTML Visualization Export

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Goal

Export full Neptune graph (786 nodes, 2059 edges) as interactive HTML
visualizations for demo and exploration.

#### Results

| Metric | Value |
|--------|-------|
| Source | Neptune (live query) |
| Nodes exported | 786 |
| Edges exported | 2059 |
| Missing endpoints | 0 |
| Duplicate nodes | 0 |
| Murata contamination | 0 |
| System nodes present | YES (SAP, 中間F, Andpad) |
| HTML files generated | 5 |
| Vis data JSON | 2 |
| Mermaid diagrams | 1 |
| Export time | 0.8s |

#### Files Created

- src/hermes_bedrock_agent/v2/excel/excel_neptune_graph_exporter.py
- src/hermes_bedrock_agent/v2/excel/excel_graph_visualization_builder.py
- src/hermes_bedrock_agent/v2/excel/excel_graph_visualization_reporter.py
- src/hermes_bedrock_agent/v2/pipelines/export_excel_graph_html.py
- scripts/export_excel_graph_html_v2.py
- data/outputs/sample_20260519_excel_v1/visualization/excel_knowledge_graph_full.html (878KB)
- data/outputs/sample_20260519_excel_v1/visualization/excel_knowledge_graph_core.html (515KB)
- data/outputs/sample_20260519_excel_v1/visualization/excel_field_mapping_graph.html (457KB)
- data/outputs/sample_20260519_excel_v1/visualization/excel_business_to_implementation_graph.html (513KB)
- data/outputs/sample_20260519_excel_v1/visualization/excel_evidence_graph.html (631KB)
- data/outputs/sample_20260519_excel_v1/visualization/neptune_graph_export.json
- data/outputs/sample_20260519_excel_v1/visualization/neptune_graph_nodes.jsonl
- data/outputs/sample_20260519_excel_v1/visualization/neptune_graph_edges.jsonl
- data/outputs/sample_20260519_excel_v1/visualization/graph_full_vis_data.json
- data/outputs/sample_20260519_excel_v1/visualization/graph_core_vis_data.json
- data/outputs/sample_20260519_excel_v1/visualization/excel_core_graph.mmd
- data/outputs/sample_20260519_excel_v1/visualization/excel_graph_visualization_report.md

#### Murata Outputs Status

- data/outputs/murata_semantic_v2/ — UNTOUCHED
- Neptune — NOT cleared, NOT loaded (read-only queries only)

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/export_excel_graph_html_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1/visualization --source neptune --layout force
```

#### Next Recommended Action

→ Superseded by X7 below.

---

### Stage X7: Excel Parsed Content Markdown Export for Human Verification

```text
Status: Done
Date: 2026-05-19
Decision: GO
```

#### Goal

Export all parsed Excel content as human-readable Markdown for manual verification against original workbooks.

#### Results

- Workbooks exported: 2
- Sheets exported: 29
- Table regions exported: 27
- Normalized rows exported: 1458
- Evidence chunks exported: 190
- Cell samples included: 4087
- Generated files: 37 (6 main + 2 workbook + 29 sheet files)
- Full markdown: 156,355 lines (2.4 MB)

#### Files Created

```text
src/hermes_bedrock_agent/v2/excel/excel_markdown_exporter.py
src/hermes_bedrock_agent/v2/excel/excel_markdown_reporter.py
src/hermes_bedrock_agent/v2/pipelines/export_excel_parsed_markdown.py
scripts/export_excel_parsed_markdown_v2.py

data/outputs/sample_20260519_excel_v1/markdown_export/excel_parsed_full.md
data/outputs/sample_20260519_excel_v1/markdown_export/excel_parsed_summary.md
data/outputs/sample_20260519_excel_v1/markdown_export/excel_parsed_by_sheet_index.md
data/outputs/sample_20260519_excel_v1/markdown_export/excel_parsed_quality_check.md
data/outputs/sample_20260519_excel_v1/markdown_export/markdown_export_report.md
data/outputs/sample_20260519_excel_v1/markdown_export/markdown_export_manifest.json
data/outputs/sample_20260519_excel_v1/markdown_export/workbooks/ (2 files)
data/outputs/sample_20260519_excel_v1/markdown_export/sheets/ (29 files)
```

#### Safety Checks

- Murata outputs: UNTOUCHED (36 files in murata_semantic_v2/)
- Neptune: NOT loaded, NOT cleared
- Graph files: UNTOUCHED
- V1 pipeline: UNTOUCHED

#### Known Limitations

- Very wide mapping sheets (150-191 columns) produce large row-detail blocks
- 2 sheets with 0 parsed rows (概要, フローチャート) — may contain only sparse text/charts
- 1 empty sheet (補足事項(DataSpider)) — appears intentionally blank
- Merged cells listed but not semantically resolved into header groups

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/ src/hermes_bedrock_agent/v2/pipelines/
PYTHONPATH=src python scripts/export_excel_parsed_markdown_v2.py --config configs/sample_20260519_excel_v1.yaml --run-id sample_20260519_excel_v1 --dataset sample_20260519 --input-dir data/outputs/sample_20260519_excel_v1 --output-dir data/outputs/sample_20260519_excel_v1/markdown_export --split-by-workbook --split-by-sheet --include-cell-samples --include-evidence-chunks --include-normalized-rows --include-table-regions --max-rows-per-table 0
```

#### Next Recommended Action

Decision: **GO** — Markdown export complete, ready for human verification.

After human review:
- If content verified → proceed to X8: Excel Graph QA / Retrieval Test
- If parser issues found → targeted parser fixes before proceeding

---

### Stage X7C: Excel Sheet Visual Object Extraction and Bedrock Image Analysis

**Status:** Done
**Date:** 2026-05-19

#### Objective

Extract visual objects (images, shapes, charts, flowcharts, diagrams, textboxes, connectors) from all Excel sheets. Analyze embedded images with Bedrock Claude Sonnet multimodal API. Generate Markdown report for human review.

#### Results

- **Visual objects extracted:** 124 (53 shapes, 38 textboxes, 24 connectors, 8 embedded images, 1 group)
- **Bedrock analyses performed:** 8 (6 successful high-confidence, 2 low-confidence)
- **Sheets with visual content:** 2 of 3 (概要: architecture diagram via textboxes; API呼出順序: 7 process flow screenshots)
- **フローチャート sheet:** NOT recovered (no drawing XML linkage found)
- **概要 sheet:** 16 visual objects extracted (DataSpider Servista, ANDPAD, SAP, REST adapter architecture diagram via shapes/textboxes)
- **API呼出順序 sheet:** 72 visual objects + 7 embedded PNG images with rich flowchart analysis
- **Flowchart steps detected (Bedrock):** ~49 total across 6 images
- **Diagram nodes detected:** ~37 total
- **Systems identified:** ANDPAD, 基幹システム (貴社システム), システム外
- **Raw media exported:** 9 files (7 PNG process flows 73-172KB, 1 tiny icon 890B, 1 SVG)

#### Key Findings

1. **概要 sheet architecture diagram** is reconstructable from textbox/shape/connector metadata:
   - SAP → CSV → DataSpider Servista (処理スクリプト) → REST アダプタ → API (REST) → ANDPAD(施工管理アプリ)
   - 開発スコープ範囲 annotation
2. **API呼出順序 sheet** contains 7 embedded screenshots showing complete ANDPAD integration flows:
   - 発注作成, 発注ステータス変更, 納品一覧, 納品データ編集, 請求一覧, 請求ステータス変更
   - Business process: Order → Delivery → Billing lifecycle
3. **フローチャート sheet** has no extractable visual objects — drawing content may be in Excel format not accessible via openpyxl
4. **Bedrock VLM quality** is excellent for screenshots of tabular data (conf 0.88-0.93) but returns 0.10 for placeholder icons

#### Files Created

```
src/hermes_bedrock_agent/v2/excel/excel_visual_schema.py
src/hermes_bedrock_agent/v2/excel/excel_visual_object_extractor.py
src/hermes_bedrock_agent/v2/excel/excel_sheet_image_exporter.py
src/hermes_bedrock_agent/v2/excel/excel_bedrock_vision_analyzer.py
src/hermes_bedrock_agent/v2/excel/excel_visual_markdown_exporter.py
src/hermes_bedrock_agent/v2/excel/excel_visual_reporter.py
src/hermes_bedrock_agent/v2/pipelines/excel_visual_parse_pipeline.py
scripts/excel_visual_parse_v2.py

data/outputs/sample_20260519_excel_v1/visual_parse/jsonl/visual_workbooks.jsonl
data/outputs/sample_20260519_excel_v1/visual_parse/jsonl/visual_sheets.jsonl
data/outputs/sample_20260519_excel_v1/visual_parse/jsonl/visual_objects.jsonl (124 records)
data/outputs/sample_20260519_excel_v1/visual_parse/jsonl/visual_analyses.jsonl (8 records)
data/outputs/sample_20260519_excel_v1/visual_parse/markdown/excel_visual_parse_full.md
data/outputs/sample_20260519_excel_v1/visual_parse/markdown/visual_parse_summary.md
data/outputs/sample_20260519_excel_v1/visual_parse/markdown/visual_parse_quality_check.md
data/outputs/sample_20260519_excel_v1/visual_parse/markdown/visual_evidence_design.md
data/outputs/sample_20260519_excel_v1/visual_parse/markdown/flowchart_visual_analysis.md
data/outputs/sample_20260519_excel_v1/visual_parse/markdown/overview_visual_analysis.md
data/outputs/sample_20260519_excel_v1/visual_parse/reports/excel_visual_parse_report.md
data/outputs/sample_20260519_excel_v1/visual_parse/raw_media/ (9 files)
```

#### Safety Checks

- Murata outputs: UNTOUCHED
- Neptune: NOT loaded, NOT cleared
- Graph files: UNTOUCHED
- V1 pipeline: UNTOUCHED

#### Known Limitations

- LibreOffice not installed — no sheet-level PNG composites
- PyMuPDF not installed — no PDF conversion
- SVG images not analyzable by Bedrock (1 SVG skipped)
- フローチャート sheet has no drawing XML linkage (content may require LibreOffice rendering)
- Connector source→target is positional, not semantic
- VML drawings parsed but may contain comment indicators rather than content
- image7 (172KB, largest) received truncated analysis (max_tokens hit)

#### Commands Run

```bash
python -m compileall src/hermes_bedrock_agent/v2/excel/excel_visual_schema.py src/hermes_bedrock_agent/v2/excel/excel_visual_object_extractor.py src/hermes_bedrock_agent/v2/excel/excel_sheet_image_exporter.py src/hermes_bedrock_agent/v2/excel/excel_bedrock_vision_analyzer.py src/hermes_bedrock_agent/v2/excel/excel_visual_markdown_exporter.py src/hermes_bedrock_agent/v2/excel/excel_visual_reporter.py src/hermes_bedrock_agent/v2/pipelines/excel_visual_parse_pipeline.py

PYTHONPATH=src python scripts/excel_visual_parse_v2.py --config configs/sample_20260519_excel_v1.yaml --s3-uri "s3://s3-hulftchina-rd/サンプル20260519/" --run-id sample_20260519_excel_v1 --dataset sample_20260519 --output-dir data/outputs/sample_20260519_excel_v1/visual_parse --bedrock-enabled --max-images 50 -v
```

#### Next Recommended Action

Decision: **GO** — Visual parse complete. Significant business-process content extracted.

Recommended next steps:
1. **Human review** of `visual_parse/markdown/excel_visual_parse_full.md` against original Excel
2. **X7D:** Convert verified visual analysis → EvidenceChunks (flowchart_steps → BusinessStep candidates)
3. **X8:** Graph extraction using combined textual + visual evidence
