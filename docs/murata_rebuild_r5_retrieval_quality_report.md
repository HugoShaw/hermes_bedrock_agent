# Phase R5 — Retrieval Quality Report

## Summary

All retrieval quality gates passed. Vector retrieval achieves 100% top-5 and top-10 success rates across all 5 target questions with zero irrelevant results.

## Overall Metrics

| Metric | Value |
|--------|-------|
| Total Queries | 10 |
| Top-5 Success Rate | 100% |
| Top-10 Success Rate (≥3 relevant) | 100% |
| Avg Relevant Items in Top-10 | 10.0 |
| Summary vs Raw Ratio | 31:69 |
| Total Irrelevant Results | 0 |

## Per-Question Results

### Q1 — 应付管理业务流程

| Metric | Value |
|--------|-------|
| Highly Relevant (top-10) | 18 |
| Partially Relevant | 2 |
| Irrelevant | 0 |
| Summary Hits | 9 |
| Raw Hits | 11 |
| Top-5 Has Highly Relevant | ✅ |
| Top-10 Has ≥3 Relevant | ✅ |

### Q2 — JOURNAL_BASE 表作用

| Metric | Value |
|--------|-------|
| Highly Relevant (top-10) | 13 |
| Partially Relevant | 7 |
| Irrelevant | 0 |
| Summary Hits | 4 |
| Raw Hits | 16 |
| JOURNAL_BASE in Top-5 | ✅ |

### Q3 — 三表关联

| Metric | Value |
|--------|-------|
| Highly Relevant (top-10) | 16 |
| Partially Relevant | 4 |
| Irrelevant | 0 |
| Summary Hits | 3 |
| Raw Hits | 17 |
| All 3 Tables Found | ✅ (SUN_REQUEST, JOURNAL_BASE, RECEIVING_JOURNAL) |

### Q4 — Semantic Map

| Metric | Value |
|--------|-------|
| Highly Relevant (top-10) | 20 |
| Partially Relevant | 0 |
| Irrelevant | 0 |
| Summary Hits | 11 |
| Raw Hits | 9 |
| semantic_map_summary/process in Top-5 | ✅ |

### Q5 — OA 迁移

| Metric | Value |
|--------|-------|
| Highly Relevant (top-10) | 15 |
| Partially Relevant | 5 |
| Irrelevant | 0 |
| Summary Hits | 4 |
| Raw Hits | 16 |
| oa_migration_summary in Top-5 | ✅ |

## Quality Gate Results

| Gate | Criterion | Result |
|------|-----------|--------|
| 6 | Each Q has ≥1 highly_relevant in top-5 | ✅ PASS |
| 7 | Each Q has ≥3 relevant in top-10 | ✅ PASS |
| 8 | Q2 retrieves JOURNAL_BASE in top-5 | ✅ PASS |
| 9 | Q3 retrieves all 3 tables in top-10 | ✅ PASS |
| 10 | Q4 retrieves semantic_map/process in top-5 | ✅ PASS |
| 11 | Q5 retrieves oa_migration in top-5 | ✅ PASS |
| 12 | R4 summaries appear in retrieval | ✅ PASS (31 hits) |

**Overall Quality Gate: ✅ ALL PASSED**

## Key Observations

1. **Zero irrelevant results** — The targeted chunking (R3) + summarization (R4) approach produces a highly focused embedding corpus with no noise.
2. **Summary chunks work well** — 31 of 100 total hits are R4 summaries, showing they add retrieval value especially for semantic/process questions (Q4 has 11 summary hits).
3. **Q4 dominates summary usage** — Expected, since Q4 (Semantic Map) requires holistic process understanding that summaries provide.
4. **Q3 relies on raw chunks** — Expected, since Q3 asks about specific field-level join logic best answered by raw SQL/code evidence.
5. **Balance is good** — The 31:69 summary:raw ratio shows both tiers contribute without one drowning the other.

## Generated At

2026-05-15T07:45:55.074713
