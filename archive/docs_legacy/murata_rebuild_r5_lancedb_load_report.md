# Phase R5 — LanceDB Load Report

## Summary

Successfully created LanceDB collection `murata_e2e_murata_rebuild_v1` with 51 vector records.

## Storage Details

| Parameter | Value |
|-----------|-------|
| LanceDB Path | ~/projects/data/vector_store/lancedb |
| Collection Name | murata_e2e_murata_rebuild_v1 |
| Action Taken | create_new (no pre-existing rebuild collection) |
| Records Written | 51 |
| Vector Dimension | 1024 |
| Baseline Preserved | ✅ murata_e2e_murata_live_v1 untouched |

## Schema

All 22 fields preserved per record:

- chunk_id, run_id, dataset, text, vector
- source, source_uri, source_file_name, source_type
- chunk_purpose, summary_type, is_summary
- parent_chunk_ids (JSON string), related_target_questions (JSON string)
- expected_entities (JSON string), key_tables (JSON string)
- key_fields (JSON string), key_code_modules (JSON string)
- should_embed, should_extract_graph, evidence_strength
- metadata_json (JSON string with model info, confidence, token counts)

## Verification

- Vector search confirmed working (cosine similarity)
- Self-lookup returns distance=0.0000
- Cross-chunk similarity ranges from 0.4 to 0.9
- All metadata fields correctly stored and retrievable

## Safety Checks

- ✅ Baseline collection `murata_e2e_murata_live_v1` was NOT modified
- ✅ No existing rebuild data was present (fresh creation)
- ✅ All records have run_id=murata_rebuild_v1
- ✅ All records have dataset=murata

## Generated At

2026-05-15T07:45:06.135496
