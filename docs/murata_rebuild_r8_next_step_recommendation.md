# R8 Next Step Recommendation

## R8 Status: COMPLETE ✅

Phase R8 Neptune Dry-Run passed all 25 quality gates. The canonical graph (381 nodes, 703 edges) is fully import-ready.

---

## Recommended Next Phase: R9

### R9 Options

**Option A: Sample Live Import (Recommended)**

Import 20 nodes + 30 edges as a validation round. Verify:
- Neptune connectivity
- MERGE+SET creates expected nodes/edges
- Properties persist correctly
- Rollback works cleanly
- Read-back queries return correct structure

**Option B: Full Live Import**

Import all 381 nodes + 703 edges. Takes ~54 minutes with 3s delay. Requires:
- Explicit user confirmation
- Rollback script ready (already generated)
- Post-import validation queries

**Option C: Clean Old Rebuild + Full Import**

If murata_rebuild_v1 data from a prior attempt exists in Neptune:
1. Execute rollback (count, verify, delete)
2. Re-import full canonical graph
3. Validate

---

## Pre-R9 Requirements

1. Neptune endpoint accessible from this environment
2. AWS credentials with Neptune write access
3. Explicit user confirmation of import mode
4. Decision on whether old rebuild data exists in Neptune

---

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Neptune timeout on large batches | LOW | Sequential 3s-delay pattern |
| Property size limits | LOW | Evidence text truncated at 500 chars |
| SigV4 auth expiry during 54min import | MEDIUM | Boto3 auto-refreshes credentials |
| Baseline data corruption | NONE | Rollback scoped, no baseline queries |
| Partial import failure | LOW | MERGE is idempotent, can retry safely |

---

## What R9 Should Produce

1. Import execution log
2. Post-import validation (node/edge counts, Q4 path verification)
3. Sample query results (JOURNAL_BASE neighbors, AP flow path)
4. Decision on whether to proceed to R10 (LanceDB embedding + hybrid retrieval)

---

## Decision Required

Please confirm:
1. Proceed to R9? (YES/NO)
2. R9 mode: sample (20+30) or full (381+703)?
3. Should old murata_rebuild_v1 data be cleaned first?
