# R7 Integrity Check Report

## Summary

All integrity checks PASSED. The canonical graph has zero structural defects.

---

## Entity Integrity

| Check | Result | Detail |
|-------|--------|--------|
| E1 No missing entity_id | ✅ PASS | 0 missing |
| E2 No duplicate entity_id | ✅ PASS | 0 duplicates |
| E3 No missing canonical_name | ✅ PASS | 0 missing |
| E4 No missing entity_type | ✅ PASS | 0 missing |
| E5 No missing layer | ✅ PASS | 0 missing |
| E6 run_id/dataset correct | ✅ PASS | All murata_rebuild_v1/murata |
| E7 Has source_chunk_ids | ✅ PASS | All have ≥1 chunk |

---

## Relation Integrity

| Check | Result | Detail |
|-------|--------|--------|
| R1 No missing relation_id | ✅ PASS | 0 missing |
| R2 No duplicate relation_id | ✅ PASS | 0 duplicates |
| R3 No dangling source | ✅ PASS | 0 dangling |
| R4 No dangling target | ✅ PASS | 0 dangling |
| R5 All types allowed | ✅ PASS | 22 types, 0 unsupported |
| R6 Has evidence | ✅ PASS | All have evidence_texts |
| R7 Has source_chunk | ✅ PASS | All have source_chunk_ids |
| R8 Has confidence | ✅ PASS | 0 missing |
| R9 No custom type | ✅ PASS | 0 custom |
| R10 relates_to < 20% | ✅ PASS | 3.1% |
| R11 Self-ref valid | ✅ PASS | 5 valid state transitions |

---

## Evidence Integrity

| Check | Result | Detail |
|-------|--------|--------|
| Ev1 Has source_chunk | ✅ PASS | 181/181 |
| Ev2 Has evidence_text | ✅ PASS | 181/181 |
| Ev3 Links to entity/relation | ✅ PASS | 181/181 linked |

---

## Q1-Q5 Coverage Integrity

| Question | Entities | Relations | Status |
|----------|----------|-----------|--------|
| Q1 | 297 | 587 | ✅ Full |
| Q2 | 113 | 266 | ✅ Full |
| Q3 | 115 | 243 | ✅ Full |
| Q4 | 221 | 504 | ✅ Full |
| Q5 | 142 | 314 | ✅ Full |

---

## Referential Integrity Summary

- **Nodes referenced by edges**: 381/381 (100% — no orphan nodes needed by edges)
- **Edge endpoints in node set**: 703/703 (100% — zero dangling)
- **Evidence linked**: 181/181 (100%)
- **Neptune CSV valid**: No missing ~id, ~from, ~to, ~label

---

## Conclusion

The canonical graph passes ALL integrity checks. It is structurally sound, referentially complete, and ready for Neptune preview/import in R8.
