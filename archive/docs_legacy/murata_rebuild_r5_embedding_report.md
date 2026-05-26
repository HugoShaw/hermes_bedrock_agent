# Phase R5 — Embedding Report

## Summary

Generated embeddings for 51 candidates using Amazon Titan Embed Text V2.

## Configuration

| Parameter | Value |
|-----------|-------|
| Embedding Model | amazon.titan-embed-text-v2:0 |
| Provider | AWS Bedrock |
| Region | ap-northeast-1 |
| Dimension | 1024 |
| Normalize | True |
| Total Candidates | 51 |
| R3 Raw Chunks | 38 |
| R4 Summary Chunks | 13 |

## Results

| Metric | Value |
|--------|-------|
| Embeddings Generated | 51/51 |
| Failures | 0 |
| Total Input Tokens | 28243 |
| Avg Tokens/Chunk | 553 |
| Estimated Cost | ~$0.5649 (Titan V2 $0.02/1M tokens) |

## Input Breakdown

### R3 Raw Chunks (38)

Source types:
- Schema evidence (tables, DDL, field definitions)
- Code evidence (Java actions, services, SQL mappers)
- Process evidence (workflow descriptions, approval flows)
- Config evidence (system configuration)

### R4 Summary Chunks (13)

- 11 primary summaries (one per R3 candidate chunk)
- 1 semantic_map_summary (Q4 focused, multi-source)
- 1 oa_migration_summary (Q5 focused, multi-source)

## Quality Notes

- Zero failures across all 51 embedding calls
- All vectors are 1024-dimensional, normalized
- Token counts range from ~100 to ~1200 per chunk
- No truncation was needed (all within Titan V2's 8192 token limit)

## Generated At

2026-05-15T07:45:06.135371
