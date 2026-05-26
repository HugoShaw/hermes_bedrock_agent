# R7 Neptune Preview Report

## Summary

Neptune-ready preview CSV files have been generated. These are PREVIEW ONLY — no Neptune write occurs until R8.

---

## Generated Files

| File | Rows | Columns |
|------|------|---------|
| neptune_nodes_preview_r7.csv | 381 | 14 |
| neptune_edges_preview_r7.csv | 703 | 11 |

---

## Node Schema

```csv
~id,~label,name,canonical_name,entity_type,layer,run_id,dataset,display_name,aliases,source_chunk_ids,source_uris,confidence_avg,support_count
```

## Edge Schema

```csv
~id,~from,~to,~label,relation_type,run_id,dataset,evidence_ids,source_chunk_ids,confidence_avg,support_count
```

---

## Validation Results

| Check | Result |
|-------|--------|
| All nodes have ~id | ✅ 381/381 |
| All nodes have ~label | ✅ 381/381 |
| All edges have ~id | ✅ 703/703 |
| All edges have ~from | ✅ 703/703 |
| All edges have ~to | ✅ 703/703 |
| All edges have ~label | ✅ 703/703 |
| All ~from exist in nodes | ✅ 0 missing |
| All ~to exist in nodes | ✅ 0 missing |
| No duplicate ~id in nodes | ✅ 0 duplicates |
| No duplicate ~id in edges | ✅ 0 duplicates |
| CSV encoding valid | ✅ UTF-8 |
| No unescaped delimiters | ✅ csv.writer handles |

---

## Neptune Compatibility Notes

1. **~id format**: `ent_<layer>_<type>_<slug>` for nodes, `rel_<seq>` for edges
2. **~label**: Maps to entity_type for nodes, relation_type for edges
3. **Multi-value fields**: Semicolon-separated (aliases, source_chunk_ids, evidence_ids)
4. **run_id/dataset**: Present on all records for Neptune property filtering

---

## Estimated Neptune Graph Size

| Metric | Count |
|--------|-------|
| Nodes | 381 |
| Edges | 703 |
| Properties per node | ~10 avg |
| Properties per edge | ~8 avg |
| Total graph triples | ~5,000 estimated |

This is a modest-sized enterprise graph suitable for Neptune Analytics or Neptune Serverless.

---

## R8 Import Considerations

1. Neptune Analytics (g-nbuyck5yl8) uses openCypher — CSV load via LOAD_FROM_S3 or programmatic MERGE+SET
2. Recommended: MERGE+SET with parameterized queries (per project memory)
3. `run_id` property allows selective deletion of rebuild data without touching baseline
4. Graph ID: g-nbuyck5yl8, region: ap-northeast-1

---

## Conclusion

Neptune preview CSVs are structurally valid and ready for R8 dry-run import. No missing IDs, no dangling references, proper escaping. The graph size (381 nodes, 703 edges) is well within Neptune Analytics limits.
