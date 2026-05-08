# hermes_bedrock_agent

Enterprise AI platform for Bedrock KB query, S3 document ETL, multimodal parsing, Semantic Map, and Neptune Analytics GraphRAG.

## Project Positioning

This is a unified enterprise knowledge processing platform that supports:
- **Bedrock Knowledge Base** multi-KB parallel retrieval
- **S3 Enterprise Document** scanning and incremental processing
- **Multimodal Document Parsing** (PDF, images, diagrams, code, SQL)
- **Semantic Map / Graph Data** generation with entity/relation extraction
- **Neptune Analytics** graph data write and vector search
- **GraphRAG / Knowledge Q&A / Process Generation** infrastructure

## Directory Structure

```
hermes_bedrock_agent/
  .env                          # Environment configuration
  .env.example                  # Configuration template
  pyproject.toml                # Project metadata and dependencies
  uv.lock                       # Locked dependencies

  docs/                         # Documentation
    architecture.md             # System architecture
    graph_schema.md             # Graph node/edge schema
    operation_guide.md          # Running and monitoring

  configs/                      # YAML configuration files
    graph_schema.yaml           # Valid node labels and edge types
    ingestion.yaml              # Pipeline settings
    llm.yaml                    # LLM provider configuration

  src/hermes_bedrock_agent/     # Main package
    config.py                   # Unified configuration
    cli.py                      # Typer CLI entry point

    kb/                         # Bedrock Knowledge Base query
      bedrock_kb_client.py      # Single + Multi-KB clients
      kb_query.py               # High-level query functions

    graph/                      # Neptune Analytics operations
      neptune_client.py         # openCypher client
      cypher_templates.py       # Query templates
      query_examples.cypher     # Example queries

    s3_graph_etl/               # S3 → Parse → Graph pipeline
      schemas.py                # Pydantic models (DocumentChunk, GraphNode, GraphEdge)
      sources/                  # S3 scanning and file tracking
      parsers/                  # File parsing (text, code, PDF, DOCX, image)
      llm/                      # Multimodal LLM clients
      extractors/               # Entity/relation extraction
      embeddings/               # Embedding providers (Bedrock, OpenAI, Mock)
      graph_builder/            # Graph assembly and loading
      jobs/                     # Job runners (ingestion, incremental sync)

  scripts/                      # Standalone scripts
    run_s3_graph_etl.py
    run_kb_query.py
    run_neptune_query.py

  semantic_map_workflow/         # Existing experimental assets

  data/                         # Data directory
    raw/                        # Raw downloaded files
    processed/                  # Processed intermediates
    registry/                   # File processing registry
    artifacts/                  # Output artifacts (nodes.jsonl, edges.jsonl)

  logs/                         # Log files
  tests/                        # Pytest test suite
```

## Setup

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS credentials configured (`~/.aws/credentials` or env vars)

### Install Dependencies

```bash
cd ~/projects/hermes_bedrock_agent
uv sync --dev
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your values:
#   - AWS_REGION
#   - BEDROCK_KNOWLEDGE_BASES (or BEDROCK_KNOWLEDGE_BASE_ID)
#   - S3_BUCKET, S3_PREFIX
#   - NEPTUNE_GRAPH_ID
#   - EMBEDDING_PROVIDER, EMBEDDING_MODEL_ID, EMBEDDING_DIMENSION
#   - VISION_LLM_PROVIDER, VISION_LLM_MODEL_ID
#   - DRY_RUN=true (start with dry-run)
```

## Running

### Dry-Run (no AWS calls, generates sample artifacts)

```bash
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --dry-run
```

Output: `data/artifacts/nodes.jsonl` and `data/artifacts/edges.jsonl`

### Real S3 Ingestion

```bash
# Set DRY_RUN=false in .env, or:
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --once --prefix output/
```

### Write to Neptune

```bash
# Ensure NEPTUNE_GRAPH_ID is set in .env
# Set DRY_RUN=false
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion --once
```

### Incremental Sync

```bash
uv run python -m hermes_bedrock_agent.s3_graph_etl.jobs.incremental_sync
```

### KB Query

```bash
uv run python scripts/run_kb_query.py "付款申請流程" --top-k 5
```

### Neptune Query

```bash
uv run python scripts/run_neptune_query.py "MATCH (n) RETURN n.name LIMIT 10"
```

## query_examples.cypher

Located at `src/hermes_bedrock_agent/graph/query_examples.cypher`. Contains:
1. Query all relationships
2. Query nodes by name (payment/付款)
3. One-hop neighbor query
4. Two-hop traversal
5. Vector similarity top-k
6. GraphRAG (vector + graph traversal)

Usage:
```bash
uv run python scripts/run_neptune_query.py --file src/hermes_bedrock_agent/graph/query_examples.cypher
```

## Hermes Cron Scheduled Execution

Daily incremental sync at 2:00 AM:

```bash
cd ~/projects/hermes_bedrock_agent
source .venv/bin/activate
python -m hermes_bedrock_agent.s3_graph_etl.jobs.incremental_sync
```

Requirements:
- Only processes new/changed files (based on ETag comparison)
- Outputs: `data/artifacts/nodes.jsonl` and `edges.jsonl`
- Failures logged to: `logs/errors.log`
- Does NOT auto-modify code

## Tests

```bash
uv run pytest
```

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run linter
uv run ruff check src/

# Run tests
uv run pytest -v
```
