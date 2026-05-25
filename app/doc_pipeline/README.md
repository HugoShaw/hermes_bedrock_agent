# doc_pipeline

Standardised document parsing pipeline that converts S3-hosted Excel (and PDF) documents
into a searchable knowledge base: LanceDB vector store + Neptune Analytics graph.

```
S3 source → Download → Sheet/Page splitting → PDF/Image rendering
→ Tiling → VLM parsing → Markdown → Chunking → LanceDB embedding → Neptune graph
```

## Quick start

```bash
# Start LibreOffice listener first (required for Excel conversion)
soffice --headless --invisible --nocrashreport --nodefault --nofirststartwizard \
  "--accept=socket,host=localhost,port=2002;urp;StarOffice.ServiceManager" &
sleep 8

# Full pipeline from S3 prefix
/usr/bin/python3 -m app.doc_pipeline \
  --s3-prefix "サンプル20260519/" \
  --output-dir outputs/run_20260525/

# Single local file
/usr/bin/python3 -m app.doc_pipeline \
  --file /tmp/workbook.xlsx \
  --output-dir outputs/test/

# Parse only (no KB ingestion)
/usr/bin/python3 -m app.doc_pipeline \
  --file /tmp/workbook.xlsx \
  --output-dir outputs/test/ \
  --stages parse

# Ingest from existing parsed markdown
/usr/bin/python3 -m app.doc_pipeline \
  --parsed-dir outputs/test/workbook/vlm_parsed \
  --stages ingest \
  --replace

# Incremental — skip already-processed workbooks
/usr/bin/python3 -m app.doc_pipeline \
  --s3-prefix "サンプル20260519/" \
  --output-dir outputs/incremental/ \
  --incremental

# Inject authoritative Mermaid flowchart for sheet 2
/usr/bin/python3 -m app.doc_pipeline \
  --file /tmp/workbook.xlsx \
  --output-dir outputs/test/ \
  --ground-truth flowchart.mmd \
  --sheet 2
```

> **Note:** Excel→PDF conversion uses LibreOffice UNO bindings.
> Always invoke with `/usr/bin/python3`, never a venv Python.

## Stage flags

| `--stages` value | Runs |
|---|---|
| `all` (default) | All stages end-to-end |
| `parse` | S3 discovery → Excel→PDF → Image rendering → VLM → Markdown post |
| `ingest` | Chunking → Vector embedding → Neptune graph |
| `images` | Only PDF and image generation (for visual review) |
| `vlm` | Only VLM parsing on existing images |

## Write modes

| Flag | Behaviour |
|---|---|
| _(none)_ | Append new chunks to existing LanceDB table |
| `--replace` | Delete rows for this workbook, then add |
| `--rebuild` | Drop and recreate the entire table |

## Package layout

```
app/doc_pipeline/
├── __init__.py          # exports run_pipeline
├── __main__.py          # CLI entry point
├── config.py            # PipelineConfig dataclass
├── models.py            # Pydantic models
├── stages/
│   ├── s3_discovery.py  # Stage 1: scan S3, build WorkManifest
│   ├── excel_to_pdf.py  # Stage 2: LibreOffice UNO per-sheet PDF export
│   ├── pdf_to_image.py  # Stage 3: adaptive-DPI render + tile generation
│   ├── vlm_parse.py     # Stage 4: Claude Sonnet multimodal parsing
│   ├── markdown_post.py # Stage 5: Mermaid injection, H1 normalisation
│   ├── chunker.py       # Stage 6: semantic heading-based chunking
│   ├── vector_embed.py  # Stage 7: Titan Embed V2 → LanceDB
│   └── graph_ingest.py  # Stage 8: entity extraction → Neptune
├── runners/
│   ├── full_pipeline.py # End-to-end orchestration
│   └── incremental.py   # Skip already-processed files
└── utils/
    ├── libreoffice.py   # UNO connection management
    ├── bedrock_client.py# Converse API wrapper (text + multimodal)
    ├── image_ops.py     # PIL tiling, stitching, resizing
    └── s3_ops.py        # S3 download/upload helpers
```

## Programmatic usage

```python
from app.doc_pipeline import run_pipeline

summary = run_pipeline(
    xlsx_path="/tmp/workbook.xlsx",
    output_dir="outputs/test/",
    stages="all",
    mode="replace",
)
print(summary)
```

## Key implementation notes

1. **Never parallelize VLM calls** — concurrent Bedrock requests cause cascading timeouts.
2. **Image bytes for Bedrock** — raw bytes, NOT base64. The SDK handles encoding.
3. **Neptune parameterized queries** — all Cypher uses `$param` placeholders.
4. **PIL MAX_IMAGE_PIXELS** — set to 500_000_000 before any image ops.
5. **Bedrock read_timeout** — 600 s for large VLM responses (~8 K output tokens).
6. **Adaptive DPI** — sheets > 3000 mm wide: DPI=36; normal A3: DPI=150.
7. **LanceDB schema** — must match `app/dual_rag/vector_store_loader.py` exactly.
8. **Graph ingest** — delegates to `app.dual_rag.graph_builder.build_graph` for consistency.

## Configuration

All settings are loaded from the project `.env` file.  The most important variables:

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `ap-northeast-1` | AWS region |
| `S3_BUCKET` | `s3-hulftchina-rd` | S3 bucket name |
| `BEDROCK_VLM_MODEL_ID` | `jp.anthropic.claude-sonnet-4-6` | Claude Sonnet model for VLM |
| `BEDROCK_EMBED_MODEL_ID` | `amazon.titan-embed-text-v2:0` | Embedding model |
| `VECTOR_LOCAL_STORE_PATH` | `/home/ubuntu/projects/data/vector_store/lancedb` | LanceDB path |
| `NEPTUNE_GRAPH_ID` | _(empty)_ | Neptune Analytics graph ID |
