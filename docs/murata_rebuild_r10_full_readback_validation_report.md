# R10 Full Read-Back Validation Report

## Node Read-Back

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Total rebuild nodes | 381 | 381 | ✅ |
| Node properties accessible | YES | YES | ✅ |
| entity_id present | 381 | 381 | ✅ |
| run_id=murata_rebuild_v1 | 381 | 381 | ✅ |
| dataset=murata | 381 | 381 | ✅ |

## Edge Read-Back

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Total rebuild edges | 703 | 703 | ✅ |
| Edge properties accessible | YES | YES | ✅ |
| relation_id present | 703 | 703 | ✅ |
| run_id on edges | 703 | 703 | ✅ |
| Distinct relation_ids | 703 | 703 | ✅ |

## Label Distribution (Top 10)

| Label | Count |
|-------|-------|
| Column | 66 |
| BusinessStep | 40 |
| Status | 39 |
| EnumValue | 29 |
| Method | 29 |
| Field | 28 |
| Class | 23 |
| BusinessProcess | 19 |
| Module | 16 |
| BusinessObject | 16 |

## Edge Type Distribution (Top 10)

| Type | Count |
|------|-------|
| contains | 168 |
| has_field | 68 |
| reads_from | 60 |
| writes_to | 51 |
| flows_to | 51 |
| transitions_to | 45 |
| calls | 43 |
| has_status | 35 |
| generates | 34 |
| supports | 26 |

## R9 Duplicate Edge Resolution

- R9 imported 10 edges with different MERGE key pattern
- R10 MERGE created 10 parallel duplicates (same relation_id)
- Cleanup: 10 duplicates removed, final count = 703 ✅
- MERGE idempotency confirmed for identical key patterns

## Baseline Preservation

| Check | Value |
|-------|-------|
| Baseline nodes (murata_live_v1) | 3034 (unchanged) |
| Baseline data modified | NO ✅ |
| Cross-contamination edges | 0 ✅ |
