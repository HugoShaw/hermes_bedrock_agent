# R12 QA Terminal Usage Guide

## Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/qa_terminal_demo.py` | Interactive QA terminal | `python scripts/qa_terminal_demo.py --interactive` |
| `scripts/run_qa_demo_batch.py` | Batch Q1-Q5 | `python scripts/run_qa_demo_batch.py --cached` |
| `scripts/export_neptune_subgraph.py` | Graph export | `python scripts/export_neptune_subgraph.py --entity JOURNAL_BASE` |

## QA Terminal Demo — Full CLI Reference

### Display Modes

| Mode | Lines | Description |
|------|-------|-------------|
| `compact` | ~85 | Question + short answer preview + top 3 evidence + latency |
| `demo` | ~430 | Full header + summary + top 5 evidence + rendered answer + citations + latency |
| `debug` | ~600+ | All of demo + full evidence + entity extraction + fusion context + warnings |
| `full` | All | Everything via pager, no content omitted |

### Basic Usage

```bash
# Preset question with demo view
python scripts/qa_terminal_demo.py --preset q1

# Custom question
python scripts/qa_terminal_demo.py -q "JOURNAL_BASE表的作用是什么？"

# Interactive mode
python scripts/qa_terminal_demo.py --interactive

# Compact view (terminal-friendly)
python scripts/qa_terminal_demo.py --preset q1 --view compact

# Full view with pager
python scripts/qa_terminal_demo.py --preset q1 --view full --pager true

# Debug mode with all details
python scripts/qa_terminal_demo.py --preset q1 --view debug --pager false
```

### Full CLI Arguments

```bash
python scripts/qa_terminal_demo.py \
  --run-id murata_rebuild_v1 \
  --dataset murata \
  --lancedb-collection murata_e2e_murata_rebuild_v1 \
  --neptune-graph-id g-nbuyck5yl8 \
  --view demo \
  --lang zh \
  --top-k-vector 10 \
  --graph-depth 2 \
  --max-graph-edges 30 \
  --show-vector-evidence true \
  --show-graph-evidence true \
  --show-fusion-context true \
  --show-latency true \
  --export-trace true \
  --pager true \
  --pause-between-sections false \
  --max-preview-chars 600 \
  --max-evidence-preview-chars 300 \
  --output-dir docs/demo_outputs \
  --preset q1 \
  --output docs/demo_outputs/manual_q1_answer.md
```

### Output Saving

Every run automatically saves:

1. `{output_dir}/{preset}_answer.md` — Full answer in Markdown
2. `{output_dir}/{preset}_debug.json` — Debug trace with retrieval details
3. `{output_dir}/{preset}_terminal_summary.md` — Terminal-friendly summary

For custom questions: `custom_{timestamp}_*.{md,json}`

### Interactive Mode Commands

```
Commands:
  q1-q5    Run preset question
  ask      Enter custom question
  view     Change view mode (compact/demo/debug/full)
  help     Show this help
  exit     Quit

After answer:
  [Enter]  Ask next question
  v        Show full vector evidence
  g        Show full graph evidence
  f        Show full fusion context
  a        Show full answer in pager
  s        Show saved file paths
  q        Quit
```

### Display Panels (10 sections)

1. **Header** — system info, model, collection, run ID
2. **Question** — user question with extracted search terms
3. **Retrieval Summary** — vector hits, graph entities, neighbors, answer length
4. **Vector Evidence** — table: Rank, Distance, Chunk, Purpose, Source, Preview
5. **Graph Evidence** — table: Rank, Entity, Type, Relations, Neighbors
6. **Fusion Context** — summary (demo) or full text (debug/full)
7. **Answer** — rendered as Rich Markdown (with CSV syntax highlighting for Q4)
8. **Citations** — source files and graph entities referenced
9. **Latency** — vector/graph/answer/total timings + token usage
10. **Saved Files** — paths to auto-saved output files

### Dependencies

- **Required**: boto3, lancedb, python-dotenv
- **Optional (enhanced display)**: `rich` (graceful fallback to plain text if unavailable)

### Rendering

- Uses Rich library (v15.0.0) for panels, tables, markdown rendering, syntax highlighting
- Falls back to plain text if Rich is not installed
- CSV content (Q4) detected and rendered with syntax highlighting
- Long answers rendered via pager in `--view full`
