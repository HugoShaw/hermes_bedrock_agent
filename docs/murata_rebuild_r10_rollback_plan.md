# R10 Rollback Plan

## ⚠️ DO NOT EXECUTE WITHOUT EXPLICIT USER CONFIRMATION

---

## Scope

This rollback plan removes ALL data imported during R10 full import:

| Target | Scope |
|--------|-------|
| Nodes to remove | 381 (run_id=murata_rebuild_v1, dataset=murata) |
| Edges to remove | 703 (between rebuild nodes) |
| Baseline affected | NO — murata_live_v1 is untouched |

## Rollback Script

File: `~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_rollback_plan_r10.cypher`

### Steps:

1. Delete all edges between rebuild nodes
2. Delete all rebuild nodes
3. Verify cleanup (expect 0 remaining)

### Commands:

```cypher
// Step 1: Delete rebuild edges
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
DELETE r;

// Step 2: Delete rebuild nodes
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
DELETE n;

// Step 3: Verify
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'}) RETURN count(n) AS remaining;
```

## When to Use

- Only if R10 import data must be completely removed
- Only with explicit user confirmation
- Never auto-executed

## Re-Import After Rollback

R10 full import can be safely re-run after rollback using the same MERGE+SET pattern. The operation is idempotent.
