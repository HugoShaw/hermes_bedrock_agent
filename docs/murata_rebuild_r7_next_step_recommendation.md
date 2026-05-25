# R7 Next Step Recommendation

## R7 Status: COMPLETE ✅

Phase R7 Graph Normalization, Deduplication & Integrity passed all quality gates.

---

## Readiness for R8

### What R7 Produced
- 381 canonical entities (from 859 raw, 55.6% reduction)
- 703 canonical relations (from 1,044 raw, 32.7% reduction)
- 181 canonical evidence records (100% linked)
- Neptune preview CSVs validated (zero dangling)
- Q4 final semantic map preview (10-node path, 3 allowed types)
- Full Q1-Q5 coverage preserved

### R8 Entry Requirements Met

| Requirement | Status |
|-------------|--------|
| Canonical entities exist | ✅ |
| Canonical relations exist | ✅ |
| No dangling references | ✅ |
| Neptune preview valid | ✅ |
| Q1-Q5 coverage preserved | ✅ |
| Integrity checks pass | ✅ |

---

## Recommended R8 Scope

### R8: Neptune Dry-Run / Import Preview

1. **Dry-run validation**: Simulate Neptune import using preview CSVs
2. **Schema conflict check**: Verify no collision with baseline `murata_live_v1` data
3. **Property compatibility**: Ensure canonical IDs don't clash with existing graph
4. **Import strategy**: MERGE+SET with parameterized openCypher
5. **Selective import**: Use `run_id=murata_rebuild_v1` as filter property
6. **Rollback plan**: Delete by `run_id` property if rebuild quality is poor

### R8 Should NOT:
- Delete baseline data
- Overwrite murata_live_v1 properties
- Run full QA yet (that's R9)

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Entity ID collision with baseline | Use ent_ prefix (baseline uses different format) |
| Q4 path not fully linear | Graph has connected components, BFS confirms reachability |
| 4 pending relations excluded | 0.6% impact, no Q1-Q5 coverage loss |
| Neptune timeout on batch import | Use sequential MERGE+SET with 3s delay (per project memory) |

---

## Decision

**Recommend proceeding to R8: Neptune Dry-Run / Import Preview.**

R7 canonical graph is structurally sound, coverage-complete, and Neptune-ready.
