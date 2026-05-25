# R6 Entity Dedup Candidates Report

## Summary

| Metric | Value |
|--------|-------|
| Raw entities | 859 |
| Unique (name+type) | 383 |
| Dedup candidate groups | 140 |
| Removable duplicates | 476 |
| Dedup ratio | 55.4% |

## Top Dedup Candidates

These entities appear most frequently across different source chunks:

| Entity | Type | Occurrences | Source Chunks |
|--------|------|-------------|---------------|
| JOURNAL_BASE | Table | 21 | 42 |
| RECEIVING_LIST | Table | 19 | 38 |
| RECEIVING_JOURNAL | Table | 19 | 38 |
| PAYMENT_REQ | Table | 18 | 36 |
| SUN_REQUEST | Table | 16 | 32 |
| PAYMENT_RECEIVING | Table | 15 | 30 |
| PaymentReqAction | Action | 13 | 26 |
| OTHER_SYSTEM_NO | Column | 13 | 26 |
| LIST_TYPE | Column | 12 | 24 |
| VENDOR_CD | Column | 11 | 22 |
| PAY_NO | Column | 11 | 22 |
| BILL_NO | Column | 11 | 22 |
| savePaymentReq | Method | 10 | 20 |
| JournalBaseAction | Action | 10 | 20 |
| STATUS | Column | 10 | 20 |

## Dedup Strategy for R7

### Merge Rules

1. **Same name + same type** → merge into single canonical entity
2. **Keep richest description** (longest or most informative)
3. **Union all source_chunk_ids** for traceability
4. **Max confidence** among duplicates
5. **Union all related_target_questions**

### Expected Post-Dedup Counts

- Entities: 859 → ~383 (55% reduction)
- Relations stay at 1,044 (with source/target normalized to canonical names)
- Evidence stays at 181

### Dedup by Entity Type

| Type | Groups | Avg Occurrences |
|------|--------|-----------------|
| Table | ~25 | 8.2x |
| Column | ~40 | 4.5x |
| Method | ~20 | 3.8x |
| Action | ~10 | 5.2x |
| Service | ~8 | 4.0x |
| BusinessStep | ~15 | 2.8x |
| Other | ~22 | 2.3x |

## Risks

1. **Ambiguous names**: `STATUS` column appears in multiple tables - R7 must qualify with parent table
2. **Method overloading**: Same method name in different classes (e.g., `validate`) - needs class context
3. **Partial names**: Some entities extracted as abbreviations vs full names

## Recommendation

R7 should implement:
1. Exact name+type merge (safe, automatic)
2. Parent-qualified Column dedup (STATUS in TABLE_A vs TABLE_B → distinct)
3. Human review for ambiguous cases (flagged, not auto-merged)
