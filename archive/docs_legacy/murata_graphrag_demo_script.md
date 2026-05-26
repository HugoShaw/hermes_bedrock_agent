# Murata Enterprise GraphRAG — Demo Presenter Script

## Purpose

This document is a step-by-step presenter guide for demonstrating the Murata Enterprise GraphRAG system.

## Prerequisites

- Terminal access to the demo machine
- Network access to AWS (Neptune, Bedrock)
- Browser for HTML visualizations
- ~5 minutes for live demo, ~2 minutes for cached demo

## Demo Script

### Opening (30 seconds)

"This demo shows our Enterprise Hybrid GraphRAG system for the Murata AP (Accounts Payable) project. It combines vector search over 51 document chunks with a 381-node knowledge graph to answer complex business questions about the AP system."

### Step 1: Show the Knowledge Graph (1 minute)

Open in browser:
```bash
open docs/demo_q4_semantic_map.html
```

Talk through:
- "This is the main AP business flow: from external orders through HULFT transfer, journal processing, receiving, payment requests, approval, and finally SUN ERP posting."
- "Each node represents a table, process, or system component."
- "The graph has 381 total nodes and 703 relationships."

### Step 2: Run Q1 (AP Flow Question) — Cached (30 seconds)

```bash
cat docs/demo_outputs/q1_answer.md
```

Highlight:
- "The answer maps each process step to a specific database table"
- "Key fields are identified per step"
- "Code modules (Action classes, Services) are cited"

### Step 3: Run Q3 Live (Three-Table Analysis) — Optional (1 minute)

```bash
python scripts/qa_terminal_demo.py --preset q3
```

Point out:
- "Vector retrieval: 10 hits in 0.1s"
- "Graph retrieval: 14 entities, 90 neighbors in 0.3s"
- "The answer identifies SUN_REQUEST ↔ JOURNAL_BASE via OTHER_SYSTEM_NO field"
- "Code evidence: ReceivingServiceImpl SQL joins"

### Step 4: Show Q5 (OA Migration Design) (1 minute)

```bash
cat docs/demo_outputs/q5_answer.md | head -80
```

Highlight:
- "This is a design question — the system clearly separates existing evidence from proposed changes"
- "Concrete API design: OA推送接口, OA回調接口"
- "Database changes specified: ALTER TABLE, new STATUS codes"
- "Business impact analysis included"

### Step 5: Show Graph Visualization (30 seconds)

```bash
open docs/demo_graph_journal_base.html
```

- "JOURNAL_BASE is a hub entity with 27 connections"
- "Connected to tables, processes, fields, and code modules"

### Closing (30 seconds)

"The system scored 5/5 on all 5 target questions. Average answer time is 44 seconds. The hybrid approach gives us both document-level detail (from vectors) and structural understanding (from the graph). Questions?"

## Fallback: Cached-Only Demo

If network is unavailable:
```bash
python scripts/run_qa_demo_batch.py --cached
# Then show docs/demo_outputs/*.md
```

## Technical Q&A Preparation

| Likely Question | Answer |
|----------------|--------|
| "How many documents?" | 46 source chunks from 15 S3 files (design docs, DB schemas, code) |
| "How long to build?" | ~2 hours total across R1-R11 phases |
| "Cost?" | ~$15 in Bedrock API calls for extraction + QA |
| "Can it handle new questions?" | Yes, any question about the Murata AP system |
| "What about hallucination?" | System prompt requires evidence-grounded answers; Q5 separates evidence from design |
| "Graph DB choice?" | Neptune (serverless, managed, openCypher) |
| "Why not just RAG?" | Graph adds structural knowledge — table relationships, flow paths, code dependencies |
