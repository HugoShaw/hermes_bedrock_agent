# Operation Guide

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   cd ~/projects/hermes_bedrock_agent
   uv sync --dev
   ```
3. Copy `.env.example` to `.env` and fill in values
4. Verify AWS credentials: `aws sts get-caller-identity`

## Running the Pipeline

### Dry-Run (no S3 access, no Neptune writes)

```bash
cd ~/projects/hermes_bedrock_agent
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --dry-run
```

### One-time Full Ingestion

```bash
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --once --prefix output/
```

### Incremental Sync (only new/changed files)

```bash
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --prefix output/ --once
```

### With File Limit

```bash
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --once --max-files 10
```

## Querying

### KB Query

```bash
uv run python scripts/run_kb_query.py "付款申請流程" --top-k 5
```

### Neptune Query

```bash
uv run python scripts/run_neptune_query.py "MATCH (n) RETURN n.name LIMIT 10"
```

## Monitoring

- Ingestion logs: `logs/ingestion.log`
- Error logs: `logs/errors.log`
- Artifacts: `data/artifacts/nodes.jsonl`, `data/artifacts/edges.jsonl`
- Registry: `data/registry/file_registry.jsonl`

## Cron Setup (Hermes Agent)

Schedule daily incremental sync:

```bash
# Every day at 2:00 AM
cd ~/projects/hermes_bedrock_agent
source .venv/bin/activate
python -m hermes_bedrock_agent.s3_graph_etl.jobs.incremental_sync
```

## Troubleshooting

1. **S3 access denied**: Check `aws s3 ls s3://<bucket>/` works
2. **Neptune connection failed**: Verify NEPTUNE_GRAPH_ID is correct
3. **Empty results**: Check S3_PREFIX matches your file paths
4. **Parser failures**: Check `logs/errors.log` for details
