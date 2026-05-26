# R7 Graph Normalization Report

## Phase Summary

| Item | Value |
|------|-------|
| Phase | R7: Graph Normalization, Dedup & Integrity |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |
| Input | R6 raw extraction (859E, 1044R, 181Ev) |
| Output | Canonical graph (381E, 703R, 181Ev) |
| Status | COMPLETE |

---

## Entity Normalization

| Metric | Value |
|--------|-------|
| Raw entities | 859 |
| Canonical entities | 381 |
| Dedup reduction | 55.6% |
| Merged entries | 621 |
| Kept separate | 238 |
| Pending merges | 0 |

### Normalization Rules Applied

1. **Case normalization**: CamelCase → snake_case slugs
2. **Full-width/half-width**: Normalized to half-width
3. **Whitespace/punctuation**: Cleaned and standardized
4. **Type-safe merge**: Only merge entities with same (slug, type)
5. **Cross-type separation**: Table ≠ Class ≠ Action ≠ Service preserved

### Entity Type Distribution (Canonical)

| Type | Count | Layer |
|------|-------|-------|
| Column | 78 | data |
| Method | 52 | system |
| Table | 46 | data |
| Field | 33 | data |
| BusinessStep | 30 | business |
| Action | 22 | system |
| Class | 22 | system |
| Status | 15 | data |
| Service | 14 | system |
| ExternalSystem | 11 | system |
| BusinessProcess | 10 | business |
| Module | 8 | system |
| View | 8 | data |
| API | 7 | system |
| EnumValue | 6 | data |
| Screen | 5 | business |
| Report | 4 | business |
| Interface | 3 | system |
| DAO | 2 | system |
| File | 2 | evidence |
| Document | 1 | evidence |
| BusinessObject | 1 | business |
| BusinessRule | 1 | business |

### Layer Distribution

| Layer | Count |
|-------|-------|
| data | 186 (48.8%) |
| system | 141 (37.0%) |
| business | 51 (13.4%) |
| evidence | 3 (0.8%) |

---

## Relation Normalization

| Metric | Value |
|--------|-------|
| Raw relations | 1,044 |
| Canonical relations | 703 |
| Dedup reduction | 32.7% |
| Rejected | 0 |
| Pending | 4 |
| Self-references kept | 5 (valid state transitions) |

### Relation Type Distribution (Canonical)

| Type | Count | % |
|------|-------|---|
| contains | 168 | 23.9% |
| has_field | 68 | 9.7% |
| reads_from | 60 | 8.5% |
| writes_to | 51 | 7.3% |
| flows_to | 51 | 7.3% |
| transitions_to | 45 | 6.4% |
| calls | 43 | 6.1% |
| has_status | 35 | 5.0% |
| generates | 34 | 4.8% |
| supports | 26 | 3.7% |
| depends_on | 23 | 3.3% |
| relates_to | 22 | 3.1% |
| updates | 20 | 2.8% |
| joins_on | 14 | 2.0% |
| references | 13 | 1.8% |
| belongs_to | 9 | 1.3% |
| maps_to | 8 | 1.1% |
| exports | 5 | 0.7% |
| implements | 3 | 0.4% |
| approves | 2 | 0.3% |
| imports | 2 | 0.3% |
| rejects | 1 | 0.1% |

### Key Observations

- **No custom relation types** — all 22 types in allowed set
- **relates_to at 3.1%** — well below 20% threshold
- **contains (23.9%)** is dominant — healthy for enterprise schema modeling
- **Self-references**: 5 `transitions_to` on Status/Field entities — valid state machines

---

## Evidence Normalization

| Metric | Value |
|--------|-------|
| Raw evidence | 181 |
| Canonical evidence | 181 |
| Linked to entities | 181/181 (100%) |
| Linked to relations | 181/181 (100%) |

### Evidence Types

| Type | Count |
|------|-------|
| process | 170 |
| schema | 9 |
| code | 2 |

---

## Provenance Preservation

All canonical records preserve:
- `source_chunk_ids` — tracing to R3/R4 chunks
- `raw_entity_ids` / `raw_relation_ids` — tracing to R6 raw records
- `evidence_texts` — original evidence supporting relations
- `support_count` — how many raw records merged into canonical
- `confidence_max` / `confidence_avg` — aggregate confidence metrics
- `related_target_questions` — Q1-Q5 mapping preserved

---

## Conclusion

Entity normalization reduced 859 → 381 (55.6% reduction) through safe type-aware deduplication. Relation dedup reduced 1044 → 703 (32.7% reduction) through triple-key deduplication. Zero rejected relations. 4 pending low-confidence relates_to relations for optional review. All integrity checks passed.
