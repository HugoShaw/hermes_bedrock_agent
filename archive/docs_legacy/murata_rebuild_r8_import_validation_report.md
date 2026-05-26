# R8 Import Validation Report

## Summary

All validation checks PASSED. The R7 canonical graph is structurally valid and ready for Neptune import.

---

## Entity Validation

| Check | Result | Detail |
|-------|--------|--------|
| Entity count | 381 | matches R7 |
| Missing entity_id | 0 | ✅ |
| Duplicate entity_id | 0 | ✅ |
| Missing run_id | 0 | ✅ |
| Missing dataset | 0 | ✅ |
| Missing canonical_name | 0 | ✅ |
| Missing entity_type | 0 | ✅ |
| Missing layer | 0 | ✅ |
| Unsupported labels | 0 | ✅ |

---

## Relation Validation

| Check | Result | Detail |
|-------|--------|--------|
| Relation count | 703 | matches R7 |
| Missing relation_id | 0 | ✅ |
| Duplicate relation_id | 0 | ✅ |
| Dangling source | 0 | ✅ |
| Dangling target | 0 | ✅ |
| Unsupported types | 0 | ✅ |
| Custom type count | 0 | ✅ |

---

## Property Serialization

| Check | Status |
|-------|--------|
| Arrays serialized to JSON strings | ✅ |
| Evidence text truncated at 500 chars | ✅ |
| No None/null values in critical fields | ✅ |
| run_id on all records | ✅ |
| dataset on all records | ✅ |
| created_by_phase=R8 on all records | ✅ |

---

## Node Label Distribution (Top 10)

| Label | Count |
|-------|-------|
| Table | 58 |
| BusinessStep | 52 |
| Action | 45 |
| Field | 39 |
| Module | 35 |
| Class | 32 |
| Service | 28 |
| Method | 24 |
| Column | 22 |
| Status | 18 |

---

## Relation Type Distribution (Top 10)

| Type | Count |
|------|-------|
| contains | 142 |
| depends_on | 98 |
| calls | 87 |
| generates | 76 |
| belongs_to | 64 |
| reads_from | 52 |
| writes_to | 48 |
| implements | 39 |
| has_field | 35 |
| relates_to | 22 |

---

## Live Validation

| Item | Status |
|------|--------|
| Connectivity check | NOT EXECUTED (dry-run only) |
| Sample import | NOT EXECUTED (dry-run only) |
| Full import | NOT EXECUTED (dry-run only) |

---

## Verdict

**IMPORT-READY**: The graph passes all structural, referential, and label validations. Safe to proceed to sample import (R9) when explicitly confirmed.
