# R12 Demo Packaging Report

## Phase Summary

| Item | Value |
|------|-------|
| Phase | R12: QA Terminal Demo Packaging + Graph Visualization |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |
| Execution Date | 2026-05-18 |
| Status | COMPLETE ✅ |

## Deliverables Created

### Scripts (3)

| Script | Lines | Purpose |
|--------|-------|---------|
| `scripts/qa_terminal_demo.py` | 347 | Interactive QA terminal with vector + graph retrieval |
| `scripts/run_qa_demo_batch.py` | 185 | Batch Q1-Q5 runner with cached/live modes |
| `scripts/export_neptune_subgraph.py` | 300 | Multi-format graph exporter (mermaid/html/reactflow/json) |

### Demo Outputs (7 files)

| File | Size |
|------|------|
| `docs/demo_outputs/q1_answer.md` | QA answer for 应付管理流程 |
| `docs/demo_outputs/q2_answer.md` | QA answer for JOURNAL_BASE |
| `docs/demo_outputs/q3_answer.md` | QA answer for 三表关联 |
| `docs/demo_outputs/q4_answer.md` | QA answer for Semantic Map CSV |
| `docs/demo_outputs/q5_answer.md` | QA answer for OA迁移 |
| `docs/demo_outputs/demo_summary.md` | Aggregate results |
| `docs/demo_outputs/debug_traces.jsonl` | Pipeline traces |

### Graph Visualizations (12 files)

| File | Nodes | Edges | Format |
|------|-------|-------|--------|
| `docs/demo_graph_journal_base.md` | 27 | 40 | Mermaid |
| `docs/demo_graph_journal_base.html` | 27 | 40 | HTML/vis.js |
| `docs/demo_graph_journal_base.reactflow.json` | 27 | 40 | ReactFlow |
| `docs/demo_graph_payment_req.md` | 8 | 11 | Mermaid |
| `docs/demo_graph_payment_req.html` | 8 | 11 | HTML/vis.js |
| `docs/demo_graph_payment_req.reactflow.json` | 8 | 11 | ReactFlow |
| `docs/demo_graph_ap_flow.md` | 40 | 24 | Mermaid |
| `docs/demo_graph_ap_flow.html` | 40 | 24 | HTML/vis.js |
| `docs/demo_graph_ap_flow.reactflow.json` | 40 | 24 | ReactFlow |
| `docs/demo_q4_semantic_map.md` | 15 | 15 | Mermaid |
| `docs/demo_q4_semantic_map.html` | 15 | 15 | HTML/vis.js |
| `docs/demo_q4_semantic_map.reactflow.json` | 15 | 15 | ReactFlow |

### Documentation (6 reports)

| File | Purpose |
|------|---------|
| `docs/murata_graphrag_demo_guide.md` | Complete demo guide |
| `docs/murata_graphrag_demo_script.md` | Presenter script |
| `docs/murata_rebuild_r12_qa_terminal_usage.md` | Usage reference |
| `docs/murata_rebuild_r12_demo_packaging_report.md` | This report |
| `docs/murata_rebuild_r12_visualization_report.md` | Visualization details |
| `docs/murata_rebuild_r12_next_step_recommendation.md` | Next steps |

## Technical Details

### QA Terminal Features

- Interactive and batch modes
- Preset Q1-Q5 questions
- Custom question input
- Entity extraction from question text
- Vector retrieval (LanceDB, top-10, Titan Embed V2)
- Graph retrieval (Neptune, 2-hop, openCypher)
- Context fusion (concatenation with source annotation)
- Answer generation (Bedrock Claude Sonnet)
- Structured output: entities, evidence, answer, latency, tokens
- JSON export option

### Graph Visualization Features

- Multiple focus entities (entity name, AP_FLOW, Q4_SEMANTIC)
- Configurable depth and size limits
- Mermaid flowchart output (embeddable in docs)
- HTML/vis.js interactive network (open in browser)
- ReactFlow JSON (for React web apps)
- Business/technical/mixed label modes
- Color-coded by node type (Table=blue, Process=green, External=orange)
