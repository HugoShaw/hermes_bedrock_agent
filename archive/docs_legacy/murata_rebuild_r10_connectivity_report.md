# R10 Neptune Connectivity Report

## Connectivity Check

| Check | Result |
|-------|--------|
| Endpoint | g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com |
| Graph ID | g-nbuyck5yl8 |
| Region | ap-northeast-1 |
| Auth | SigV4 (boto3 neptune-graph) |
| Ping | SUCCESS ✅ |
| Total nodes | 3054 (before import) |
| Total edges | 5146 (before import) |

## Pre-Import Rebuild Data

| Metric | Count | Source |
|--------|-------|--------|
| Existing rebuild nodes | 20 | R9 sample import |
| Existing rebuild edges | 10 | R9 sample import |

## Authentication

- Method: AWS SigV4 via boto3 `neptune-graph` service client
- Client: `hermes_bedrock_agent.clients.neptune_client.NeptuneClient`
- Credentials: IAM role (environment)
- Region: ap-northeast-1

## Connection Timing

- Ping latency: <100ms
- Query response: consistent sub-second for simple queries
- Import throughput: 44-46 ops/sec

## Notes

- Baseline (murata_live_v1) data intact: 3034 nodes
- MERGE+SET pattern confirmed idempotent — R9 data seamlessly updated
- No VPC/security group issues detected
