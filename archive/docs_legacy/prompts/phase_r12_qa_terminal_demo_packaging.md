# Phase R12 — QA Terminal Demo Packaging + Graph Visualization

## Objective

Package the validated Murata GraphRAG rebuild into a demo-ready QA interface and graph visualization workflow.

R12 is a **demo packaging and visualization phase**.

R12 must not rebuild the knowledge base.  
R12 must not re-parse documents.  
R12 must not regenerate embeddings.  
R12 must not re-run graph extraction.  
R12 must not re-import Neptune data.  
R12 must not modify baseline data.

The purpose of R12 is to answer one key question:

> Can we demonstrate the rebuilt Murata GraphRAG system clearly through a QA interface that shows answer quality, evidence, retrieval traces, and Neptune graph visualization?

R12 should make the current system easier to demo, inspect, and explain.

---

## Project Context

Project root:

```text
~/projects/hermes_bedrock_agent
Validated rebuild target:
run_id: murata_rebuild_v1
dataset: murata
LanceDB collection: murata_e2e_murata_rebuild_v1
Neptune Graph ID: g-nbuyck5yl8
Neptune endpoint: g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com
AWS region: ap-northeast-1
Text model: jp.anthropic.claude-sonnet-4-6
Embedding model: amazon.titan-embed-text-v2:0
R11 result:
R11 Hybrid Retrieval & QA Validation PASSED.
Q1-Q5 all scored 5/5.
LanceDB vector retrieval works.
Neptune graph retrieval works.
Fusion context works.
Answer generation works.
Debug traces were generated.
R12 should focus on presentation, usability, and visualization.
Control Files to Read
Before executing R12, read:
.hermes.mddocs/task_state.mddocs/prompts/phase_r12_qa_terminal_demo_packaging.mdAlso read previous phase reports:
docs/murata_rebuild_r11_hybrid_retrieval_report.md
docs/murata_rebuild_r11_qa_answers_report.md
docs/murata_rebuild_r11_qa_evaluation_report.md
docs/murata_rebuild_r11_debug_trace_report.md
docs/murata_rebuild_r11_next_step_recommendation.md
Read R11 artifacts:
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/hybrid_retrieval_results_r11.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/vector_retrieval_results_r11.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/graph_retrieval_results_r11.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/fusion_contexts_r11.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_answers_r11.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_debug_traces_r11.jsonl
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_evaluation_r11.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/qa_latency_metrics_r11.json
Read R10/R8 graph artifacts if needed:
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_key_entity_queries_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_neighbor_queries_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q3_path_validation_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q4_path_validation_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/neptune_full_q5_oa_validation_r10.json
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_nodes_neptune_csv_r8.csv
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/q4_edges_neptune_csv_r8.csv
R12 Scope
R12 includes:
Improve or create a demo-ready QA terminal.Add clear display sections for:
questiondetected entitiesvector evidencegraph evidencefusion contextanswercitations/evidencelatencyAdd preset demo questions Q1-Q5.Add command-line options for demo mode.Add graph visualization export from Neptune.Add Mermaid subgraph export.Add HTML graph visualization if feasible.Add ReactFlow-compatible JSON export if feasible.Add demo guide documentation.Add screenshots/export instructions if applicable.Generate R12 reports and stop for review.R12 excludes:
Rebuilding chunks.Regenerating summaries.Regenerating embeddings.Writing LanceDB.Re-running graph extraction.Re-importing Neptune.Deleting or modifying Neptune data.Modifying baseline data.Proceeding to any next phase automatically.Required Pre-checks
Before implementation, verify:
1. Rebuild QA assets exist
Check:
LanceDB collection: murata_e2e_murata_rebuild_v1
Expected records: 51

Neptune graph:
run_id=murata_rebuild_v1
dataset=murata
Expected nodes: 381
Expected edges: 703
Run read-only checks only.
2. Existing QA terminal
Locate existing QA terminal script:
scripts/qa_terminal.py
or similar files:
scripts/qa_*.py
src/**/qa*.py
src/**/retrieval*.py
src/**/answer*.py
Inspect existing components:
LanceDB retriever
NeptuneGraphRetriever
QueryEntityExtractor
ContextBuilder
AnswerGenerator
fusion logic
Do not rewrite everything if existing logic is usable. Prefer minimal extension.
3. Visualization utilities
Locate existing visualization modules:
src/**/visualization*.py
scripts/export_mermaid.py
scripts/export_*.py
If they exist, reuse or extend them.
If not, create lightweight scripts.
Demo QA Terminal Requirements
Create or enhance:
scripts/qa_terminal_demo.py
If scripts/qa_terminal.py already exists and is suitable, either:
extend it with --demo-mode, orcreate scripts/qa_terminal_demo.py as a wrapper around existing logic.Recommended: create a separate demo wrapper to avoid breaking existing terminal.
Required CLI Options
The demo terminal should support:
python scripts/qa_terminal_demo.py \
  --run-id murata_rebuild_v1 \
  --dataset murata \
  --lancedb-collection murata_e2e_murata_rebuild_v1 \
  --neptune-graph-id g-nbuyck5yl8 \
  --view demo \
  --lang zh \
  --top-k-vector 10 \
  --graph-depth 2 \
  --max-graph-edges 30
Required options:
--run-id
--dataset
--lancedb-collection
--neptune-graph-id
--view demo|debug|compact
--lang zh|ja|en|auto
--top-k-vector
--graph-depth
--max-graph-edges
--mock-answer false|true
--show-vector-evidence true|false
--show-graph-evidence true|false
--show-fusion-context true|false
--show-latency true|false
--export-trace true|false
Optional:
--question-file
--preset q1|q2|q3|q4|q5|all
--save-answer-md
--save-debug-json
--export-graph-mermaid
--export-graph-html
Demo View Display Requirements
In --view demo, display should be human-readable and not too noisy.
For each question, show:
======================================================================
Murata GraphRAG QA Demo
run_id=murata_rebuild_v1 | dataset=murata
Vector=LanceDB: murata_e2e_murata_rebuild_v1
Graph=Neptune: g-nbuyck5yl8
======================================================================

Q> 用户问题

[1] Detected Intent / Language
[2] Key Entities / Search Terms
[3] Vector Evidence Summary
[4] Graph Evidence Summary
[5] Fused Context Summary
[6] Final Answer
[7] Evidence / Citations
[8] Latency
======================================================================
Vector evidence should show:
rank
score/distance
chunk_id
source_file_name
chunk_purpose
summary_type
related_target_questions
short preview
Graph evidence should show:
matched entity
entity type
relation type
neighbor entity
path if available
evidence preview
source_chunk_ids
Fusion context should show:
number of vector items
number of graph items
top evidence selected
deduped source count
Answer should be displayed cleanly in Markdown.
Debug View Display Requirements
In --view debug, show more details:
raw extracted entity mentions
graph search terms
matched graph entities
vector top-k full metadata
graph neighbor paths
fusion context token estimate
answer prompt summary
latency by stage
warnings
Do not print unreadable huge JSON unless user asks.
Compact View Display Requirements
In --view compact, show only:
question
short answer
top 3 evidence
latency
Preset Demo Questions
Add built-in Q1-Q5 presets.
Q1
请描述应付管理的业务流程，并要求：
1. 每个流程步骤对应的数据库表
2. 每个步骤涉及的关键字段
3. 如有对应代码模块，请指出类或方法
Q2
JOURNAL_BASE 表在系统中的作用是什么？
请结合：
1. 表结构
2. 相关业务流程
3. 调用该表的代码模块进行说明
Q3
SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三张表之间，在没有外键的情况下：
1. 通过哪些字段形成关联
2. 这些关联在代码中是如何体现的，如 SQL 或 Mapper
3. 在业务流程中的数据流转路径
Q4
请围绕“应付管理完整业务流程”，构建一个 Semantic Map，输出 Neptune CSV。
已知业务主流程为：
订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表

要求：
1. 必须覆盖以上完整流程链，不得缺失步骤
2. 输出 nodes.csv，字段：id,label,type
3. 输出 edges.csv，字段：from,to,relation
4. 关系仅允许：
   - generates
   - depends_on
   - relates_to
5. 必须体现一条清晰主链：至少包含连续路径 A → B → C → D
6. 不要解释，只输出 CSV
Q5
当前系统中，付款申请在应付系统内完成审批。
现在需要进行系统改造：
- 做单仍在应付系统，Payment Request
- 审批流程迁移到 OA 系统
- 审批完成后，审批结果需要回写应付系统。

请完成以下内容：
1. 设计新的业务流程
2. 描述数据流转关系
3. 给出系统改造清单
4. 说明对现有业务流程的影响

要求：
- 结合现有表结构，如 PAYMENT_REQ、PAYMENT_RECEIVING 等
- 尽量具体，不要泛泛而谈
- 不要只写概念，需要有结构化内容
Graph Visualization Requirements
R12 must provide a way to visualize Neptune graph subgraphs.
Create or enhance:
scripts/export_neptune_subgraph.py
This script should export a Neptune subgraph for selected focus entities.
Graph Visualization CLI
Required command examples:
python scripts/export_neptune_subgraph.py \
  --run-id murata_rebuild_v1 \
  --dataset murata \
  --graph-id g-nbuyck5yl8 \
  --focus JOURNAL_BASE \
  --depth 2 \
  --max-nodes 80 \
  --max-edges 120 \
  --format mermaid \
  --output docs/demo_graph_journal_base.md
python scripts/export_neptune_subgraph.py \
  --run-id murata_rebuild_v1 \
  --dataset murata \
  --graph-id g-nbuyck5yl8 \
  --focus PAYMENT_REQ \
  --depth 2 \
  --max-nodes 80 \
  --max-edges 120 \
  --format html \
  --output docs/demo_graph_payment_req.html
python scripts/export_neptune_subgraph.py \
  --run-id murata_rebuild_v1 \
  --dataset murata \
  --graph-id g-nbuyck5yl8 \
  --focus "应付管理" \
  --depth 3 \
  --max-nodes 120 \
  --max-edges 180 \
  --format reactflow \
  --output docs/demo_graph_ap_flow.reactflow.json
Required options:
--run-id
--dataset
--graph-id
--focus
--depth
--max-nodes
--max-edges
--relation-types
--node-types
--format mermaid|html|reactflow|json
--output
--lang zh|ja|en|auto
--label-mode business|technical|mixed
Graph Query Rules
For graph visualization, query only nodes with:
run_id=murata_rebuild_v1
dataset=murata
Do not query or display baseline nodes unless user explicitly requests comparison.
For focus entity matching, support:
canonical_name exact match
display_name exact match
contains match
aliases_json contains if available
case-insensitive technical match
CJK partial match
Special aliases:
仕訳基礎 → JOURNAL_BASE
付款申请 / 付款申請 / 支払申請 → PAYMENT_REQ
应付管理 / 応付管理 → AP business process
对账单 / 対帳単 → RECEIVING_LIST
OA系统 / OA系統 → OA
Graph Visualization Output Requirements
Mermaid Output
For Mermaid:
flowchart LR
  A["JOURNAL_BASE<br/>Table"] -->|has_field| B["OTHER_SYSTEM_NO<br/>Column"]
Requirements:
Use flowchart LR
Escape special characters
Limit node label length
Show relation label on edge
Group by layers if possible
Use readable labels
Avoid too many nodes by default
HTML Output
If generating HTML, use a lightweight standalone HTML file.
Preferred:
D3.js force graph via CDN
or vis-network via CDN
If internet access is not guaranteed, generate simple embedded JS without external dependency or clearly document CDN dependency.
HTML should support:
node color by layer
node shape/type by entity_type
edge label
hover tooltip
search box if feasible
legend
focus node highlight
ReactFlow JSON Output
For ReactFlow JSON:
{
  "nodes": [
    {
      "id": "...",
      "type": "default",
      "position": {"x": 0, "y": 0},
      "data": {
        "label": "...",
        "entity_type": "...",
        "layer": "..."
      }
    }
  ],
  "edges": [
    {
      "id": "...",
      "source": "...",
      "target": "...",
      "label": "..."
    }
  ]
}
Raw JSON Output
For raw JSON:
{
  "focus": "...",
  "nodes": [],
  "edges": [],
  "metadata": {
    "run_id": "murata_rebuild_v1",
    "dataset": "murata",
    "depth": 2
  }
}
Required Demo Graph Exports
Generate at least the following demo graph files:
docs/demo_graph_journal_base.md
docs/demo_graph_payment_req.md
docs/demo_graph_ap_flow.md
docs/demo_graph_q4_semantic_map.md
If HTML generation is feasible, also generate:
docs/demo_graph_journal_base.html
docs/demo_graph_payment_req.html
docs/demo_graph_ap_flow.html
If ReactFlow JSON generation is feasible, also generate:
docs/demo_graph_journal_base.reactflow.json
docs/demo_graph_payment_req.reactflow.json
docs/demo_graph_ap_flow.reactflow.json
Q4 Semantic Map Visualization
R12 must generate a clean visualization for Q4.
Use either:
q4_nodes_neptune_csv_r8.csv
q4_edges_neptune_csv_r8.csv
or Neptune query results.
Create:
docs/demo_q4_semantic_map.md
docs/demo_q4_semantic_map.html
The Q4 demo graph should be much smaller than the full 221-node / 499-edge preview.
Preferred Q4 demo graph size:
10–30 nodes
10–40 edges
It should show a clear main chain:
MS系统 / 外部订单
→ HULFT
→ JOURNAL_BASE
→ RECEIVING_LIST / 对账单
→ RECEIVING_JOURNAL
→ PAYMENT_REQ / 付款申请
→ PAYMENT_RECEIVING
→ SUN_REQUEST
→ SUN ERP
→ 报表 / 支付输出
Allowed edge labels:
generates
depends_on
relates_to
QA Demo Batch Script
Create:
scripts/run_qa_demo_batch.py
This script should run Q1-Q5 in one command and save outputs.
Example:
python scripts/run_qa_demo_batch.py \
  --run-id murata_rebuild_v1 \
  --dataset murata \
  --lancedb-collection murata_e2e_murata_rebuild_v1 \
  --neptune-graph-id g-nbuyck5yl8 \
  --preset all \
  --view demo \
  --output-dir docs/demo_outputs
Outputs:
docs/demo_outputs/q1_answer.md
docs/demo_outputs/q2_answer.md
docs/demo_outputs/q3_answer.md
docs/demo_outputs/q4_answer.md
docs/demo_outputs/q5_answer.md
docs/demo_outputs/demo_summary.md
docs/demo_outputs/debug_traces.jsonl
Demo Documentation
Create:
docs/murata_graphrag_demo_guide.md
The guide must include:
System overview.What was rebuilt.How to run QA terminal demo.How to run Q1-Q5 batch demo.How to export graph visualization.How to interpret Vector Evidence.How to interpret Graph Evidence.How to interpret Fusion Context.How to open Mermaid / HTML graph outputs.Known limitations.Recommended demo script.Also create:
docs/murata_graphrag_demo_script.md
This should be a presenter script for explaining the demo to stakeholders.
Optional: Lightweight Web UI
If time permits and existing project structure supports it, create a minimal Streamlit UI:
scripts/qa_demo_streamlit.py
Features:
question input
preset Q1-Q5 buttons
answer display
vector evidence table
graph evidence table
latency display
Mermaid graph text display
Run command:
streamlit run scripts/qa_demo_streamlit.py
Do not make Streamlit mandatory. Terminal demo is required; Streamlit is optional.
Output Artifacts
Create artifacts under:
~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts/
Required:
qa_demo_config_r12.json
qa_demo_run_results_r12.jsonl
qa_demo_latency_r12.json
graph_visualization_exports_r12.json
Output Reports / Docs
Create under:
~/projects/hermes_bedrock_agent/docs/
Required:
docs/murata_rebuild_r12_demo_packaging_report.md
docs/murata_rebuild_r12_visualization_report.md
docs/murata_rebuild_r12_qa_terminal_usage.md
docs/murata_graphrag_demo_guide.md
docs/murata_graphrag_demo_script.md
docs/murata_rebuild_r12_next_step_recommendation.md
Required demo outputs:
docs/demo_outputs/q1_answer.md
docs/demo_outputs/q2_answer.md
docs/demo_outputs/q3_answer.md
docs/demo_outputs/q4_answer.md
docs/demo_outputs/q5_answer.md
docs/demo_outputs/demo_summary.md
docs/demo_outputs/debug_traces.jsonl
Required graph outputs:
docs/demo_graph_journal_base.md
docs/demo_graph_payment_req.md
docs/demo_graph_ap_flow.md
docs/demo_graph_q4_semantic_map.md
docs/demo_q4_semantic_map.md
Optional graph outputs:
docs/demo_graph_journal_base.html
docs/demo_graph_payment_req.html
docs/demo_graph_ap_flow.html
docs/demo_q4_semantic_map.html
docs/demo_graph_journal_base.reactflow.json
docs/demo_graph_payment_req.reactflow.json
docs/demo_graph_ap_flow.reactflow.json
R12 Quality Gate
R12 passes only if:
QA demo terminal or wrapper exists.QA demo terminal can use rebuild LanceDB collection.QA demo terminal can use rebuild Neptune graph.Demo mode displays vector evidence.Demo mode displays graph evidence.Demo mode displays final answer.Demo mode displays latency.Q1-Q5 batch demo script exists.Q1-Q5 batch demo runs or a dry-run/test output is generated from existing R11 artifacts.Demo outputs for Q1-Q5 are created.Graph visualization export script exists.JOURNAL_BASE graph visualization is created.PAYMENT_REQ graph visualization is created.AP flow graph visualization is created.Q4 semantic map visualization is created.Mermaid output is valid enough for review.HTML or ReactFlow export is created if feasible, or explicitly skipped with reason.Demo guide is created.Demo presenter script is created.No Neptune writes occur.No LanceDB writes occur.No embedding generation occurs.No graph extraction occurs.No document parsing occurs.No baseline data is modified.If R12 fails:
do not proceedreport failure reasonsrecommend one of:
fix QA terminal configfix graph export queryreduce visualization node countimprove Mermaid escapingcreate simpler static demo from R11 artifactsSuccess Criteria
R12 is successful if:
1. A user can run a QA demo from terminal.
2. The demo clearly shows vector evidence and graph evidence.
3. Q1-Q5 outputs are saved as demo materials.
4. Neptune graph subgraphs can be exported and viewed.
5. Q4 semantic map can be shown visually.
6. The demo guide explains how to present the system.
Implementation Guidance
Prefer incremental, safe implementation.
Recommended order:
Inspect existing QA terminal.Create scripts/qa_terminal_demo.py.Create scripts/run_qa_demo_batch.py.Create scripts/export_neptune_subgraph.py.Generate Mermaid graph outputs.Generate optional HTML / ReactFlow graph outputs.Generate demo docs.Run smoke tests.Create R12 reports.Update docs/task_state.md.Do not over-engineer.
If the project already has reusable functions, use them.
If some components are not easily reusable, create thin wrappers.
Forbidden Actions
R12 must not:
write Neptunedelete Neptune datawrite LanceDBregenerate embeddingsre-run graph extractionre-parse source documentsmodify baseline dataproceed to next phase automaticallyAllowed Actions
R12 may:
read LanceDB rebuild collectionquery Neptune rebuild graph read-onlycall Bedrock text LLM for demo answers if running live demoreuse R11 answer artifacts to generate static demo outputscreate scriptscreate Markdown / HTML / JSON visualization outputscreate demo docsupdate docs/task_state.mdState Update
After completing R12, update docs/task_state.md:
## Current Phase

`R12`

## Current Phase Status

completed or failed

## Completed Outputs

- `scripts/qa_terminal_demo.py`
- `scripts/run_qa_demo_batch.py`
- `scripts/export_neptune_subgraph.py`
- `docs/murata_rebuild_r12_demo_packaging_report.md`
- `docs/murata_rebuild_r12_visualization_report.md`
- `docs/murata_rebuild_r12_qa_terminal_usage.md`
- `docs/murata_graphrag_demo_guide.md`
- `docs/murata_graphrag_demo_script.md`
- `docs/murata_rebuild_r12_next_step_recommendation.md`
- `docs/demo_outputs/q1_answer.md`
- `docs/demo_outputs/q2_answer.md`
- `docs/demo_outputs/q3_answer.md`
- `docs/demo_outputs/q4_answer.md`
- `docs/demo_outputs/q5_answer.md`
- `docs/demo_outputs/demo_summary.md`
- `docs/demo_outputs/debug_traces.jsonl`
- `docs/demo_graph_journal_base.md`
- `docs/demo_graph_payment_req.md`
- `docs/demo_graph_ap_flow.md`
- `docs/demo_graph_q4_semantic_map.md`
- `docs/demo_q4_semantic_map.md`

## Latest Findings

Summarize QA demo usability, graph visualization results, and limitations.

## Risks / Issues

Summarize UI limitations, graph density issues, Mermaid/HTML limitations, and performance concerns.

## Recommended Next Phase

Choose one:

- `Complete`
- `R12.5`
- `Productionization`
- `Baseline Comparison`

## Next Phase Prompt

If needed, specify next prompt file.
Then stop and wait for user review.
Do not proceed to another phase automatically.
