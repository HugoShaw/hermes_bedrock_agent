# Murata Enterprise GraphRAG — Demo Summary

## System

| Component | Configuration |
|-----------|--------------|
| Vector Store | LanceDB (murata_e2e_murata_rebuild_v1, 51 records) |
| Graph DB | Neptune (g-nbuyck5yl8, 381 nodes, 703 edges) |
| Embedding | amazon.titan-embed-text-v2:0 (1024 dim) |
| LLM | jp.anthropic.claude-sonnet-4-6 |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |

## Results

| Question | Title | Score | Length | Latency |
|----------|-------|-------|--------|---------|
| Q1 | 应付管理业务流程 | 5/5 | 6162 | 57.4s |
| Q2 | JOURNAL_BASE 表分析 | 5/5 | 3843 | 37.9s |
| Q3 | 三表关联分析 (SUN_REQUEST / JOURNAL_BASE / RECEIVING_JOURNAL) | 5/5 | 4762 | 42.6s |
| Q4 | Semantic Map CSV 输出 | 5/5 | 1247 | 8.2s |
| Q5 | OA 审批迁移改造方案 | 5/5 | 9093 | 73.7s |

## Aggregate

| Metric | Value |
|--------|-------|
| Total Questions | 5 |
| Average Score | 5.0/5 |
| Total Latency | 219.8s |
| Average Latency | 44.0s |
| Pass Rate | 100% |

## Generated

- Timestamp: 2026-05-18T05:18:46.440535
- Source: R11 validated answers (cached)
