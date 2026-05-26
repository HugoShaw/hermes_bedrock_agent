# Murata Enterprise GraphRAG — Demo Guide

## System Overview

The Murata Enterprise GraphRAG system combines:

1. **LanceDB Vector Store** — 51 document chunks embedded with Amazon Titan Embed V2 (1024 dim)
2. **Neptune Graph Database** — 381 entities + 703 relations extracted from Murata AP system docs
3. **Bedrock Claude** — jp.anthropic.claude-sonnet-4-6 for answer generation
4. **Hybrid Retrieval** — Vector similarity + graph traversal fused as context

### Architecture

```
User Question
    │
    ├─→ Entity Extraction (keyword matching)
    │
    ├─→ Vector Retrieval (LanceDB top-10, ~0.1s)
    │       └─→ Titan Embed V2 → cosine similarity
    │
    ├─→ Graph Retrieval (Neptune 2-hop, ~0.3s)
    │       └─→ MATCH entity → neighbors → relations
    │
    ├─→ Context Fusion (concatenation with source annotation)
    │
    └─→ Answer Generation (Claude Sonnet, ~30-70s)
            └─→ Structured answer with evidence citations
```

## How to Run QA Terminal

### Interactive Mode

```bash
cd ~/projects/hermes_bedrock_agent
python scripts/qa_terminal_demo.py --interactive
```

Type questions in Chinese or English. Use `q1`-`q5` for presets. Type `exit` to quit.

### Single Question

```bash
python scripts/qa_terminal_demo.py --question "JOURNAL_BASE表的作用是什么?"
python scripts/qa_terminal_demo.py --preset q1
```

### Save Output

```bash
python scripts/qa_terminal_demo.py --preset q2 --output /tmp/q2_result.json
```

## How to Run Q1-Q5 Batch Demo

### Cached Mode (instant, uses R11 results)

```bash
python scripts/run_qa_demo_batch.py --cached
```

### Live Mode (calls Bedrock, ~3-4 minutes total)

```bash
python scripts/run_qa_demo_batch.py --live
```

### Output

All demo outputs go to `docs/demo_outputs/`:
- `q1_answer.md` ... `q5_answer.md` — Individual answers
- `demo_summary.md` — Aggregate results
- `debug_traces.jsonl` — Pipeline debug data

## How to Export Graph Visualization

### Mermaid (for docs/presentations)

```bash
python scripts/export_neptune_subgraph.py --focus JOURNAL_BASE --format mermaid
python scripts/export_neptune_subgraph.py --focus PAYMENT_REQ --format mermaid --depth 2
python scripts/export_neptune_subgraph.py --focus Q4_SEMANTIC --format mermaid
python scripts/export_neptune_subgraph.py --focus AP_FLOW --format mermaid
```

### HTML (interactive, open in browser)

```bash
python scripts/export_neptune_subgraph.py --focus JOURNAL_BASE --format html -o docs/demo_graph_journal_base.html
```

### ReactFlow JSON (for React apps)

```bash
python scripts/export_neptune_subgraph.py --focus Q4_SEMANTIC --format reactflow -o docs/demo_q4_semantic_map.reactflow.json
```

### Special Focus Values

| Focus | Description |
|-------|-------------|
| `AP_FLOW` | Full AP business flow (queries Neptune live) |
| `Q4_SEMANTIC` | Curated 15-node semantic map (no Neptune needed) |
| Any entity name | Queries Neptune for 2-hop subgraph |

## Interpreting Vector Evidence

Vector evidence comes from LanceDB cosine similarity search:

- **distance < 0.3** — Very relevant, likely same topic
- **distance 0.3-0.5** — Related content, may have useful context
- **distance > 0.5** — Weakly related, use with caution
- **source_file_name** — Original S3 document
- **text** — The chunk content used as evidence

## Interpreting Graph Evidence

Graph evidence comes from Neptune entity traversal:

- **Entity** — A canonical node (table, process, module, etc.)
- **Neighbors** — Directly connected nodes via labeled edges
- **Relation types** — describes, contains, flows_to, calls, generates, depends_on, etc.
- **Labels** — PascalCase node types (Table, Process, Module, Field, etc.)

## Interpreting Fusion Context

The fusion context combines:
1. Top-10 vector chunks (with source annotation)
2. Up to 15 graph entities with their neighbor connections

The LLM sees both as structured context and synthesizes a coherent answer.

## How to Present Q4 Semantic Map

The Q4 semantic map shows the AP business main chain:

```
MS系統 → HULFT → JOURNAL_BASE → RECEIVING_LIST → 審批
→ RECEIVING_JOURNAL → PAYMENT_REQ → 審批 → PAYMENT_RECEIVING
→ SUN_REQUEST → SUN ERP → 報表
```

Use `docs/demo_q4_semantic_map.html` for interactive presentation,
or embed the Mermaid from `docs/demo_q4_semantic_map.md` in slides.

## Known Limitations

1. **Latency**: Answer generation takes 30-70s per question (Bedrock Claude)
2. **Vector coverage**: 51 chunks may miss niche topics not in source docs
3. **Graph depth**: 2-hop traversal may miss long-chain relationships
4. **Entity extraction**: Keyword-based, not semantic — may miss synonym entities
5. **No streaming**: Answers are returned in full (no partial display)
6. **Single model**: Only jp.anthropic.claude-sonnet-4-6 tested
7. **No caching**: Each live query re-embeds and re-queries (no result cache)
