# R6 Next Step Recommendation

## R6 Status: COMPLETE ✅

Phase R6 graph extraction completed successfully with all quality gates passed.

## Readiness for R7

### What R6 Produced
- 859 raw entities (383 unique by name+type)
- 1,044 clean relations (0 suspicious, 0 custom types)
- 181 evidence records
- 140 entity dedup candidate groups
- Full Q1-Q5 coverage
- Q4 semantic map with 8-node continuous path

### What R7 Should Do

**R7 Phase: Graph Normalization & Integrity**

1. **Entity Dedup Resolution** (primary)
   - Merge 140 dedup groups → reduce 859 raw to ~383 canonical entities
   - Handle ambiguous cases (STATUS column in different tables)
   - Preserve all source_chunk_ids for traceability

2. **Relation Normalization**
   - Update all relation source/target to canonical entity names
   - Remove exact-duplicate relations (same source+target+type)
   - Validate bidirectional consistency

3. **Q4 Semantic Map Refinement**
   - Consolidate 286 Q4 nodes → ~30-50 core process nodes
   - Establish canonical AP flow path
   - Layer assignment (business/system/data)

4. **Integrity Checks**
   - Orphan entity detection (entities with no relations)
   - Dangling relation detection (relations referencing non-existent entities)
   - Schema validation (all entity_types and relation_types in allowed sets)
   - Confidence threshold enforcement

5. **Neptune Schema Preparation**
   - Generate node labels and property maps
   - Generate edge types and property maps
   - Validate against Neptune constraints (no arrays, PascalCase labels)

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Over-aggressive dedup | Loses distinct entities | Qualify ambiguous names with parent context |
| Loss of Q4 path during normalization | Breaks semantic map | Preserve path-critical edges in protected set |
| Neptune schema incompatibility | Blocks R8 loading | Validate against Neptune constraints in R7 |
| Evidence loss during merge | Reduces QA quality | Union all evidence from duplicate entities |

## Cost Projection

- R7 (normalization): Minimal API cost (mostly local processing), ~$0 Bedrock
- R8 (Neptune loading): ~$0 (Neptune write only)
- R9 (QA validation): ~$1-2 (answer generation for Q1-Q5)

## Recommendation

**Proceed to R7: Graph Normalization & Integrity.**

The R6 raw graph is rich (859E/1044R) with clean extraction quality (0 suspicious, 0 custom). The main R7 task is dedup resolution and integrity validation before Neptune loading in R8.
