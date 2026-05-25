# R11 Debug Trace Report

## Pipeline Steps (per question)

```
user_question → entity_extraction → vector_retrieval(top_k=10) → graph_retrieval(depth=2) → context_fusion → answer_generation → evaluation
```

## Traces

### Q1

| Step | Result | Latency |
|------|--------|---------|
| Entity Extraction | 0 entities, 6 terms | <1ms |
| Vector Retrieval | 10 hits | 0.137s |
| Graph Retrieval | 8 entities, 56 neighbors | 0.287s |
| Context Fusion | 18 items | <1ms |
| Answer Generation | 6162 chars | 56.93s |
| Evaluation | Score 5/5 PASS | <1ms |
| **Total** | — | **57.35s** |

### Q2

| Step | Result | Latency |
|------|--------|---------|
| Entity Extraction | 1 entities, 3 terms | <1ms |
| Vector Retrieval | 10 hits | 0.140s |
| Graph Retrieval | 6 entities, 54 neighbors | 0.160s |
| Context Fusion | 16 items | <1ms |
| Answer Generation | 3843 chars | 37.60s |
| Evaluation | Score 5/5 PASS | <1ms |
| **Total** | — | **37.90s** |

### Q3

| Step | Result | Latency |
|------|--------|---------|
| Entity Extraction | 3 entities, 5 terms | <1ms |
| Vector Retrieval | 10 hits | 0.153s |
| Graph Retrieval | 14 entities, 148 neighbors | 0.332s |
| Context Fusion | 24 items | <1ms |
| Answer Generation | 4762 chars | 42.10s |
| Evaluation | Score 5/5 PASS | <1ms |
| **Total** | — | **42.58s** |

### Q4

| Step | Result | Latency |
|------|--------|---------|
| Entity Extraction | 3 entities, 5 terms | <1ms |
| Vector Retrieval | 10 hits | 0.190s |
| Graph Retrieval | 8 entities, 56 neighbors | 0.227s |
| Context Fusion | 18 items | <1ms |
| Answer Generation | 1247 chars | 7.82s |
| Evaluation | Score 5/5 PASS | <1ms |
| **Total** | — | **8.24s** |

### Q5

| Step | Result | Latency |
|------|--------|---------|
| Entity Extraction | 5 entities, 5 terms | <1ms |
| Vector Retrieval | 10 hits | 0.136s |
| Graph Retrieval | 15 entities, 86 neighbors | 0.386s |
| Context Fusion | 25 items | <1ms |
| Answer Generation | 9093 chars | 73.22s |
| Evaluation | Score 5/5 PASS | <1ms |
| **Total** | — | **73.74s** |

