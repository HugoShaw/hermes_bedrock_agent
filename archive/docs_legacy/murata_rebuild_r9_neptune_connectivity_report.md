# R9 Neptune Connectivity Report

## Connectivity Check

| Check | Result |
|-------|--------|
| Endpoint | g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com |
| Graph ID | g-nbuyck5yl8 |
| Region | ap-northeast-1 |
| Auth Method | SigV4 (boto3 neptune-graph client) |
| Ping (RETURN 1) | SUCCESS ✅ |
| Total nodes in graph | 3,034 |
| Total edges in graph | 5,136 |

---

## Pre-Existing Rebuild Data

| Query | Result |
|-------|--------|
| rebuild nodes (run_id=murata_rebuild_v1) | 0 (clean state) |
| rebuild edges (run_id=murata_rebuild_v1) | 0 (clean state) |

Assessment: No prior rebuild data exists. MERGE import is safe to proceed.

---

## Baseline Verification

| Item | Status |
|------|--------|
| murata_live_v1 nodes | Untouched (part of 3,034 total) |
| murata_live_v1 edges | Untouched (part of 5,136 total) |
| Baseline collision risk | NONE |

---

## Client Configuration

```text
Client: boto3.client("neptune-graph", region_name="ap-northeast-1")
API: execute_query(graphIdentifier="g-nbuyck5yl8", queryString=..., parameters=..., language="OPEN_CYPHER")
Response: streaming payload → JSON
Timeout: default (boto3 managed)
```

---

## Network & Performance

- First query latency: ~200ms
- Subsequent queries: ~100-150ms
- No timeout issues
- No VPC/security group issues
- No IAM permission issues
