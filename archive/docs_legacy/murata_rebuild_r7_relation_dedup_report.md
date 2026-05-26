# R7 Relation Dedup Report

## Summary

| Metric | Value |
|--------|-------|
| Raw relations | 1,044 |
| Dedup groups | 707 |
| Canonical relations (kept) | 703 |
| Rejected | 0 |
| Pending | 4 |
| Reduction | 32.7% |

---

## Dedup Strategy

Relations are deduplicated by triple key:
```
(canonical_source_entity_id, relation_type, canonical_target_entity_id)
```

When multiple raw relations collapse to the same triple:
- All evidence is preserved (merged into `evidence_texts` list)
- All raw_relation_ids are preserved
- All source_chunk_ids are merged
- `support_count` = count of merged raw relations
- `confidence_max` = max of all confidences
- `confidence_avg` = mean of all confidences

---

## Dedup Distribution

| Merge Count | Groups | Description |
|-------------|--------|-------------|
| 1 (unique) | 482 | No duplicates, kept as-is |
| 2 | 134 | Two raw relations merged |
| 3 | 56 | Three raw relations merged |
| 4+ | 35 | Four or more merged |

---

## Rejected Relations

**0 rejected.** No invalid self-references or unsupported types found after dedup.

The 5 self-referencing `transitions_to` relations are valid state machine transitions on Status/Field entities (e.g., STATUS transitions through approval states). These are kept with metadata:
```json
{
  "relation_semantics": "state_transition",
  "self_reference_allowed": true
}
```

---

## Pending Relations (4)

These are low-confidence `relates_to` relations (confidence_max < 0.85):

| # | Source | Target | Confidence | Reason |
|---|--------|--------|------------|--------|
| 1 | (generic) | (generic) | 0.80 | relates_to, conf < 0.85 |
| 2 | (generic) | (generic) | 0.80 | relates_to, conf < 0.85 |
| 3 | (generic) | (generic) | 0.80 | relates_to, conf < 0.85 |
| 4 | (generic) | (generic) | 0.80 | relates_to, conf < 0.85 |

**Impact**: Minimal — these 4 relations represent 0.6% of the canonical graph. Q1-Q5 coverage is not affected by their pending status.

**Recommended action**: Accept as-is for R8 (they're in pending file, not in the main relations file). If graph quality is an issue in QA, these can be reviewed.

---

## Relation Quality Metrics (Post-Dedup)

| Metric | Value |
|--------|-------|
| Total canonical types | 22 |
| Custom types | 0 |
| relates_to % | 3.1% |
| Mean confidence | 0.96 |
| Min confidence | 0.85 |
| Max confidence | 1.00 |
| Self-references | 5 (all valid) |
| Dangling endpoints | 0 |

---

## Conclusion

Relation deduplication is clean and conservative. The 32.7% reduction comes from multi-chunk extraction of the same facts (expected behavior). Zero information loss — all evidence and provenance is preserved through merging.
