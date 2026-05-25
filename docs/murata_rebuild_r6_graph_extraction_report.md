# R6 Graph Extraction Report

## Phase Summary

| Item | Value |
|------|-------|
| Phase | R6: Graph Extraction |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |
| Model | jp.anthropic.claude-sonnet-4-6 |
| Region | ap-northeast-1 |
| Extraction Date | 2025-05-15 |

## Input

- **Total candidates**: 51 (from R4 embedding_input_candidates_r4.jsonl)
- **Selected for extraction**: 46 chunks (should_extract_graph=true)
- **Excluded**: 5 chunks (config/visual only, no graph value)
- **R4 summaries**: 13 (priority extraction)
- **R3 raw chunks**: 33

## Extraction Execution

| Metric | Value |
|--------|-------|
| Total batches | 23 (2 chunks/batch) |
| First-pass success | 9/23 |
| First-pass failures | 14/23 (Bedrock timeouts) |
| Retry success | 14/14 (with 600s read_timeout) |
| Final success rate | 23/23 (100%) |
| Total input tokens | 39,535 |
| Total output tokens | 181,471 |
| Estimated cost | ~$2.84 |
| Avg batch time | ~85s |

## Root Cause of Initial Failures

The default boto3 read_timeout (60s) was insufficient for Claude Sonnet's graph extraction output (avg ~8000 output tokens per batch). Setting `read_timeout=600` in botocore Config resolved all failures on retry.

## Extraction Results

| Category | Count |
|----------|-------|
| Raw entities | 859 |
| Unique entities (name+type) | 383 |
| Raw relations | 1,044 |
| Clean relations | 1,044 |
| Suspicious relations | 0 |
| Raw evidence records | 181 |
| Extraction failures | 0 |
| Dedup candidate groups | 140 |

## Entity Type Distribution

| Type | Count | % |
|------|-------|---|
| Column | 221 | 25.7% |
| Table | 117 | 13.6% |
| Method | 90 | 10.5% |
| BusinessStep | 50 | 5.8% |
| Field | 44 | 5.1% |
| Status | 43 | 5.0% |
| EnumValue | 42 | 4.9% |
| ExternalSystem | 36 | 4.2% |
| Class | 31 | 3.6% |
| Action | 28 | 3.3% |
| View | 27 | 3.1% |
| Module | 23 | 2.7% |
| BusinessProcess | 21 | 2.4% |
| Service | 19 | 2.2% |
| ServiceImpl | 18 | 2.1% |
| BusinessObject | 17 | 2.0% |
| System | 13 | 1.5% |
| Interface | 9 | 1.0% |
| Report | 6 | 0.7% |
| API | 4 | 0.5% |

## Relation Type Distribution

| Type | Count | % |
|------|-------|---|
| contains | 252 | 24.1% |
| has_field | 145 | 13.9% |
| reads_from | 101 | 9.7% |
| writes_to | 80 | 7.7% |
| flows_to | 58 | 5.6% |
| has_status | 55 | 5.3% |
| transitions_to | 51 | 4.9% |
| calls | 51 | 4.9% |
| joins_on | 45 | 4.3% |
| generates | 35 | 3.4% |
| updates | 33 | 3.2% |
| relates_to | 28 | 2.7% |
| supports | 26 | 2.5% |
| depends_on | 25 | 2.4% |
| references | 19 | 1.8% |
| maps_to | 12 | 1.1% |
| belongs_to | 11 | 1.1% |
| exports | 8 | 0.8% |
| imports | 3 | 0.3% |
| implements | 3 | 0.3% |
| approves | 2 | 0.2% |
| rejects | 1 | 0.1% |

## Key Quality Indicators

- **custom relation count**: 0 ✅
- **relates_to percentage**: 2.7% (not dominant) ✅
- **Zero extraction failures** ✅
- **Zero suspicious relations** ✅
- **All 22 allowed relation types used** ✅

## Scope Compliance

| Forbidden Operation | Status |
|--------------------|--------|
| Neptune query/write | Not executed ✅ |
| LanceDB write | Not executed ✅ |
| Embedding generation | Not executed ✅ |
| VLM calls | Not executed ✅ |
| QA terminal | Not executed ✅ |
| Final answers | Not generated ✅ |
| Baseline data deletion | Not performed ✅ |

## Recommendations

1. Proceed to R7 for normalization, dedup, and integrity checking
2. The 140 dedup candidate groups (reducing 859 → 383 unique entities) need R7 resolution
3. Q4 semantic map path is strong (8-node continuous chain)
4. All 5 target questions have full entity coverage
