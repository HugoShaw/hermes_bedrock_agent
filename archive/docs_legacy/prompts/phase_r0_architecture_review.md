# Phase R0 — Architecture Review and Rebuild Plan

## Objective

Review the current Murata GraphRAG architecture and create a rebuild plan.

The current QA quality is poor. Do not fix the QA terminal directly. Do not run a rebuild yet.

This phase is analysis and planning only.

## Context

Baseline:

- run_id: `murata_live_v1`
- LanceDB collection: `murata_e2e_murata_live_v1`
- dataset: `murata`
- S3 source: `s3://s3-hulftchina-rd/Murata/`

New rebuild target:

- run_id: `murata_rebuild_v1`
- LanceDB collection: `murata_e2e_murata_rebuild_v1`

## Allowed Actions

- Read source code.
- Read existing docs.
- Read existing reports.
- Analyze current architecture.
- Create planning documents.
- Create config draft.

## Forbidden Actions

- Do not access AWS.
- Do not call Bedrock.
- Do not query Neptune.
- Do not write LanceDB.
- Do not write Neptune.
- Do not delete any data.
- Do not run the full pipeline.
- Do not modify core code.

## Review Current Architecture

Analyze:

1. scan
2. parse / VLM
3. chunking
4. embedding / LanceDB
5. graph extraction
6. fast normalization / integrity
7. Neptune load
8. retrieval / fusion / answer
9. visualization
10. qa_terminal

## Diagnose Quality Issues

Analyze possible causes of poor QA quality:

- chunk too fragmented
- code / SQL raw chunks not suitable for business QA
- missing summary chunks
- low-value chunks polluting vector store
- graph extraction too broad or too fine-grained
- relation types too generic
- too many `custom` / `related_to` relations
- mixed graph layers
- weak fusion or reranking
- noisy context
- answer prompt not strict enough about evidence

## New Architecture Proposal

Design a rebuild architecture with:

1. small sample first
2. stage-by-stage validation
3. new run_id
4. new LanceDB collection
5. Neptune sample load
6. no default enrichment
7. summary chunks
8. chunk purpose classification

## Graph Layers

Design three graph layers:

### Business Semantic Layer

- BusinessProcess
- BusinessObject
- BusinessRule
- Screen
- Module
- Document

### System Implementation Layer

- Service
- API
- Class
- Method
- SQL
- File

### Data / Evidence Layer

- Table
- Column
- Chunk
- SourceDocument
- Evidence

## Chunk Purpose

Design chunk purpose values:

- answerable_text
- code_evidence
- schema_evidence
- visual_evidence
- data_sample
- config_evidence
- low_value
- summary

## Summary Chunks

Design summary chunk types:

- code_summary_chunk
- table_summary_chunk
- module_summary_chunk
- business_summary_chunk
- visual_summary_chunk

## Embedding Input Strategy

Design rules for what enters the vector store:

- summary chunks first
- answerable_text
- schema_evidence
- selected visual_evidence
- exclude data_sample by default
- exclude low_value by default
- avoid raw code chunks as primary answer evidence unless summarized

## Graph Extraction Input Strategy

Design rules for graph extraction input:

- summary chunks
- schema_evidence
- answerable_text
- code_summary
- selected code_evidence
- exclude data_sample
- exclude low_value

## Relation Type Strategy

Restrict relation types to a controlled set:

- contains
- references
- reads_from
- writes_to
- calls
- depends_on
- belongs_to
- implements
- supports
- related_to

Minimize `custom`.

## Required Outputs

Create:

1. `docs/murata_rebuild_plan.md`
2. `docs/murata_retrieval_quality_issues.md`
3. `configs/murata_rebuild_v1.yaml`

## Report

After completing R0, output a report with:

1. Current architecture summary
2. Problem diagnosis
3. Proposed rebuild architecture
4. Phase list
5. Quality gates
6. Suggested sample file categories
7. Required code changes
8. R1 recommendation

## State Update

Update `task_state.md`:

- Current Phase Status: completed
- Next Phase: R1
- Next Phase Prompt: `docs/prompts/phase_r1_sample_selection.md`

Then stop.
