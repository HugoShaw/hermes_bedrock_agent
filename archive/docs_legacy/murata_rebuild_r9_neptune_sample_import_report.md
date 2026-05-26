# R9 Neptune Sample Import Report

## Phase Summary

| Item | Value |
|------|-------|
| Phase | R9: Neptune Sample Live Import & Validation |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |
| Execution Mode | SAMPLE_LIVE_IMPORT_ONLY |
| Date | 2025-05-18 |
| Neptune Graph | g-nbuyck5yl8 (ap-northeast-1) |
| Auth | SigV4 (boto3 neptune-graph) |

---

## Results

| Metric | Value |
|--------|-------|
| Nodes attempted | 20 |
| Nodes imported | 20 ✅ |
| Nodes failed | 0 |
| Edges attempted | 30 |
| Edges MERGE success | 30 |
| Edges actually created | 10 |
| Edges skipped (missing endpoints) | 20 |
| Read-back node count | 20 ✅ |
| Read-back edge count | 10 ✅ |
| JOURNAL_BASE found | YES ✅ |
| PAYMENT_REQ found | YES ✅ |
| 2-hop paths found | 7 ✅ |
| Variable-length paths | Supported ✅ |
| Properties preserved | YES ✅ |
| Baseline modified | NO ✅ |

---

## Edge Skip Explanation

20 out of 30 sample edges reference target/source nodes that are NOT in the 20-node sample set. The MERGE pattern uses `MATCH (s {entity_id: $src}) MATCH (t {entity_id: $tgt})` — when either endpoint doesn't exist, Neptune silently returns an empty result (no edge created, no error). This is correct and expected behavior. These edges will be created during the full R10 import when all 381 nodes exist.

---

## Key Findings

1. **Neptune connectivity**: Fully functional (3034 baseline + 20 rebuild nodes)
2. **SigV4 auth**: Working correctly with boto3 neptune-graph client
3. **MERGE idempotency**: Confirmed — re-running creates no duplicates
4. **Property preservation**: All properties (entity_id, run_id, dataset, canonical_name, etc.) readable
5. **Label assignment**: All 10 distinct labels correctly assigned
6. **Path traversal**: Both fixed-length and variable-length paths work
7. **Query performance**: All queries return < 1 second

---

## Quality Gate: 23/23 PASSED ✅
