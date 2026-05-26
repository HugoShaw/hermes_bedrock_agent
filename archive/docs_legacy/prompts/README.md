# Phase Prompts

This directory contains phase-level prompts for Hermes Agent.

Hermes must always read:

1. `../../.hermes.md`
2. `../task_state.md`
3. the current phase prompt file

before executing any task.

## Phase List

| Phase | File | Purpose |
|---|---|---|
| R0 | `phase_r0_architecture_review.md` | Architecture review and rebuild plan |
| R1 | `phase_r1_sample_selection.md` | Select small high-value sample files |
| R2 | `phase_r2_parse_quality_check.md` | Parse and VLM quality check |
| R3 | `phase_r3_chunking_quality.md` | Chunking and chunk purpose classification |
| R4 | `phase_r4_summary_chunks.md` | Generate summary chunks |
| R5 | `phase_r5_embedding_lancedb.md` | Embedding and LanceDB retrieval check |
| R6 | `phase_r6_graph_extraction.md` | Graph extraction sample |
| R7 | `phase_r7_normalization_integrity.md` | Fast normalization and integrity check |
| R8 | `phase_r8_neptune_sample_load.md` | Neptune dry-run and sample load |
| R9 | `phase_r9_qa_validation.md` | QA terminal validation |
| R10 | `phase_r10_expand_scope.md` | Expand from sample to larger scope |

## Rule

One phase at a time.

After completing each phase, update `task_state.md` and stop.
