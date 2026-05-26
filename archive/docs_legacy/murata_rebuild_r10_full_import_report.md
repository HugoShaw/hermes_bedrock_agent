# R10 Full Neptune Import Report

## Phase Summary

| Item | Value |
|------|-------|
| Phase | R10: Full Neptune Import & Graph Validation |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |
| Execution Mode | FULL_NEPTUNE_IMPORT_AND_GRAPH_VALIDATION |
| Date | 2025-06-18 |
| Quality Gate | 26/26 PASSED ✅ |

## Neptune Target

| Config | Value |
|--------|-------|
| Endpoint | g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com |
| Graph ID | g-nbuyck5yl8 |
| Region | ap-northeast-1 |
| Auth | SigV4 (boto3 neptune-graph) |

## Import Results

| Operation | Attempted | Success | Failed | Time | Rate |
|-----------|-----------|---------|--------|------|------|
| Node import | 381 | 381 | 0 | 8.3s | 45.8/s |
| Edge import | 703 | 703 | 0 | 16.0s | 44.0/s |
| **Total** | **1,084** | **1,084** | **0** | **24.3s** | — |

## R9 Duplicate Cleanup

10 duplicate edges from R9 sample import were cleaned (different MERGE key pattern). Final count: 703 edges exactly.

## Read-Back Verification

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Rebuild nodes | 381 | 381 | ✅ |
| Rebuild edges | 703 | 703 | ✅ |
| Labels | 20 | 20 | ✅ |
| Edge types | 28 | 28 | ✅ |
| Properties readable | YES | YES | ✅ |
| Baseline unchanged | 3034 | 3034 | ✅ |

## Total Graph After Import

| Metric | Before | After |
|--------|--------|-------|
| Total nodes | 3054 | 3415 |
| Total edges | 5146 | 5849 |
| Rebuild nodes | 20 (R9) | 381 |
| Rebuild edges | 10 (R9) | 703 |

## Quality Gate: 26/26 PASSED ✅

All quality gates passed. Zero failures. Full import validated.
