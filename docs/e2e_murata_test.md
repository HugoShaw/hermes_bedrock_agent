# E2E Murata Pipeline Test Guide

## Overview

Full end-to-end pipeline for processing the Murata enterprise dataset:
- **Source**: `s3://s3-hulftchina-rd/Murata/` (~263 files: Java, SQL, Excel, Word, PowerPoint, Markdown)
- **Pipeline**: scan → parse → chunk → embed → graph → load → retrieval → visualization
- **Vector Store**: LanceDB (local)
- **Graph Store**: Neptune Analytics (live)
- **Models**: Bedrock Titan Embed v2, Claude 3.5 Sonnet (extraction + generation)

## Prerequisites

```bash
# 1. AWS credentials configured
aws sts get-caller-identity

# 2. Python environment
cd ~/projects/hermes_bedrock_agent
source .venv/bin/activate

# 3. Required packages
uv pip install python-docx python-pptx openpyxl PyMuPDF lancedb

# 4. Verify S3 access
aws s3 ls s3://s3-hulftchina-rd/Murata/ --summarize | tail -5

# 5. Verify Bedrock access
aws bedrock list-foundation-models --region ap-northeast-1 | grep titan-embed
```

## Quick Start

### Full Pipeline (all stages)

```bash
python scripts/run_e2e_murata_pipeline.py \
    --stage all \
    --run-id murata_full_vlm_live_001 \
    --enable-vlm \
    --live-neptune \
    --confirm-live-write \
    --skip-existing
```

### Stage by Stage

```bash
# Stage 1: Scan S3
python scripts/run_e2e_murata_pipeline.py --stage scan

# Stage 2: Parse documents (VLM enabled for images/PDF)
python scripts/run_e2e_murata_pipeline.py --stage parse --enable-vlm

# Stage 3: Chunk
python scripts/run_e2e_murata_pipeline.py --stage chunk

# Stage 4: Embed + LanceDB write
python scripts/run_e2e_murata_pipeline.py --stage embedding --skip-existing

# Stage 5: Graph extraction (Claude)
python scripts/run_e2e_murata_pipeline.py --stage graph --skip-existing

# Stage 6: Load to Neptune
python scripts/run_e2e_murata_pipeline.py --stage load --live-neptune --confirm-live-write

# Stage 7: Retrieval demo
python scripts/run_e2e_murata_pipeline.py --stage retrieval --live-neptune

# Stage 8: Visualization
python scripts/run_e2e_murata_pipeline.py --stage visualization --live-neptune
```

### Resume After Failure

```bash
# Resume with skip-existing (won't re-process completed items)
python scripts/run_e2e_murata_pipeline.py --stage all --skip-existing --resume

# Resume specific stage
python scripts/run_e2e_murata_pipeline.py --stage embedding --skip-existing
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--stage` | `all` | Stage to run: scan, parse, chunk, embedding, graph, load, retrieval, visualization, all |
| `--run-id` | `murata_full_vlm_live_001` | Run identifier (used in artifact paths and LanceDB collection) |
| `--enable-vlm` | `True` | Enable VLM (Bedrock multimodal) for image/PDF page analysis |
| `--no-vlm` | `False` | Disable VLM parsing |
| `--live-neptune` | `False` | Enable live Neptune queries/writes |
| `--confirm-live-write` | `False` | Safety flag: confirm Neptune write (required with --live-neptune) |
| `--neptune-endpoint` | `g-nbuyck5yl8...` | Neptune Analytics endpoint |
| `--resume` | `False` | Resume from checkpoint |
| `--skip-existing` | `False` | Skip items already in artifact files |
| `--fail-fast` | `False` | Halt on first error |
| `--lancedb-path` | `~/projects/data/vector_store/lancedb` | LanceDB storage path |
| `--vector-store-backend` | `lancedb` | Vector store backend |

## Artifact Output

All artifacts are written to:
```
~/projects/data/enterprise_graphrag/runs/{run_id}/artifacts/
```

### Stage 1: Scan
- `documents.jsonl` — S3 file inventory (document_id, source_uri, source_type, file_size)
- `file_inventory_report.json` — type distribution, total bytes, scan metadata

### Stage 2: Parse
- `normalized_documents.jsonl` — parsed documents with sections
- `visual_blocks.jsonl` — VLM analysis results (architecture diagrams, screenshots)
- `parser_failed.jsonl` — files that failed parsing (with error details)

### Stage 3: Chunk
- `chunks.jsonl` — chunked text segments (chunk_id, content, section_title, page)
- `chunk_stats.json` — chunk count, type distribution, avg chunks/doc

### Stage 4: Embedding
- `embeddings.jsonl` — chunk embeddings (chunk_id, embedding[1024])
- `lancedb_load_report.json` — LanceDB write stats (collection, record count)

### Stage 5: Graph
- `raw_entities.jsonl` — raw extracted entities (before normalization)
- `raw_relations.jsonl` — raw extracted relations
- `raw_evidence.jsonl` — extraction evidence
- `entities.jsonl` — normalized, quality-reviewed entities
- `relations.jsonl` — accepted relations
- `pending_relations.jsonl` — relations with borderline confidence
- `rejected_relations.jsonl` — rejected relations (self-loops, bad types, etc.)
- `graph_quality_report.json` — extraction statistics

### Stage 6: Load
- `neptune_import.cypher` — all Cypher queries (audit trail)
- `neptune_load_report.json` — load results (nodes/edges loaded, errors)
- `load_verification_report.md` — verification queries and entity type distribution

### Stage 7: Retrieval
- `fused_context_examples.jsonl` — fused retrieval results for demo queries
- `answer_examples.jsonl` — generated answers with citations
- `retrieval_live_examples.jsonl` — retrieval statistics per query

### Stage 8: Visualization
- `mermaid_examples.md` — Mermaid diagrams (local + Neptune live)

### Final Reports
- `murata_e2e_quality_report.md` — full pipeline summary
- `cleanup_commands.md` — commands to clean up all created resources

## Verification

### LanceDB Verification

```python
import lancedb

db = lancedb.connect("~/projects/data/vector_store/lancedb")
print("Tables:", db.table_names())

tbl = db.open_table("murata_e2e_murata_full_vlm_live_001")
print(f"Records: {len(tbl)}")
print(f"Schema: {tbl.schema}")

# Sample query
import numpy as np
results = tbl.search(np.random.randn(1024).tolist()).limit(5).to_list()
for r in results:
    print(f"  {r['chunk_id']}: {r['text'][:60]}...")
```

### Neptune Verification

```cypher
-- Count all nodes
MATCH (n) RETURN count(n) AS total_nodes

-- Count by label
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC

-- Count edges
MATCH ()-[r]->() RETURN count(r) AS total_edges

-- Sample: find entity by name
MATCH (n) WHERE n.name CONTAINS '仕訳' RETURN n LIMIT 5

-- Sample: find relationships
MATCH (a)-[r]->(b) WHERE a.name CONTAINS '付款' RETURN a.name, type(r), b.name LIMIT 10
```

### Query Demo

```bash
# Simple query (LanceDB only)
python scripts/query_demo.py --no-neptune "仕訳基礎テーブルの構造は？"

# Hybrid query (LanceDB + Neptune)
python scripts/query_demo.py "付款申請の承認フローはどのように動作しますか"

# Skip answer generation (retrieval only)
python scripts/query_demo.py --no-answer "PaymentReqActionの機能"
```

### Mermaid Export

```bash
# From local artifacts
python scripts/export_mermaid.py --from-artifacts --center-entity "仕訳基礎"

# From live Neptune
python scripts/export_mermaid.py --center-entity "PaymentReqAction" --depth 3

# Save to file
python scripts/export_mermaid.py --from-artifacts --output ~/graph.md
```

## Cleanup

**IMPORTANT:** Always verify before deleting Neptune data.

### Quick Cleanup

```bash
# Delete local artifacts only
rm -rf ~/projects/data/enterprise_graphrag/runs/murata_full_vlm_live_001/

# Delete LanceDB collection
python -c "
import lancedb
db = lancedb.connect('$HOME/projects/data/vector_store/lancedb')
db.drop_table('murata_e2e_murata_full_vlm_live_001')
print('Dropped LanceDB collection')
"
```

### Neptune Cleanup

```cypher
-- WARNING: Review carefully before executing
-- Delete all graph data (only for test graphs!)

-- Step 1: Delete edges
MATCH ()-[r]->() WHERE r.relation_id IS NOT NULL DELETE r

-- Step 2: Delete nodes
MATCH (n) WHERE n.entity_id IS NOT NULL DELETE n
```

### Full Cleanup Script

See `artifacts/cleanup_commands.md` for the complete cleanup procedure generated by the pipeline.

## Troubleshooting

### Common Issues

1. **S3 Access Denied**: Check IAM role/profile has s3:GetObject + s3:ListBucket for `s3-hulftchina-rd`
2. **Bedrock ThrottlingException**: Reduce batch size or add delays. The pipeline has 0.5s delay between embedding batches and 1s between graph extraction calls.
3. **LanceDB Table Not Found**: Run embedding stage first. Collection is created on first write.
4. **Neptune Connection Timeout**: Verify VPC/security group allows access to Neptune endpoint from current machine.
5. **DOCX/PPTX parse failure**: Install `python-docx` and `python-pptx`. These are optional deps.
6. **PDF parse failure**: Install `PyMuPDF` (`pip install PyMuPDF`).

### Log Location

Pipeline logs to stderr with the hermes_bedrock_agent logger. To capture:
```bash
python scripts/run_e2e_murata_pipeline.py --stage all 2>&1 | tee logs/e2e_run.log
```

## Architecture

```
S3 (Murata/)
    │
    ▼
┌─────────┐    ┌──────────┐    ┌─────────┐
│  SCAN   │───▶│  PARSE   │───▶│  CHUNK  │
│ (S3 ls) │    │(+VLM img)│    │(struct) │
└─────────┘    └──────────┘    └─────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                                  ▼
           ┌──────────────┐                  ┌──────────────┐
           │  EMBEDDING   │                  │    GRAPH     │
           │(Titan + Lance)│                  │(Claude extr) │
           └──────────────┘                  └──────────────┘
                    │                                  │
                    ▼                                  ▼
           ┌──────────────┐                  ┌──────────────┐
           │   LanceDB    │                  │   Neptune    │
           │  (vectors)   │                  │  (entities)  │
           └──────────────┘                  └──────────────┘
                    │                                  │
                    └──────────────┬───────────────────┘
                                   ▼
                          ┌──────────────┐
                          │  RETRIEVAL   │
                          │ (hybrid RRF) │
                          └──────────────┘
                                   │
                                   ▼
                          ┌──────────────┐
                          │  GENERATION  │
                          │(Claude + cit)│
                          └──────────────┘
                                   │
                                   ▼
                          ┌──────────────┐
                          │VISUALIZATION │
                          │(Mermaid/RF)  │
                          └──────────────┘
```
