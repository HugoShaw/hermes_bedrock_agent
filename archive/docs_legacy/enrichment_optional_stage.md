# i18n Enrichment — Optional Stage

## Overview

The i18n enrichment stage adds multilingual display names, business-friendly
aliases, and zh/en/ja labels to entities and relations in the knowledge graph.

**This stage is DISABLED by default.** The default pipeline works without it:

```
scan → parse → chunk → embed → graph extraction → normalize → Neptune load → retrieval → visualization
```

Enrichment is an **optional enhancement** that improves:
- Graph retrieval hit rate for CJK (Chinese/Japanese) queries
- Business-friendly display labels in Mermaid/ReactFlow visualization
- Multilingual alias matching in QueryEntityExtractor

## Why Default Skip

1. **Cost**: LLM enrichment for 3,000+ entities costs ~$15-30 in API calls
2. **Time**: Full LLM enrichment takes 2-5 hours depending on rate limits
3. **Not Required**: The pipeline produces valid search/retrieval without it
4. **Incremental**: Can be run separately after initial knowledge base build

## Enrichment Modes

| Mode | LLM Calls | Neptune Write | Use Case |
|------|-----------|---------------|----------|
| `none` | ✗ | ✗ | Default — skip entirely |
| `rule` | ✗ | ✗ | Low-cost deterministic rules only |
| `mock` | ✗ | ✗ | Testing and demo validation |
| `llm` | ✓ | Optional | Production multilingual enrichment |

### Mode: none (Default)

Does nothing. Pipeline proceeds directly from graph normalization to Neptune load.

### Mode: rule

Applies deterministic rules without any LLM calls:
- **Priority entities**: Uses hand-crafted i18n data for 8 key entities
  (JOURNAL_BASE, payment_req, muratapr, etc.)
- **Relation labels**: Uses builtin zh/en/ja map for common relation types
  (reads_from → 読み取る, writes_to → 書き込む, etc.)
- **Technical aliases**: Generates underscore-split and lowercase variants
- **No business label guessing**: If unsure, keeps the original technical name

### Mode: mock

Uses MockDeterministicLLM to generate predictable enrichment output.
Useful for testing the full enrichment pipeline without API costs.

### Mode: llm

Uses live Bedrock Claude to generate business-friendly multilingual labels.
Features:
- Multi-entity batch prompting (5 entities per call)
- Rate limiting (configurable RPM)
- Checkpoint/resume for long runs
- Failure fallback (preserves data on LLM errors)
- Skip-existing for incremental updates

## How to Enable in Pipeline

### Via CLI (run_e2e_murata_pipeline.py)

```bash
# Default: skip enrichment
python scripts/run_e2e_murata_pipeline.py \
  --mode live-source \
  --s3-uri "s3://s3-hulftchina-rd/Murata/" \
  --run-id murata_live_v2 \
  --stage all \
  --resume

# Enable rule-based enrichment
python scripts/run_e2e_murata_pipeline.py \
  --mode live-source \
  --s3-uri "s3://s3-hulftchina-rd/Murata/" \
  --run-id murata_live_v2 \
  --stage all \
  --enrichment-mode rule \
  --resume

# Enable mock enrichment (for testing)
python scripts/run_e2e_murata_pipeline.py \
  --mode live-source \
  --s3-uri "s3://s3-hulftchina-rd/Murata/" \
  --run-id murata_live_v2 \
  --stage all \
  --enrichment-mode mock \
  --enrichment-max-entities 200 \
  --resume
```

### Via Standalone Script (enrich_i18n.py)

```bash
# mode=none: prints info and exits
python scripts/enrich_i18n.py --run-id murata_live_v1 --mode none

# Rule-based enrichment (no LLM)
python scripts/enrich_i18n.py --run-id murata_live_v1 --mode rule

# Mock enrichment (for testing)
python scripts/enrich_i18n.py --run-id murata_live_v1 --mode mock

# Live LLM enrichment (selected entities)
python scripts/enrich_i18n.py \
  --run-id murata_live_v1 \
  --mode llm \
  --max-entities 200 \
  --rate-limit-per-minute 20

# Live LLM enrichment (all entities, resume from checkpoint)
python scripts/enrich_i18n.py \
  --run-id murata_live_v1 \
  --mode llm \
  --all-entities \
  --resume \
  --skip-existing \
  --rate-limit-per-minute 15
```

## Dry-Run (Default)

By default, enrichment does **NOT** write to Neptune:

```bash
# This generates preview files but does NOT touch Neptune
python scripts/enrich_i18n.py --run-id murata_live_v1 --mode mock
```

Output includes:
- `i18n_entities_enriched.jsonl` — Enriched entity data
- `i18n_relations_enriched.jsonl` — Enriched relation labels
- `i18n_update_neptune_preview.json` — What WOULD be written
- `i18n_update_neptune_preview.cypher` — Parameterized Cypher preview

## Writing to Neptune

**Requires explicit double-confirmation:**

```bash
python scripts/enrich_i18n.py \
  --run-id murata_live_v1 \
  --mode llm \
  --input i18n_entities_enriched.jsonl \
  --update-neptune \
  --confirm-live-write
```

Without `--confirm-live-write`, the script exits with an error.

### Risks of Neptune Write-Back

1. **Irreversible**: Neptune MERGE overwrites existing properties
2. **Partial writes**: If interrupted, some entities will have i18n fields and others won't
3. **Schema pollution**: Adds many new properties to Neptune nodes
4. **Query impact**: Existing Cypher queries may need updates

### Recommended Practice

1. Run enrichment in dry-run mode first
2. Review `i18n_update_neptune_preview.json`
3. Validate with QueryEntityExtractor using local enriched artifacts
4. Only write to Neptune when satisfied with quality

## Configuration

### configs/enrichment.yaml

```yaml
enrichment:
  enabled: false
  mode: none
  target: selected
  max_entities: 200
  update_neptune: false
  require_confirm_live_write: true
```

### Environment Variables

```bash
ENRICHMENT_ENABLED=false
ENRICHMENT_MODE=none
ENRICHMENT_MAX_ENTITIES=200
ENRICHMENT_UPDATE_NEPTUNE=false
```

## Recommended Practices

| Scenario | Recommended Mode |
|----------|-----------------|
| Technical validation / CI | `none` |
| Cost-sensitive production | `rule` |
| Demo / presentation | `mock` |
| Production with multilingual search | `llm` (selected entities) |
| Full production optimization | `llm` (all entities, with resume) |

**Do NOT default to full LLM enrichment for all entities.**
Start with `rule` or `mock`, validate retrieval quality, then selectively
apply `llm` to high-value entities that fail CJK query matching.

## Output Artifacts

When enrichment runs (mode != none), it generates files in the artifacts directory:

| File | Description |
|------|-------------|
| `i18n_entities_enriched.jsonl` | Entity i18n fields |
| `i18n_relations_enriched.jsonl` | Relation i18n labels |
| `i18n_enrichment_report.json` | Machine-readable report |
| `i18n_enrichment_report.md` | Human-readable report |
| `i18n_update_neptune_preview.json` | Neptune write-back preview |
| `i18n_update_neptune_preview.cypher` | Cypher preview |

These are **optional enrichment output** — not default pipeline output.
The presence of `i18n_entities_enriched*.jsonl` in the artifacts directory
is detected by QueryEntityExtractor to augment alias matching.

## Integration with QueryEntityExtractor

The QueryEntityExtractor automatically loads i18n enrichment data if available:
- If `i18n_entities_enriched.jsonl` exists → loads aliases_zh/en/ja
- If not → uses original canonical_name/aliases (Phase 10A behavior)
- No enrichment artifacts = no degradation in search quality
