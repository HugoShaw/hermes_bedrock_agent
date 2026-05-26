# R11 Hybrid Retrieval Report

## Overview

| Item | Value |
|------|-------|
| Phase | R11: Hybrid Retrieval & QA Terminal Validation |
| Run ID | murata_rebuild_v1 |
| LanceDB Collection | murata_e2e_murata_rebuild_v1 (51 records) |
| Neptune Graph | g-nbuyck5yl8 (381 nodes, 703 edges) |
| Embedding Model | amazon.titan-embed-text-v2:0 (1024 dim) |
| Text Model | jp.anthropic.claude-sonnet-4-6 |
| Vector top_k | 10 |
| Graph depth | 2, max_edges=30 |

## Retrieval Performance

| Question | Vector Hits | Graph Entities | Graph Neighbors | Vec Latency | Graph Latency |
|----------|-------------|----------------|-----------------|-------------|---------------|
| Q1 | 10 | 8 | 56 | 0.14s | 0.29s |
| Q2 | 10 | 6 | 54 | 0.14s | 0.16s |
| Q3 | 10 | 14 | 148 | 0.15s | 0.33s |
| Q4 | 10 | 8 | 56 | 0.19s | 0.23s |
| Q5 | 10 | 15 | 86 | 0.14s | 0.39s |

## Fusion Strategy

- Method: Concatenation with source annotation
- Vector evidence: top-10 chunks with distance scores
- Graph evidence: Entity + neighbor expansion (2-hop)
- Context format: Markdown-structured with source labels

## Aggregates

- Avg vector retrieval: 0.151s
- Avg graph retrieval: 0.278s
- Total retrieval pipeline: 2.15s for 5 questions
