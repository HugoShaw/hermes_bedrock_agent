# R8 Rollback Plan

## ⚠️ WARNING: DO NOT EXECUTE WITHOUT EXPLICIT USER CONFIRMATION

This document describes the rollback strategy for the murata_rebuild_v1 Neptune import. The rollback script exists but must NOT be executed unless explicitly confirmed by the user.

---

## Scope

The rollback is scoped **exclusively** to:

```
run_id = murata_rebuild_v1
dataset = murata
```

It will **NEVER** touch:

```
run_id = murata_live_v1
collection = murata_e2e_murata_live_v1
```

---

## Rollback Script

File: `neptune_rollback_r8.cypher`

### Step 1: Count (verification only)

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS rebuild_nodes_count;
```

Expected result: 381 (if full import completed) or ≤20 (if sample import only)

### Step 2: Count edges (verification only)

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})-[r]->(m {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(r) AS rebuild_edges_count;
```

### Step 3: Delete (ONLY if confirmed)

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
DETACH DELETE n;
```

### Step 4: Verify deletion

```cypher
MATCH (n {run_id: 'murata_rebuild_v1', dataset: 'murata'})
RETURN count(n) AS remaining_nodes;
-- Expected: 0
```

### Step 5: Verify baseline untouched

```cypher
MATCH (n {run_id: 'murata_live_v1'})
RETURN count(n) AS baseline_nodes;
-- Expected: unchanged (3034 from Phase 10B.1 import)
```

---

## When to Use Rollback

1. After a failed full import that left partial data
2. After a test/sample import that should be cleaned before full import
3. If data corruption is discovered post-import
4. If the rebuild strategy changes and a fresh start is needed

---

## Safety Guarantees

| Item | Status |
|------|--------|
| Rollback targets only rebuild data | ✅ |
| Baseline data never touched | ✅ |
| Verification queries run before delete | ✅ |
| Post-delete verification included | ✅ |
| User confirmation required | ✅ |

---

## Current Status

- Rollback script: GENERATED (not executed)
- Live import: NOT EXECUTED (R8 is dry-run only)
- Rollback execution: BLOCKED pending user confirmation
