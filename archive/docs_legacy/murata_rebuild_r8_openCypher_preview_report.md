# R8 OpenCypher Preview Report

## Summary

Generated parameterized openCypher MERGE scripts for Neptune import. All scripts use parameterized queries to prevent injection and follow Neptune Analytics conventions.

---

## Node MERGE Pattern

```cypher
MERGE (n:Label {entity_id: $entity_id})
SET n += $properties
```

Properties include:
- `entity_id` (primary key)
- `canonical_name`
- `display_name`
- `entity_type`
- `layer`
- `run_id` = 'murata_rebuild_v1'
- `dataset` = 'murata'
- `aliases_json` (serialized array)
- `source_chunk_ids_json` (serialized array)
- `source_uris_json` (serialized array)
- `related_target_questions_json` (serialized array)
- `confidence_avg`, `confidence_max`, `support_count`
- `created_by_phase` = 'R8'

---

## Edge MERGE Pattern

```cypher
MATCH (s {entity_id: $source_entity_id})
MATCH (t {entity_id: $target_entity_id})
MERGE (s)-[r:RELATION_TYPE {relation_id: $relation_id}]->(t)
SET r += $properties
```

Properties include:
- `relation_id` (primary key)
- `relation_type`
- `run_id` = 'murata_rebuild_v1'
- `dataset` = 'murata'
- `source_chunk_ids_json`, `evidence_ids_json`
- `evidence_preview` (truncated text)
- `confidence_avg`, `confidence_max`, `support_count`
- `created_by_phase` = 'R8'

---

## Import Execution Strategy

1. Import all 381 nodes first (MERGE+SET)
2. Import all 703 edges after nodes exist
3. Sequential execution (1 query per call)
4. 3-second delay between calls (Neptune Analytics rate-limit safety)
5. Use `botocore.Config(read_timeout=600)` for large responses
6. Parameterized queries via Neptune Analytics API (SigV4 auth)

---

## Estimated Import Time

| Phase | Items | Time/Item | Estimated |
|-------|-------|-----------|-----------|
| Nodes | 381 | 3s | ~19 min |
| Edges | 703 | 3s | ~35 min |
| Total | 1,084 | — | ~54 min |

---

## Generated Script Files

| File | Purpose |
|------|---------|
| neptune_node_merge_preview_r8.cypher | Sample node MERGE (first 10) + template |
| neptune_edge_merge_preview_r8.cypher | Sample edge MERGE (first 10) + template |
| neptune_sample_import_preview_r8.cypher | 20-node + 30-edge sample with validation |
| neptune_rollback_r8.cypher | Scoped rollback (DO NOT EXECUTE without confirmation) |

---

## Safety Notes

- All scripts include `run_id` and `dataset` on every record
- No string interpolation in live execution — use parameterized queries
- Neptune Analytics uses `$param` syntax for parameters
- No arrays in property values — use JSON-serialized strings
- Use single quotes within Cypher strings (not escaped backslashes)
- MERGE+SET pattern ensures idempotent re-runs
