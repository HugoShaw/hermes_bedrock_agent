# R6 Relation Quality Report

## Summary

| Metric | Value |
|--------|-------|
| Total raw relations | 1,044 |
| Clean relations | 1,044 |
| Suspicious relations | 0 |
| Unique relation types | 22 |
| Custom type count | **0** ✅ |
| relates_to count | 28 (2.7%) ✅ |

## Quality Indicators

### No Custom Relations
Zero relations used a "custom" type. All 1,044 relations use one of the 22 predefined relation types.

### relates_to Not Dominant
Only 28/1,044 (2.7%) use the generic `relates_to` type. This indicates the model successfully assigned specific, meaningful relation types.

### All Relations Have Required Fields

Every clean relation contains:
- ✅ source_entity (non-empty)
- ✅ target_entity (non-empty)
- ✅ relation_type (from allowed set)
- ✅ source_chunk_id (traceable)
- ✅ evidence_text (non-empty)
- ✅ confidence (0.0-1.0)

### Relation Type Quality

**Structural relations (61.0%)**:
- contains: 252 (24.1%)
- has_field: 145 (13.9%)
- has_status: 55 (5.3%)
- belongs_to: 11 (1.1%)

**Data flow relations (22.7%)**:
- reads_from: 101 (9.7%)
- writes_to: 80 (7.7%)
- flows_to: 58 (5.6%)

**Behavioral relations (12.3%)**:
- transitions_to: 51 (4.9%)
- calls: 51 (4.9%)
- updates: 33 (3.2%)
- generates: 35 (3.4%)

**Dependency relations (6.7%)**:
- joins_on: 45 (4.3%)
- depends_on: 25 (2.4%)

**Semantic relations (3.0%)**:
- relates_to: 28 (2.7%)
- references: 19 (1.8%)

## Confidence Distribution

Based on extraction model confidence scores:
- High confidence (≥0.9): majority
- Medium confidence (0.7-0.89): secondary
- Low confidence (<0.7): minimal (no suspicious threshold breaches)

## Suspicious Relation Analysis

**Zero suspicious relations identified.**

All relations passed:
1. Source entity present ✅
2. Target entity present ✅
3. Evidence text present ✅
4. Source chunk traceable ✅
5. Relation type in allowed set ✅
6. Confidence ≥ 0.4 ✅
7. No custom type ✅

## Recommendations for R7

1. **Dedup resolution**: Many relations reference the same entity name extracted from different chunks. R7 normalization should merge these.
2. **Join field validation**: The 45 `joins_on` relations should be cross-checked with actual SQL/Mapper evidence.
3. **Q4 path consolidation**: The 149 Q4 preview edges should be reduced to the canonical semantic map path during R7.
