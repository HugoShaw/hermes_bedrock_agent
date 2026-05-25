# Murata Retrieval Quality Issues Diagnosis

## Diagnosis Date

2026-05-15

## Baseline Reference

- run_id: `murata_live_v1`
- LanceDB collection: `murata_e2e_murata_live_v1`
- Neptune: 3034 nodes + 5136 edges
- Source files: ~263 files from `s3://s3-hulftchina-rd/Murata/`

---

## Root Cause Analysis

### 1. Chunk Quality Issues

#### 1.1 Code/SQL Chunks Dominate Vector Store

- Murata dataset is heavily code-oriented (Java, SQL, DDL, Excel)
- Code chunks enter the vector store at 2000 chars per chunk alongside text chunks at 1500 chars
- When user asks a business question (e.g. "仕訳基礎のデータフローは？"), the embedding search retrieves raw code/SQL chunks that are semantically close to business terms but not human-readable answers
- **Impact**: Top-K results filled with irrelevant code snippets instead of business descriptions

#### 1.2 No Chunk Purpose Classification

- All chunks (text, code, table, visual) enter the vector store equally
- No way to distinguish "answerable text" from "supporting evidence"
- No summary chunks exist — if a 200-line Java file has one comment about a business process, only that comment is relevant but the entire code chunk gets returned
- **Impact**: Low signal-to-noise ratio in retrieval results

#### 1.3 No Summary Chunks

- A Java class implementing "付款申請" (Payment Request) has no summary chunk explaining what it does in business terms
- SQL DDL files define tables but there's no summary of "what business entity does this table store"
- Module-level or file-level summaries don't exist
- **Impact**: User gets raw code instead of business-level explanation

#### 1.4 Fragmented Section Chunking

- Section-aware chunking splits at headings but doesn't consolidate small adjacent sections
- A document section with 100 chars gets its own chunk (above min 50) but lacks context
- **Impact**: Small isolated chunks match queries but carry insufficient context for answering

### 2. Graph Extraction Issues

#### 2.1 Schema Mismatch Between Two Pipelines

There are TWO graph extraction systems:

1. **`graph/extractor.py`** (Phase 7+ pipeline): uses `EntityType` enum with 18 types and `RelationType` with 19 types
2. **`s3_graph_etl/`** pipeline: uses a different schema with 10 node labels and 11 edge types

These schemas overlap but don't align:
- `graph/extractor.py`: `system, module, table, column, api, process, document, person, organization, role, term, concept, file, service, database, screen, field, event, rule`
- `s3_graph_etl/schema.py`: `Document, Section, Table, Column, API, Process, Rule, Service, Module, Entity`

**Impact**: Inconsistent entity types in the same graph, duplicated entities with different labels

#### 2.2 Too Many Generic Relations

- `related_to` is a catch-all that carries no semantic value for retrieval
- `configs/graph_schema.yaml` allows 19 relation types, but the LLM prompt encourages broad extraction
- `ingestion.yaml` allows up to 50 entities and 100 relations per chunk — far too loose
- `graph/extractor.py` limits to 8 entities / 12 relations per chunk, but the s3_graph_etl pipeline has no such limit
- **Impact**: Graph is noisy with vague relations, path-based retrieval returns noise

#### 2.3 Code Entities Pollute Business Layer

- Variables, class names, internal method names get extracted as entities
- `_is_noise_entity()` filter exists but is applied only in `graph/extractor.py`, not in `s3_graph_etl`
- Japanese/CJK entity names need special handling not covered by noise filter
- **Impact**: Graph has thousands of low-value code entities that dilute business entity search

### 3. Retrieval Issues

#### 3.1 No Chunk Purpose Filtering at Retrieval Time

- `VectorStoreTextRetriever` has no filter for chunk purpose/quality
- All chunks are equally eligible regardless of whether they can answer a business question
- **Impact**: Code chunks score high on embedding similarity but cannot answer questions

#### 3.2 Graph → Text Bridge is Weak

- Graph evidence carries `source_chunk_ids` but ContextBuilder only resolves 5 chunks max
- Graph evidence `content` field is just "[entity_type] name: description" — very short
- If the graph path is correct but the entity description is empty, context is useless
- **Impact**: Graph retrieval identifies correct entities but cannot provide enough context

#### 3.3 Fusion Lacks Quality Signal

- RRF treats all evidence equally by rank position
- No signal for "this chunk is a summary" vs "this chunk is raw SQL"
- No boost for chunks that directly answer the question type
- **Impact**: High-quality text evidence gets diluted by numerous low-quality code matches

### 4. Answer Generation Issues

#### 4.1 Context Window Pollution

- max_text_chars = 8000, max_graph_chars = 4000 (12KB context)
- If top-10 text evidence are code chunks, the LLM gets 8KB of code and zero business text
- **Impact**: LLM cannot generate a useful answer from irrelevant context

#### 4.2 No Query-Type Routing

- Same retrieval strategy for all question types:
  - Business process questions ("仕訳基礎の流れは？")
  - Technical lookup ("PaymentHeader テーブルのカラムは？")
  - Cross-cutting questions ("どのモジュールが対帳単を使っている？")
- Each needs different retrieval emphasis (summary vs schema vs graph)
- **Impact**: One-size-fits-all retrieval fails for diverse question types

### 5. Data Layer Issues

#### 5.1 No Metadata Enrichment

- Entities lack Japanese/Chinese display names and descriptions
- Entity properties are minimal (name, canonical_name, entity_type)
- No module-level grouping or hierarchy metadata
- **Impact**: Graph queries return entities with cryptic code-names, not business-readable labels

#### 5.2 No Quality Tiers

- All 3034 nodes treated equally in Neptune
- High-confidence business entities are mixed with low-confidence code entities
- No `tier` or `layer` property to distinguish business vs implementation vs data
- **Impact**: Cannot filter graph queries by quality or relevance tier

---

## Summary Priority Matrix

| Issue | Severity | Fix Difficulty | Phase |
|-------|----------|---------------|-------|
| No chunk purpose classification | Critical | Medium | R2 (chunking) |
| No summary chunks | Critical | Medium | R2 (chunking) |
| Code chunks pollute vector store | Critical | Easy (filter) | R3 (embedding) |
| Schema mismatch between pipelines | High | Medium | R2 (extraction) |
| Generic relations (related_to) | High | Easy (schema) | R2 (extraction) |
| No query-type routing | High | Medium | R4 (retrieval) |
| Graph→text bridge weak | Medium | Medium | R4 (retrieval) |
| Fusion lacks quality signal | Medium | Medium | R4 (retrieval) |
| No metadata enrichment | Medium | Low (opt-in) | R5 (optional) |
| Context window pollution | Medium | Easy (filter) | R4 (generation) |
