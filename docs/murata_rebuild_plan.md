# Murata GraphRAG Rebuild Plan

## Rebuild ID

- run_id: `murata_rebuild_v1`
- LanceDB collection: `murata_e2e_murata_rebuild_v1`
- Dataset: `murata`
- S3 source: `s3://s3-hulftchina-rd/Murata/`

## Rebuild Philosophy

1. **Small sample first** — validate each stage on ~10-20 files before full rebuild
2. **Stage-by-stage validation** — each stage has explicit quality gates
3. **Summary-first embedding** — summary chunks are primary, raw chunks are evidence
4. **Three-layer graph** — Business / Implementation / Data layer separation
5. **Chunk purpose classification** — filter what enters vector store and graph
6. **No default enrichment** — enrichment is opt-in, not part of rebuild critical path

---

## Rebuild Phases

### R1 — Sample Selection

Select a representative sample covering:
- 2-3 Business documents (Word/MD with process descriptions)
- 2-3 Code files (Java with business logic)
- 2-3 SQL/DDL files (table definitions)
- 1-2 Visual documents (diagrams, flowcharts)
- 1-2 Config/property files

Goal: ~10-15 files spanning all Murata modules (仕訳基礎, 対帳単, 付款申請, システム管理)

Quality gate: Files selected from each module, file_list.json documented

### R2 — Parse + Chunk + Classify

1. Parse sample files using existing parsers
2. Chunk with improved configuration:
   - Reduce code_chunk_size to 1500 (align with text)
   - Increase min_chunk_size to 100 (eliminate fragments)
   - Enable section-aware chunking for all text docs
3. **NEW: Chunk purpose classification** — assign each chunk a `purpose`:
   - `answerable_text`: natural language that can answer questions
   - `code_evidence`: code that supports claims (not primary answer material)
   - `schema_evidence`: DDL/table structure definitions
   - `visual_evidence`: descriptions from VLM
   - `summary`: LLM-generated summaries (new)
   - `config_evidence`: configuration/property definitions
   - `low_value`: noise (auto-generated, boilerplate, logs)
4. **NEW: Summary chunk generation** — for each code/SQL file, generate:
   - `code_summary_chunk`: "This file implements X business process..."
   - `table_summary_chunk`: "This table stores Y for Z business purpose..."
   - `module_summary_chunk`: "This module handles..."

Quality gate:
- Each sample file has at least 1 summary chunk
- code_evidence chunks outnumber answerable_text by no more than 3:1
- zero low_value chunks enter later stages

### R3 — Embedding + LanceDB Write

1. Embed and store to `murata_e2e_murata_rebuild_v1`
2. **Embedding input filter** (by chunk purpose):
   - Always embed: `summary`, `answerable_text`, `schema_evidence`
   - Conditionally embed: `visual_evidence` (only with description)
   - Never embed: `low_value`, `data_sample`
   - Rarely embed: `code_evidence` (only if summary unavailable)
3. Store `chunk_purpose` as metadata in LanceDB for retrieval filtering

Quality gate:
- summary chunks represent >= 20% of embedded items
- Total embedded chunks < 50% of total produced chunks (filtering works)
- Spot-check: top-5 results for "仕訳基礎とは？" should include summary/answerable chunks

### R4 — Graph Extraction (Sample)

1. Use unified schema (resolve the two-pipeline mismatch)
2. **Three graph layers**:
   - **Business Semantic**: BusinessProcess, BusinessObject, BusinessRule, Screen, Module, Document
   - **System Implementation**: Service, API, Class, Method, SQL, File
   - **Data/Evidence**: Table, Column, Chunk, SourceDocument
3. **Restricted relation types** (10 allowed):
   - `contains`, `references`, `reads_from`, `writes_to`, `calls`
   - `depends_on`, `belongs_to`, `implements`, `supports`, `related_to`
4. Extract from: summary chunks + answerable_text + schema_evidence
5. Skip: low_value, data_sample, raw code_evidence (use code_summary instead)
6. Max 8 entities / 12 relations per chunk (align with graph/extractor.py)
7. Add `layer` property to each entity: `business` | `implementation` | `data`

Quality gate:
- `related_to` relations < 15% of total
- Each entity has non-empty `description`
- Entity names are meaningful (not code variables)
- All entities have `layer` property

### R5 — Neptune Load (Sample)

1. Load to Neptune using `murata_rebuild_v1` run_id
2. Validate with sample queries:
   - "仕訳基礎に関連するテーブルは？" → should find Table entities via graph
   - "付款申請のビジネスプロセスは？" → should find BusinessProcess entities
3. Verify three-layer separation works in traversal

Quality gate:
- Graph has < 50% the nodes of baseline (quality over quantity)
- Business layer entities have Japanese/English descriptions
- Path queries return meaningful 2-3 hop paths

### R6 — Retrieval + Answer Validation

1. Run sample QA questions against new collection + new graph
2. Compare answer quality vs baseline
3. Implement query-type routing:
   - Business questions → summary chunks + graph paths
   - Technical lookup → schema_evidence + code_evidence
   - Cross-cutting → graph traversal + summary chunks
4. Tune fusion weights based on sample results

Quality gate:
- Answers cite summary chunks (not raw code)
- Graph evidence adds value (entity descriptions appear in context)
- 3/5 test questions produce better answers than baseline

### R7 — Full Rebuild (if R6 passes)

1. Run full pipeline on all ~263 files
2. Generate summaries for all code/SQL files
3. Full embedding to new LanceDB collection
4. Full graph extraction and Neptune load
5. Final QA validation

Quality gate:
- All R6 quality gates still pass at scale
- No regression on sample questions
- New questions from each module answerable

---

## Graph Layer Design

### Business Semantic Layer

```
BusinessProcess → Screen (supports)
BusinessProcess → BusinessObject (references)
BusinessProcess → BusinessRule (implements)
Module → BusinessProcess (contains)
Document → BusinessProcess (describes)
```

### System Implementation Layer

```
Service → API (contains)
API → Method (contains)
Class → Method (contains)
Method → SQL (calls)
File → Class (contains)
```

### Data/Evidence Layer

```
Table → Column (contains)
Table → SQL (referenced_by)
SourceDocument → Chunk (contains)
Chunk → Entity (evidence_for)
```

---

## Chunk Purpose Classification Rules

| Source Type | Content Pattern | Purpose |
|-------------|----------------|---------|
| .md / .docx | Business narrative | answerable_text |
| .md / .docx | Heading only | low_value |
| .java / .py | Full class/method | code_evidence |
| .java / .py | LLM-generated summary | summary |
| .sql / .ddl | CREATE TABLE | schema_evidence |
| .sql / .ddl | LLM-generated summary | summary |
| .xlsx / .csv | Data rows | data_sample |
| .png / .jpg | VLM description | visual_evidence |
| .properties | Key=value config | config_evidence |
| any | < 100 chars | low_value |
| any | Boilerplate/license | low_value |

---

## Required Code Changes (Planned for R2+)

### New Components (to create)

1. `src/.../chunking/purpose_classifier.py` — classify chunk purpose
2. `src/.../chunking/summary_generator.py` — LLM summary chunk generation
3. `configs/murata_rebuild_v1.yaml` — rebuild-specific configuration
4. `scripts/run_rebuild_sample.py` — sample rebuild runner

### Existing Components (to modify in R2+)

1. `schemas/chunk.py` — add `purpose: ChunkPurpose` field
2. `embedding/embedder.py` — add purpose-based filter
3. `graph/extractor.py` — add `layer` property to entities
4. `retrieval/text_retriever.py` — add purpose filter to search
5. `retrieval/fusion.py` — add quality-weighted scoring

### NOT Modified in R0

All code changes are planned only. R0 produces this plan and config draft.

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Summary generation costs (LLM calls) | Budget ~50 summary calls for sample, monitor cost |
| Chunk purpose classifier accuracy | Start with rule-based, iterate with LLM assist |
| Schema change breaks existing tests | New run_id isolates from baseline, tests use mock |
| Neptune graph becomes too sparse | Set min summary+answerable chunks per module |
| Timeline exceeds expectation | Each phase is independently valuable, can stop at R6 |

---

## Next Step

Proceed to R1: Sample Selection (after R0 review approval).
