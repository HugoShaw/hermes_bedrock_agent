# R6 Quality Gate Decision

## Decision: PASS ✅

R6 Graph Extraction passes all 23 quality gates with 5 non-blocking warnings.

---

## Quality Gate Matrix

| # | Gate | Result | Evidence |
|---|------|--------|----------|
| G01 | All 12 artifact files exist | ✅ | 12/12 present |
| G02 | Entity count > 0 | ✅ | 859 raw, 387 unique |
| G03 | Relation count > 0 | ✅ | 1,044 clean |
| G04 | Evidence count > 0 | ✅ | 181 records |
| G05 | All relations have required fields | ✅ | 0 missing/empty |
| G06 | Confidence range valid [0,1] | ✅ | [0.80, 1.00], mean=0.962 |
| G07 | Custom relation count = 0 | ✅ | 0 custom types |
| G08 | relates_to < 20% | ✅ | 2.7% (28/1044) |
| G09 | Q1 coverage ≥ 10 entities | ✅ | 345 entities |
| G10 | Q2 includes JOURNAL_BASE | ✅ | 21 occurrences |
| G11 | Q3 has SUN_REQUEST+JOURNAL_BASE+RECEIVING_JOURNAL | ✅ | All 3 present |
| G12 | Q3 has key join fields | ✅ | 5/5 fields present |
| G13 | Q4 preview CSV exists | ✅ | 286 nodes, 149 edges |
| G14 | Q4 q4_relation_type restricted | ✅ | Only generates/depends_on/relates_to |
| G15 | Q4 continuous path A→B→C→D | ✅ | 13-node path |
| G16 | Q5 has PAYMENT_REQ | ✅ | 18 occurrences |
| G17 | Q5 has PAYMENT_RECEIVING | ✅ | 15 occurrences |
| G18 | Q5 has STATUS+BILL_NO | ✅ | 15 + 14 occurrences |
| G19 | Q5 has APPROVAL_BY/TIME/REMARK | ✅ | 6/6/7 occurrences |
| G20 | Q5 has OA/callback proposed design | ✅ | 13 OA-related entities |
| G21 | No extraction failures | ✅ | 0 failures |
| G22 | No dangling relations | ✅ | 0 src/tgt missing |
| G23 | Dedup candidates identified | ✅ | 140 groups |

**Score: 23/23 PASS**

---

## Non-Blocking Warnings

| # | Warning | Assessment | R7 Action |
|---|---------|------------|-----------|
| W01 | Q4 CSV `relation_type` has non-Q4 types | Design choice: `q4_relation_type` is the restricted field | Use `q4_relation_type` when generating final Q4 Neptune CSV |
| W02 | 5 self-referencing relations | Semantically valid transitions_to on status fields | Keep — represent state machines |
| W03 | 56 relations with evidence < 20 chars | Chinese text is dense; all evidence is meaningful | No action |
| W04 | 333 duplicate relation instances | Expected from multi-chunk extraction | R7 dedup will merge to 1 per (src,tgt,type) |
| W05 | 4 low-confidence relations (0.80) | 0.4% of total, all are generic relates_to | R7 may apply 0.85 filter |

---

## Critical Metrics Summary

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Extraction success rate | 46/46 (100%) | ≥ 90% | ✅ |
| Custom relation types | 0 | = 0 | ✅ |
| relates_to percentage | 2.7% | < 20% | ✅ |
| Mean confidence | 0.962 | ≥ 0.80 | ✅ |
| Q1-Q5 full coverage | 5/5 | ≥ 4/5 | ✅ |
| Dangling relations | 0 | = 0 | ✅ |
| Extraction failures | 0 | < 5 | ✅ |
| Q4 continuous path length | 13 | ≥ 4 | ✅ |

---

## Recommendation

### R6 Quality Gate: PASS ✅

Proceed to **R7: Graph Normalization & Integrity**.

### R7 Priority Tasks

1. **Entity dedup**: Merge 140 groups (859 → ~387 canonical entities)
2. **Relation dedup**: Merge 177 duplicate groups (1044 → ~711 unique relations)
3. **Self-reference review**: Keep 5 transitions_to self-refs or convert to state attributes
4. **Q4 consolidation**: Use `q4_relation_type` field for final Q4 output
5. **Confidence filter**: Consider 0.85 threshold (removes only 4 relations)
6. **Neptune schema**: Validate labels/properties against Neptune constraints

### No Targeted Fix Required

R6 extraction is clean. No re-extraction needed.
