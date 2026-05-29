# Graph Pipeline Refactoring Report

## What Was Reviewed

Reviewed the full DualRAG project at `~/projects/hermes_bedrock_agent/`, focusing on:

1. `src/hermes_bedrock_agent/knowledge_base/graph_extractor.py` (630 lines) — LLM-based extraction
2. `src/hermes_bedrock_agent/knowledge_base/graph_loader.py` (238 lines) — Neptune loader
3. `src/hermes_bedrock_agent/clients/neptune.py` (88 lines) — Neptune client
4. `src/hermes_bedrock_agent/clients/bedrock.py` (119 lines) — Bedrock Converse client
5. `src/hermes_bedrock_agent/cli.py` — CLI entry points
6. `scripts/demo_graph_extraction.py` — Demo script
7. Previous `/tmp/semantic_map_*` outputs from earlier ad-hoc extraction sessions

## What Old Pipeline / Legacy Logic Existed

### Old `knowledge_base/graph_extractor.py`
- Two-pass LLM extraction: "Business Semantic Graph" + "Implementation Graph"
- Tightly coupled to `Chunk` objects (requires S3 paths, document URLs)
- Hardcoded system names (ANDPAD, SAP, DataSpider) in keyword extraction
- No project-level cross-sheet understanding
- No ID registry or deduplication

### Old `knowledge_base/graph_loader.py`
- Loads one query at a time with no batching
- No preflight validation
- No post-load verification
- No dry-run output file generation
- No retry/backoff for throttling

### Previous Semantic Map Build (ad-hoc)
- Done manually in /tmp/ during previous sessions
- Not integrated into the codebase
- Good schema reference (nodes.jsonl/edges.jsonl format) but not reusable

## What Was Added / Changed

### New: `src/hermes_bedrock_agent/graph_pipeline/` (9 files)

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 163 | Public API: `run_pipeline()`, orchestrates all steps |
| `config.py` | 45 | `GraphPipelineConfig` dataclass with env var defaults |
| `schemas.py` | 127 | Pydantic models: PipelineNode, PipelineEdge, RawNode, RawEdge, ExtractionResult, ProjectInventory |
| `scanner.py` | 85 | Walks project dir, finds vlm_parsed/ dirs, inventories .md files |
| `extractor.py` | 296 | Generic LLM-based extraction with project context, truncated JSON recovery |
| `normalizer.py` | 299 | ID registry, cross-sheet deduplication, edge resolution |
| `cypher_gen.py` | 153 | Generates Neptune-compatible MERGE statements + JSONL debug files |
| `loader.py` | 169 | Execute Cypher with retry/backoff, batch loading, dry-run support |
| `validator.py` | 138 | Pre-flight checks (dangling edges, illegal chars) + post-load verification |

### Modified: `src/hermes_bedrock_agent/cli.py`
- Added `dualrag graph` command (new primary entry point for graph pipeline)

### Modified: Legacy files (deprecation notices only)
- `knowledge_base/graph_extractor.py` — Added [LEGACY] deprecation header
- `knowledge_base/graph_loader.py` — Added [LEGACY] deprecation header

## How to Run the New Graph Pipeline

### CLI (recommended):

```bash
cd ~/projects/hermes_bedrock_agent
source .venv/bin/activate

# Dry-run (generates files but does not load to Neptune):
dualrag graph outputs/サンプル20260519 --project-id sample_20260519 --dry-run

# Full run (extract + load to Neptune):
dualrag graph outputs/サンプル20260519 --project-id sample_20260519

# With custom Neptune endpoint:
dualrag graph outputs/14_債務奉行クラウド \
  --project-id saimu_bugyo_cloud \
  --neptune-graph-id g-xxxxxxxxxx \
  --delay 3.0

# Point to specific output directory:
dualrag graph outputs/サンプル20260519 --project-id sample_20260519 -o /tmp/my_output
```

### Python API:

```python
from hermes_bedrock_agent.graph_pipeline import run_pipeline, GraphPipelineConfig

cfg = GraphPipelineConfig(
    project_id="sample_20260519",
    project_name="サンプル20260519",
    dry_run=False,
    neptune_graph_id="g-xxxxxxxxxx",
)
result = run_pipeline("outputs/サンプル20260519", cfg)
print(result.summary)
```

## How Data Is Loaded Into Neptune

1. **Scan**: Walks project dir, finds all `vlm_parsed/*.md` files
2. **Extract**: Sends each markdown to Claude Sonnet via Bedrock Converse API with project context
3. **Normalize**: Builds ID registry, deduplicates same-name entities across sheets
4. **Validate**: Pre-flight checks (no dangling edges, no empty source_file, no illegal label chars)
5. **Generate**: Writes `.cypher` and `.jsonl` files to output directory
6. **Load**: Executes MERGE statements against Neptune with retry/backoff
7. **Verify**: Queries Neptune to confirm node/edge counts match expectations

All nodes use MERGE with `{id, project_id}` as the key — fully idempotent.
All edges use MATCH on both endpoints + MERGE on relationship type.

## How to Verify the Result

### Check output files:
```bash
ls outputs/サンプル20260519/graph_output/
# sample_20260519_nodes.jsonl      — extracted nodes
# sample_20260519_edges.jsonl      — extracted edges
# sample_20260519_nodes.cypher     — Neptune MERGE statements for nodes
# sample_20260519_edges.cypher     — Neptune MERGE statements for edges
# sample_20260519_registry.json    — ID registry (raw → canonical mapping)
# sample_20260519_pipeline_summary.json — run statistics
```

### Verify in Neptune:
```cypher
-- Count nodes for project
MATCH (n {project_id: 'sample_20260519'}) RETURN count(n) AS nodes

-- Count edges for project
MATCH (a {project_id: 'sample_20260519'})-[r]->(b) RETURN count(r) AS edges

-- Check isolated nodes
MATCH (n {project_id: 'sample_20260519'}) WHERE NOT (n)--() RETURN n.id, n.name

-- Check system connections
MATCH (a:System {project_id: 'sample_20260519'})-[r]->(b:System) RETURN a.name, type(r), b.name
```

### Post-load verification is automatic:
The pipeline runs `post_load_verify()` after loading, which checks:
- actual node count >= expected
- actual edge count >= expected
- count of isolated nodes

## Test Results

Tested with `outputs/サンプル20260519/wb2_flowchart` (2 markdown files):

- **Input**: 2 markdown files (sheet_01.md, sheet_02.md)
- **Extraction**: 13 nodes, 18 edges from sheet_01 (sheet_02 hit truncation, partially recovered)
- **After normalization**: 12 unique nodes, 16 edges (1 deduplication)
- **Preflight**: PASSED (0 errors)
- **Neptune load**: 12/12 nodes, 16/16 edges, 0 errors
- **Post-load verification**: nodes_ok=True, edges_ok=True, isolated_nodes=0

## Remaining Issues / Risks

1. **Large markdown files (>20KB)**: sheet_02.md (26KB) produces LLM output that exceeds token limit.
   The truncated JSON recovery saves nodes but loses edges.
   Mitigation: max_tokens is now 12000 (was 8000); for very large sheets, consider splitting content.

2. **Cross-sheet understanding is limited by context window**: The project context summary
   lists all sheet names but doesn't include their full content. For 30+ sheet workbooks,
   the LLM sees the current sheet in full but only sheet names for context.
   Future: Consider a two-phase approach (summary extraction → cross-sheet reasoning).

3. **Japanese entity ID normalization**: `_ascii_slug()` drops Japanese characters.
   This means entities with only Japanese names get hex-encoded IDs.
   The display_name and name fields preserve Japanese; only the ID is ASCII.

4. **No automatic project_id derivation**: If `--project-id` is not specified, the pipeline
   uses the directory name (which may have Japanese characters). Should auto-slugify.

5. **Old graph data coexists in Neptune**: Each project gets its own `project_id` namespace,
   so old and new data don't conflict. But the old test data (pipeline_test_v1) is still in
   Neptune from this test run.
