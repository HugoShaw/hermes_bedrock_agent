# R9 Rollback Plan

## ⚠️ DO NOT EXECUTE WITHOUT EXPLICIT USER CONFIRMATION

---

## Scope

This rollback plan removes ONLY data imported during R9 sample import:

| Target | Scope |
|--------|-------|
| run_id | murata_rebuild_v1 |
| dataset | murata |
| Nodes to remove | 20 |
| Edges to remove | 10 |

---

## Rollback Script Location

```
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_sample_rollback_plan_r9.cypher
```

---

## Rollback Steps

1. Delete edges between rebuild nodes
2. Delete rebuild nodes
3. Verify zero remaining

---

## Safety Guarantees

- ONLY targets `run_id=murata_rebuild_v1` AND `dataset=murata`
- Does NOT touch `murata_live_v1` baseline
- Does NOT delete the entire graph
- Idempotent (safe to run multiple times)

---

## When to Execute Rollback

Execute rollback ONLY if:

1. Full import (R10) needs a fresh start
2. Data corruption detected
3. User explicitly requests cleanup

Do NOT execute rollback:
- Before R10 (sample data is useful for verification)
- If R10 full import will use MERGE (idempotent, no conflicts)

---

## Current Recommendation

**DO NOT ROLLBACK** — Keep sample data in Neptune. R10 full import uses MERGE which will simply update existing nodes/edges without creating duplicates.
