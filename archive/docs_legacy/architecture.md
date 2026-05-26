# Architecture

## Overview

hermes_bedrock_agent is a unified enterprise AI platform that provides:

1. **Bedrock Knowledge Base Query** (`kb/`) - Multi-KB parallel retrieval
2. **Neptune Analytics Graph Operations** (`graph/`) - openCypher read/write
3. **S3 Graph ETL** (`s3_graph_etl/`) - Document processing pipeline
4. **Semantic Map Workflow** (`semantic_map_workflow/`) - Experimental assets

## Pipeline Architecture

```
S3 Documents (PDF, DOCX, Code, Images, SQL)
         │
         ▼
┌─────────────────────┐
│  S3 Reader / Scanner │  sources/s3_reader.py
│  File Registry       │  sources/file_registry.py
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  File Router         │  parsers/file_router.py
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    ▼           ▼
┌────────┐ ┌──────────┐
│Trad.   │ │Multimodal│
│Parser  │ │LLM Parser│
│txt/md  │ │pdf/img   │
│code/sql│ │diagram   │
└────┬───┘ └────┬─────┘
     │          │
     └────┬─────┘
          ▼
┌─────────────────────┐
│  DocumentChunk[]     │  schemas.py
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Extractors          │
│  - Hierarchy         │  extractors/
│  - Relations         │
│  - Normalizer        │
│  - Evidence Builder  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Embeddings          │  embeddings/
│  - Bedrock Titan     │
│  - OpenAI            │
│  - Mock (dry-run)    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Graph Builder       │  graph_builder/
│  - Assemble nodes    │
│  - Assemble edges    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Graph Loader        │
│  - Neptune Analytics │  graph_builder/loader.py
│  - Artifact files    │  data/artifacts/
└─────────────────────┘
```

## Module Dependencies

- `config.py` - Central configuration (env vars + YAML)
- `kb/` - Independent, depends only on boto3 + config
- `graph/` - Independent Neptune client, depends on boto3 + config
- `s3_graph_etl/` - Main pipeline, depends on all above
- `cli.py` - Entry point, depends on all modules

## Key Design Decisions

1. **Pluggable parsers** - BaseParser ABC, FileRouter dispatches by extension
2. **Pluggable LLM** - BaseLLMClient ABC, factory function for provider selection
3. **Pluggable embeddings** - BaseEmbedder ABC, Bedrock/OpenAI/Mock implementations
4. **Dry-run first** - All operations support dry-run with mock components
5. **Incremental processing** - FileRegistry tracks ETags for change detection
6. **Evidence tracking** - Every node/edge must have source_uri + evidence_text
