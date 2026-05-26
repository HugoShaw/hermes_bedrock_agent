# Phase R4 — Embedding Input Recommendation

**Date**: 2026-05-15 07:19  
**Run ID**: murata_rebuild_v1  
**Phase**: R4 → R5 Transition Recommendation

---

## Summary

R4 produced 13 high-quality summary chunks. Combined with 38 R3 chunks (should_embed=true), the R5 embedding input set contains **51 candidates** total.

---

## Embedding Input Composition

| Source | Count | Description |
|--------|-------|-------------|
| R3 raw chunks (should_embed=true) | 38 | Original code/schema/process/config chunks |
| R4 summary chunks | 13 | LLM-generated structured summaries |
| **Total** | **51** | Combined embedding input set |

---

## Replacement / Supplement Strategy

R4 summaries **supplement** (not replace) their parent R3 chunks. Both are recommended for embedding because:

1. **R3 raw chunks** provide exact code/SQL/config for precise keyword retrieval
2. **R4 summaries** provide semantic descriptions for semantic similarity retrieval
3. Together they enable **hybrid retrieval** (keyword + semantic)

### Chunks with R4 supplements

4 R3 chunks have corresponding R4 summary supplements:

| R3 Chunk | R4 Summary | Summary Type |
|----------|-----------|--------------|
| chunk_r3_013 | summary_r4_001 | code_summary |
| chunk_r3_014 | summary_r4_002 | code_summary |
| chunk_r3_015 | summary_r4_003 | code_summary |
| chunk_r3_017 | summary_r4_004 | code_summary |
| chunk_r3_018 | summary_r4_005 | code_summary |
| chunk_r3_031 | summary_r4_006 | code_summary |
| chunk_r3_032 | summary_r4_007 | code_summary |
| chunk_r3_036 | summary_r4_008 | process_summary |
| chunk_r3_037 | summary_r4_009 | schema_summary |
| chunk_r3_053 | summary_r4_010 | process_summary |
| chunk_r3_055 | summary_r4_011 | schema_summary |
| chunk_r3_053 | summary_r4_012 | semantic_map_summary |
| chunk_r3_037 | summary_r4_012 | semantic_map_summary |
| chunk_r3_015 | summary_r4_013 | oa_migration_summary |
| chunk_r3_031 | summary_r4_013 | oa_migration_summary |
| chunk_r3_037 | summary_r4_013 | oa_migration_summary |

---

## Question Coverage in Embedding Set

| Question | R3 Chunks | R4 Summaries | Total |
|----------|:---------:|:------------:|:-----:|
| Q1 | 26 | 12 | 38 |
| Q2 | 10 | 4 | 14 |
| Q3 | 12 | 2 | 14 |
| Q4 | 26 | 11 | 37 |
| Q5 | 19 | 5 | 24 |

---

## R5 Embedding Recommendations

### Model
- **Recommended**: amazon.titan-embed-text-v2:0 (configured in .env as BEDROCK_EMBEDDING_MODEL_ID)
- **Dimension**: 1024 (default for Titan V2)
- **Max tokens**: 8192 per chunk (all candidates well within limit)

### LanceDB Configuration
- **Collection**: murata_e2e_murata_rebuild_v1
- **run_id**: murata_rebuild_v1
- **Total vectors**: ~51 (38 R3 + 13 R4)

### Embedding Priority Order
1. R4 summary chunks (highest retrieval value per token)
2. R3 code_evidence chunks (exact code for Q2, Q3 precision)
3. R3 schema_evidence chunks (DDL structures)
4. R3 process/config evidence chunks

### Metadata to Index
Each embedding should carry:
- chunk_id
- source (r3_chunk or r4_summary)
- related_target_questions
- summary_type (for R4 chunks)
- key_tables
- source_file_name

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| 51 vectors may be too few for comprehensive retrieval | Medium | Monitor recall in R6 QA; add more chunks if needed |
| Q3 coverage minimal (2 R4 summaries) | Low | R3 raw SQL chunks cover join-field details directly |
| Summary hallucination | Low | All summaries generated at temp=0.1 with strict factual grounding |

---

## Conclusion

✅ **Proceed to R5 with the 51-candidate embedding set.**

The embedding_input_candidates_r4.jsonl file is ready as input for R5.
No manual curation needed — all candidates are pre-validated.
