# R10 Import Failures Report

## Summary

**ZERO FAILURES** — All import operations completed successfully.

---

## Node Import

| Metric | Value |
|--------|-------|
| Nodes attempted | 381 |
| Nodes succeeded | 381 |
| Nodes failed | 0 |
| Success rate | 100% |
| Import time | 8.3 seconds |
| Throughput | 45.8 nodes/sec |

## Edge Import

| Metric | Value |
|--------|-------|
| Edges attempted | 703 |
| Edges succeeded | 703 |
| Edges failed | 0 |
| Success rate | 100% |
| Import time | 16.0 seconds |
| Throughput | 44.0 edges/sec |

## R9 Duplicate Cleanup

| Metric | Value |
|--------|-------|
| Duplicate edges detected | 10 |
| Duplicates cleaned | 10 |
| Cause | R9 sample import used different MERGE key pattern |
| Resolution | Removed older R9 copies, kept R10 canonical edges |

## Retry Statistics

| Metric | Value |
|--------|-------|
| Max retries per operation | 3 |
| Operations needing retry | 0 |
| Total retries executed | 0 |

## Error Classification

No errors encountered. All 1,084 operations (381 nodes + 703 edges) succeeded on first attempt.
