# R8 Neptune Dry-Run Report

## Phase Summary

| Item | Value |
|------|-------|
| Phase | R8: Neptune Dry-Run / Import Preview |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |
| Execution Mode | DRY-RUN ONLY |
| Status | COMPLETE |
| Quality Gate | 25/25 PASSED ✅ |

---

## Neptune Target

| Config | Value |
|--------|-------|
| Endpoint | g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com |
| Graph ID | g-nbuyck5yl8 |
| Region | ap-northeast-1 |
| Client | NeptuneClient (openCypher via SigV4) |
| Live Import | NOT EXECUTED (dry-run only) |

---

## Graph Summary

| Metric | Count |
|--------|-------|
| Nodes | 381 |
| Edges | 703 |
| Evidence | 181 |
| Node labels | 20 |
| Edge labels | 22 |
| Q4 nodes | 221 |
| Q4 edges | 499 |

---

## Import Strategy

1. **Method**: MERGE+SET with parameterized openCypher
2. **Execution**: Sequential (1 query per entity/relation)
3. **Delay**: 3s between calls (recommended per project memory)
4. **Tagging**: All records tagged with run_id=murata_rebuild_v1, dataset=murata
5. **Rollback**: DETACH DELETE scoped to run_id=murata_rebuild_v1

---

## Generated Artifacts (14 files)

| # | File | Size |
|---|------|------|
| 1 | neptune_nodes_r8.jsonl | 259 KB |
| 2 | neptune_edges_r8.jsonl | 543 KB |
| 3 | neptune_node_merge_params_r8.jsonl | 267 KB |
| 4 | neptune_edge_merge_params_r8.jsonl | 576 KB |
| 5 | neptune_node_merge_preview_r8.cypher | 3.5 KB |
| 6 | neptune_edge_merge_preview_r8.cypher | 4.5 KB |
| 7 | neptune_rollback_r8.cypher | 1.3 KB |
| 8 | neptune_sample_nodes_r8.jsonl | 15 KB |
| 9 | neptune_sample_edges_r8.jsonl | 26 KB |
| 10 | neptune_sample_import_preview_r8.cypher | 3.2 KB |
| 11 | neptune_import_validation_r8.json | 543 B |
| 12 | neptune_import_manifest_r8.json | 2 KB |
| 13 | q4_nodes_neptune_csv_r8.csv | 14 KB |
| 14 | q4_edges_neptune_csv_r8.csv | 41 KB |

---

## Safety Verification

| Check | Status |
|-------|--------|
| Baseline (murata_live_v1) untouched | ✅ |
| No Neptune queries executed | ✅ |
| No Neptune writes executed | ✅ |
| No Bedrock calls | ✅ |
| No embedding generation | ✅ |
| No LanceDB writes | ✅ |
| Rollback scoped correctly | ✅ |

---

## Conclusion

R8 dry-run is complete. All 14 artifact files and 25 quality gates passed. The canonical graph is fully ready for Neptune import. Live import was NOT executed — pending user confirmation for R9.
