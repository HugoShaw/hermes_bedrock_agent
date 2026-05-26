#!/usr/bin/env python3
"""
Murata Enterprise GraphRAG — Interactive QA Terminal Demo
=========================================================

Rich-enhanced terminal visualization for hybrid retrieval (LanceDB vector +
Neptune graph) with answer generation via Bedrock Claude.

Usage:
    python scripts/qa_terminal_demo.py --preset q1
    python scripts/qa_terminal_demo.py --question "your question" --view debug
    python scripts/qa_terminal_demo.py --interactive --view demo
    python scripts/qa_terminal_demo.py -p q3 --view full --pager true

Environment:
    Reads .env from project root. Requires:
    - LanceDB at ~/projects/data/vector_store/lancedb
    - Neptune graph g-nbuyck5yl8 accessible
    - Bedrock runtime configured (ap-northeast-1)
    - Rich library (optional, graceful fallback to plain text)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import boto3
from botocore.config import Config
import lancedb

from hermes_bedrock_agent.clients.neptune_client import NeptuneClient

# Rich library (optional)
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.markdown import Markdown as RichMarkdown
    from rich.text import Text
    from rich.rule import Rule
    from rich.columns import Columns
    from rich.syntax import Syntax
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ======================================================================
# Configuration
# ======================================================================
LANCEDB_PATH = os.path.expanduser("~/projects/data/vector_store/lancedb")
COLLECTION = "murata_e2e_murata_rebuild_v1"
RUN_ID = "murata_rebuild_v1"
DATASET = "murata"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
TEXT_MODEL = os.environ.get("BEDROCK_TEXT_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
REGION = "ap-northeast-1"
TOP_K = 10
GRAPH_DEPTH = 2
MAX_EDGES = 30

# Preset questions
PRESETS = {
    "q1": '请描述应付管理的业务流程，并要求：\n1. 每个流程步骤对应的数据库表\n2. 每个步骤涉及的关键字段\n3. 如有对应代码模块，请指出类或方法',
    "q2": 'JOURNAL_BASE 表在系统中的作用是什么？\n请结合：\n1. 表结构\n2. 相关业务流程\n3. 调用该表的代码模块进行说明',
    "q3": 'SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三张表之间，在没有外键的情况下：\n1. 通过哪些字段形成关联\n2. 这些关联在代码中是如何体现的，如 SQL 或 Mapper\n3. 在业务流程中的数据流转路径',
    "q4": "请围绕'应付管理完整业务流程'，构建一个 Semantic Map，输出 Neptune CSV。\n已知业务主流程为：\n订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表\n\n要求：\n1. 必须覆盖以上完整流程链，不得缺失步骤\n2. 输出 nodes.csv，字段：id,label,type\n3. 输出 edges.csv，字段：from,to,relation\n4. 关系仅允许：generates, depends_on, relates_to\n5. 必须体现一条清晰主链，至少包含连续路径 A → B → C → D\n6. 不要解释，只输出 CSV",
    "q5": '当前系统中，付款申请在应付系统内完成审批。\n现在需要进行系统改造：\n- 做单仍在应付系统，Payment Request\n- 审批流程迁移到 OA 系统\n- 审批完成后，审批结果需要回写应付系统。\n\n请完成以下内容：\n1. 设计新的业务流程\n2. 描述数据流转关系\n3. 给出系统改造清单\n4. 说明对现有业务流程的影响\n\n要求：\n- 结合现有表结构，如 PAYMENT_REQ、PAYMENT_RECEIVING 等\n- 尽量具体，不要泛泛而谈\n- 不要只写概念，需要有结构化内容',
}

VERSION = "2.0.0"


# ======================================================================
# CLI Helpers
# ======================================================================

def str2bool(v):
    """Parse boolean CLI argument value."""
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', '0'):
        return False
    raise argparse.ArgumentTypeError(f'Boolean value expected, got: {v}')


# ======================================================================
# Core Functions
# ======================================================================

def init_clients():
    """Initialize LanceDB, Neptune, and Bedrock clients."""
    db = lancedb.connect(LANCEDB_PATH)
    tbl = db.open_table(COLLECTION)
    neptune = NeptuneClient()
    bedrock_rt = boto3.client(
        "bedrock-runtime", region_name=REGION,
        config=Config(read_timeout=600)
    )
    return tbl, neptune, bedrock_rt


def embed_query(bedrock_rt, text):
    """Embed query text using Titan Embed V2."""
    response = bedrock_rt.invoke_model(
        modelId=EMBED_MODEL,
        body=json.dumps({"inputText": text[:8000], "dimensions": 1024, "normalize": True}),
        contentType="application/json", accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


def vector_retrieve(tbl, bedrock_rt, query, top_k=TOP_K):
    """Retrieve top-k similar chunks from LanceDB."""
    qvec = embed_query(bedrock_rt, query)
    results = tbl.search(qvec).limit(top_k).to_arrow()
    hits = []
    for i in range(results.num_rows):
        hit = {col: results.column(col)[i].as_py()
               for col in results.column_names if col != 'vector'}
        hit["_distance"] = results.column("_distance")[i].as_py()
        hits.append(hit)
    return hits


def extract_search_terms(question):
    """Extract graph search terms from question."""
    terms = []
    keywords = [
        "JOURNAL_BASE", "SUN_REQUEST", "RECEIVING_JOURNAL", "PAYMENT_REQ",
        "PAYMENT_RECEIVING", "RECEIVING_LIST", "OA", "付款", "审批",
        "応付", "対帳", "検収", "仕訳", "支払", "Payment", "Journal",
        "Receiving", "Sun", "Approval", "HULFT",
    ]
    for kw in keywords:
        if kw.lower() in question.lower():
            terms.append(kw)
    if not terms:
        terms = ["JOURNAL_BASE", "PAYMENT_REQ", "応付"]
    return terms[:6]


def graph_retrieve(neptune, search_terms, depth=GRAPH_DEPTH, max_edges=MAX_EDGES):
    """Retrieve graph context from Neptune."""
    all_results = []
    for term in search_terms[:5]:
        try:
            result = neptune.execute_query(
                f"""MATCH (n {{run_id: '{RUN_ID}', dataset: '{DATASET}'}})
                WHERE n.canonical_name CONTAINS $term OR n.entity_id CONTAINS $term
                RETURN n.entity_id AS eid, n.canonical_name AS cname, labels(n) AS lbls
                LIMIT 5""",
                {"term": term}
            )
            nodes = result.get("results", [])
            for node in nodes[:3]:
                eid = node.get("eid")
                if eid:
                    nbr_result = neptune.execute_query(
                        f"""MATCH (n {{entity_id: $eid, run_id: '{RUN_ID}'}})-[r]-(m {{run_id: '{RUN_ID}'}})
                        RETURN n.canonical_name AS src, type(r) AS rel,
                               m.canonical_name AS tgt, m.entity_id AS tgt_id, labels(m) AS tgt_labels
                        LIMIT $lim""",
                        {"eid": eid, "lim": max_edges}
                    )
                    neighbors = nbr_result.get("results", [])
                    all_results.append({"entity": node, "neighbors": neighbors})
        except Exception as e:
            all_results.append({"term": term, "error": str(e)})
    return all_results


def build_context(vec_results, graph_results):
    """Fuse vector and graph evidence into a context string."""
    vec_context = ""
    for i, hit in enumerate(vec_results[:10]):
        vec_context += f"\n--- 文档证据 {i+1} (source: {hit.get('source_file_name','')}, distance: {hit.get('_distance',0):.3f}) ---\n"
        vec_context += hit.get("text", "")[:2000] + "\n"

    graph_context = ""
    for item in graph_results[:10]:
        entity = item.get("entity", {})
        neighbors = item.get("neighbors", [])
        if entity:
            graph_context += f"\n--- 图谱实体: {entity.get('cname','')} ({entity.get('lbls','')}) ---\n"
            for nbr in neighbors[:15]:
                graph_context += f"  {nbr.get('src','')} —[{nbr.get('rel','')}]→ {nbr.get('tgt','')} ({nbr.get('tgt_labels','')})\n"

    return vec_context, graph_context


def generate_answer(bedrock_rt, question, vec_context, graph_context, max_tokens=4096):
    """Generate answer using Bedrock Claude."""
    system_prompt = """你是 Murata Enterprise AP System 的技术顾问。基于提供的向量检索文档证据和知识图谱证据，准确回答用户的问题。

要求：
1. 只基于提供的证据回答，不要编造不存在的表名、字段名或代码模块
2. 引用证据时标注来源
3. 如果证据不足以完整回答，明确说明哪些部分是基于证据的，哪些是推断的
4. 用中文回答，技术术语保留原文"""

    user_prompt = f"""# 用户问题

{question}

# 向量检索文档证据

{vec_context}

# 知识图谱证据

{graph_context}

请基于以上证据回答问题。"""

    response = bedrock_rt.invoke_model(
        modelId=TEXT_MODEL,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        }),
        contentType="application/json", accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"], result.get("usage", {})


def run_qa(tbl, neptune, bedrock_rt, question, verbose=False):
    """Run full QA pipeline and return structured result."""
    t_start = time.time()

    # Step 1: Extract entities
    search_terms = extract_search_terms(question)

    # Step 2: Vector retrieval
    t0 = time.time()
    vec_results = vector_retrieve(tbl, bedrock_rt, question)
    t_vec = time.time() - t0

    # Step 3: Graph retrieval
    t0 = time.time()
    graph_results = graph_retrieve(neptune, search_terms)
    t_graph = time.time() - t0

    # Step 4: Build context
    vec_context, graph_context = build_context(vec_results, graph_results)

    # Step 5: Generate answer
    t0 = time.time()
    max_tok = 5000 if len(question) > 300 else 4096
    answer, usage = generate_answer(bedrock_rt, question, vec_context, graph_context, max_tok)
    t_answer = time.time() - t0

    t_total = time.time() - t_start

    result = {
        "question": question,
        "language": "zh-CN",
        "search_terms": search_terms,
        "vector_hits": len(vec_results),
        "graph_entities": len(graph_results),
        "graph_neighbors": sum(len(r.get("neighbors", [])) for r in graph_results),
        "answer": answer,
        "answer_length": len(answer),
        "latency": {"vector": t_vec, "graph": t_graph, "answer": t_answer, "total": t_total},
        "usage": usage,
        "timestamp": datetime.now().isoformat(),
    }

    return result, vec_results, graph_results, vec_context, graph_context


# ======================================================================
# Output Saving
# ======================================================================

def save_outputs(result, vec_results, graph_results, vec_context, graph_context, config):
    """Save answer, debug, and summary files. Returns list of saved paths."""
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine filename prefix
    if config.preset:
        prefix = config.preset
    else:
        prefix = f"custom_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Save answer markdown
    answer_path = output_dir / f"{prefix}_answer.md"
    answer_content = f"# QA Answer — {prefix}\n\n"
    answer_content += f"**Question:** {result['question']}\n\n"
    answer_content += f"**Timestamp:** {result['timestamp']}\n\n"
    answer_content += f"---\n\n{result['answer']}\n"
    answer_path.write_text(answer_content, encoding="utf-8")

    # Save debug JSON
    debug_path = output_dir / f"{prefix}_debug.json"
    debug_data = {
        "result": result,
        "vec_results_count": len(vec_results),
        "vec_results_preview": [
            {
                "source": h.get("source_file_name", ""),
                "distance": h.get("_distance", 0),
                "text_preview": h.get("text", "")[:200],
                "chunk_purpose": h.get("chunk_purpose", ""),
            }
            for h in vec_results[:10]
        ],
        "graph_results_count": len(graph_results),
        "graph_results_preview": [
            {
                "entity": r.get("entity", {}),
                "neighbor_count": len(r.get("neighbors", [])),
                "neighbors_preview": r.get("neighbors", [])[:5],
            }
            for r in graph_results[:10]
        ],
        "vec_context_length": len(vec_context),
        "graph_context_length": len(graph_context),
        "config": {
            "run_id": config.run_id,
            "dataset": config.dataset,
            "collection": config.lancedb_collection,
            "top_k": config.top_k_vector,
            "graph_depth": config.graph_depth,
            "max_graph_edges": config.max_graph_edges,
            "view": config.view,
            "lang": config.lang,
        },
    }
    debug_path.write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save terminal summary
    summary_path = output_dir / f"{prefix}_terminal_summary.md"
    summary = f"# Terminal Summary — {prefix}\n\n"
    summary += f"| Metric | Value |\n|--------|-------|\n"
    summary += f"| Question Length | {len(result['question'])} chars |\n"
    summary += f"| Vector Hits | {result['vector_hits']} |\n"
    summary += f"| Graph Entities | {result['graph_entities']} |\n"
    summary += f"| Graph Neighbors | {result['graph_neighbors']} |\n"
    summary += f"| Answer Length | {result['answer_length']} chars |\n"
    summary += f"| Latency (total) | {result['latency']['total']:.2f}s |\n"
    summary += f"| Input Tokens | {result['usage'].get('input_tokens', 'N/A')} |\n"
    summary += f"| Output Tokens | {result['usage'].get('output_tokens', 'N/A')} |\n"
    summary += f"\n## Search Terms\n\n{', '.join(result['search_terms'])}\n"
    summary += f"\n## Top 3 Vector Sources\n\n"
    for i, h in enumerate(vec_results[:3]):
        summary += f"{i+1}. {h.get('source_file_name', '?')} (dist={h.get('_distance', 0):.3f})\n"
    summary += f"\n## Answer Preview\n\n{result['answer'][:600]}...\n"
    summary_path.write_text(summary, encoding="utf-8")

    saved_files = [str(answer_path), str(debug_path), str(summary_path)]

    # Also save to --output if specified
    if config.output:
        out_path = Path(config.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix in (".md", ".markdown"):
            out_path.write_text(answer_content, encoding="utf-8")
        else:
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_files.append(str(out_path))

    return saved_files


# ======================================================================
# Terminal Renderer
# ======================================================================

class TerminalRenderer:
    """Handles all display logic with Rich (or plain text fallback)."""

    def __init__(self, use_rich=True):
        self.use_rich = use_rich and HAS_RICH
        if self.use_rich:
            self.console = Console()
        else:
            self.console = None

    def _print(self, text=""):
        if self.console:
            self.console.print(text)
        else:
            print(text)

    def render_header(self, config):
        """Panel 1: System info header."""
        if self.use_rich:
            header_text = Text()
            header_text.append("Murata Enterprise GraphRAG", style="bold cyan")
            header_text.append(" v" + VERSION, style="dim")
            header_text.append("\n")
            header_text.append(f"Model: {TEXT_MODEL}", style="green")
            header_text.append(f"  |  Region: {REGION}", style="green")
            header_text.append(f"  |  View: {config.view}", style="yellow")
            header_text.append("\n")
            header_text.append(f"Collection: {config.lancedb_collection}", style="dim")
            header_text.append(f"  |  Run: {config.run_id}", style="dim")
            header_text.append(f"  |  Graph: {config.neptune_graph_id}", style="dim")
            self.console.print(Panel(header_text, title="[bold]GraphRAG QA Terminal[/bold]", border_style="blue"))
        else:
            print("\n" + "=" * 70)
            print("  MURATA ENTERPRISE GRAPHRAG — QA TERMINAL v" + VERSION)
            print(f"  Model: {TEXT_MODEL} | Region: {REGION} | View: {config.view}")
            print(f"  Collection: {config.lancedb_collection} | Run: {config.run_id}")
            print("=" * 70)

    def render_question(self, question, search_terms):
        """Panel 2: Question display."""
        if self.use_rich:
            q_text = Text(question, style="bold white")
            terms_line = Text(f"\nSearch terms: {', '.join(search_terms)}", style="dim cyan")
            content = Text()
            content.append_text(q_text)
            content.append_text(terms_line)
            self.console.print(Panel(content, title="[bold yellow]Question[/bold yellow]", border_style="yellow"))
        else:
            print(f"\n📝 Question:")
            print(f"   {question}")
            print(f"   Search terms: {', '.join(search_terms)}")

    def render_retrieval_summary(self, result):
        """Panel 3: Retrieval summary."""
        if self.use_rich:
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Metric", style="bold")
            table.add_column("Value", style="cyan")
            table.add_row("Vector Hits", str(result["vector_hits"]))
            table.add_row("Graph Entities", str(result["graph_entities"]))
            table.add_row("Graph Neighbors", str(result["graph_neighbors"]))
            table.add_row("Answer Length", f"{result['answer_length']} chars")
            self.console.print(Panel(table, title="[bold green]Retrieval Summary[/bold green]", border_style="green"))
        else:
            print(f"\n📊 Retrieval: {result['vector_hits']} vector hits, "
                  f"{result['graph_entities']} entities, {result['graph_neighbors']} neighbors")

    def render_vector_evidence(self, vec_results, max_items=5, max_chars=300):
        """Panel 4: Vector evidence table."""
        if not vec_results:
            self._print("[dim]No vector evidence found.[/dim]" if self.use_rich else "  No vector evidence found.")
            return

        items = vec_results[:max_items]

        if self.use_rich:
            table = Table(title="Vector Evidence", border_style="blue", show_lines=True)
            table.add_column("Rank", style="bold", width=4, justify="center")
            table.add_column("Dist", style="cyan", width=7, justify="right")
            table.add_column("Chunk", style="dim", width=10)
            table.add_column("Purpose", style="magenta", width=14)
            table.add_column("Source", style="green", width=22)
            table.add_column("Preview", style="white", width=40, no_wrap=True)

            for i, hit in enumerate(items):
                score = f"{hit.get('_distance', 0):.3f}"
                chunk_id = str(hit.get("chunk_id", hit.get("id", "")))[:10]
                purpose = str(hit.get("chunk_purpose", ""))[:14]
                source = str(hit.get("source_file_name", ""))[-22:]
                preview = str(hit.get("text", ""))[:max_chars].replace("\n", " \\n ")[:80]
                table.add_row(str(i + 1), score, chunk_id, purpose, source, preview)

            self.console.print(table)
        else:
            print(f"\n📊 Vector Evidence (top {len(items)}):")
            for i, hit in enumerate(items):
                source = str(hit.get("source_file_name", "?"))[-20:]
                dist = hit.get("_distance", 0)
                print(f"  [{i+1}] {source} (dist={dist:.3f})")
                print(f"      {str(hit.get('text', ''))[:80]}...")

    def render_graph_evidence(self, graph_results, max_items=5, max_chars=300):
        """Panel 5: Graph evidence table."""
        if not graph_results:
            self._print("[dim]No graph evidence found.[/dim]" if self.use_rich else "  No graph evidence found.")
            return

        items = [r for r in graph_results[:max_items] if r.get("entity")]

        if self.use_rich:
            table = Table(title="Graph Evidence", border_style="magenta", show_lines=True)
            table.add_column("Rank", style="bold", width=4, justify="center")
            table.add_column("Entity", style="cyan", width=20)
            table.add_column("Type", style="yellow", width=12)
            table.add_column("Rels", style="green", width=5, justify="center")
            table.add_column("Neighbors (top 3)", style="white", width=50, no_wrap=True)

            for i, item in enumerate(items):
                entity = item.get("entity", {})
                neighbors = item.get("neighbors", [])
                name = str(entity.get("cname", ""))[:20]
                labels = str(entity.get("lbls", ""))[:12]
                rel_count = str(len(neighbors))
                nbr_preview = "; ".join(
                    f"{n.get('rel', '?')}→{n.get('tgt', '?')[:15]}"
                    for n in neighbors[:3]
                )[:80]
                table.add_row(str(i + 1), name, labels, rel_count, nbr_preview)

            self.console.print(table)
        else:
            print(f"\n🕸️  Graph Evidence (top {len(items)}):")
            for i, item in enumerate(items):
                entity = item.get("entity", {})
                neighbors = item.get("neighbors", [])
                print(f"  [{i+1}] {entity.get('cname', '')} ({len(neighbors)} connections)")
                for nbr in neighbors[:3]:
                    print(f"      → {nbr.get('rel', '?')} → {nbr.get('tgt', '?')}")

    def render_fusion_context(self, vec_context, graph_context, full=False):
        """Panel 6: Fusion context (summarized or full)."""
        if self.use_rich:
            if full:
                content = Text()
                content.append("=== Vector Context ===\n", style="bold blue")
                content.append(vec_context[:3000] if len(vec_context) > 3000 else vec_context)
                content.append("\n\n=== Graph Context ===\n", style="bold magenta")
                content.append(graph_context[:3000] if len(graph_context) > 3000 else graph_context)
                self.console.print(Panel(content, title="[bold]Fusion Context[/bold]", border_style="cyan"))
            else:
                summary = Text()
                summary.append(f"Vector context: {len(vec_context)} chars", style="blue")
                summary.append(" | ", style="dim")
                summary.append(f"Graph context: {len(graph_context)} chars", style="magenta")
                self.console.print(Panel(summary, title="[bold]Fusion Context Summary[/bold]", border_style="cyan"))
        else:
            if full:
                print(f"\n--- Fusion Context ---")
                print(f"[Vector] ({len(vec_context)} chars):")
                print(vec_context[:1000])
                print(f"\n[Graph] ({len(graph_context)} chars):")
                print(graph_context[:1000])
            else:
                print(f"\n🔗 Fusion: Vector={len(vec_context)} chars, Graph={len(graph_context)} chars")

    def render_answer(self, answer, use_pager=False):
        """Panel 7: Final answer rendered as Markdown."""
        if self.use_rich:
            # Detect CSV content (for Q4)
            has_csv = ("nodes.csv" in answer.lower() or "id,label,type" in answer or
                       "from,to,relation" in answer)

            if has_csv:
                # Extract and render CSV blocks specially
                lines = answer.split("\n")
                md_parts = []
                csv_block = []
                in_csv = False

                for line in lines:
                    if ("id,label,type" in line or "from,to,relation" in line or
                            (in_csv and "," in line and not line.startswith("#"))):
                        in_csv = True
                        csv_block.append(line)
                    else:
                        if in_csv and csv_block:
                            md_parts.append(("csv", "\n".join(csv_block)))
                            csv_block = []
                            in_csv = False
                        md_parts.append(("md", line))

                if csv_block:
                    md_parts.append(("csv", "\n".join(csv_block)))

                if use_pager:
                    with self.console.pager(styles=True):
                        self.console.print(Rule("Answer", style="green"))
                        for kind, content in md_parts:
                            if kind == "csv":
                                self.console.print(Syntax(content, "csv", theme="monokai"))
                            else:
                                self.console.print(RichMarkdown(content))
                else:
                    self.console.print(Panel.fit(
                        Text("Answer contains CSV data - rendered below"),
                        border_style="green"
                    ))
                    for kind, content in md_parts:
                        if kind == "csv":
                            self.console.print(Syntax(content, "csv", theme="monokai"))
                        else:
                            if content.strip():
                                self.console.print(RichMarkdown(content))
            else:
                if use_pager:
                    with self.console.pager(styles=True):
                        self.console.print(Rule("Answer", style="green"))
                        self.console.print(RichMarkdown(answer))
                else:
                    self.console.print(Panel(
                        RichMarkdown(answer),
                        title="[bold green]Answer[/bold green]",
                        border_style="green",
                    ))
        else:
            print(f"\n💡 Answer:")
            print("   " + "-" * 60)
            for line in answer.split("\n"):
                print(f"   {line}")
            print("   " + "-" * 60)

    def render_citations(self, vec_results, graph_results):
        """Panel 8: Citations from sources."""
        if self.use_rich:
            sources = set()
            for hit in vec_results[:10]:
                src = hit.get("source_file_name", "")
                if src:
                    sources.add(src)
            for item in graph_results[:10]:
                entity = item.get("entity", {})
                if entity.get("cname"):
                    sources.add(f"[Graph] {entity['cname']}")

            if sources:
                citation_text = Text()
                for i, src in enumerate(sorted(sources)[:15]):
                    citation_text.append(f"[{i+1}] ", style="bold")
                    citation_text.append(src + "\n", style="dim")
                self.console.print(Panel(citation_text, title="[bold]Citations[/bold]", border_style="dim"))
        else:
            sources = set()
            for hit in vec_results[:10]:
                src = hit.get("source_file_name", "")
                if src:
                    sources.add(src)
            if sources:
                print("\n📎 Citations:")
                for i, src in enumerate(sorted(sources)[:10]):
                    print(f"   [{i+1}] {src}")

    def render_latency(self, latency, usage):
        """Panel 9: Latency metrics."""
        if self.use_rich:
            metrics = Text()
            metrics.append(f"Vector: {latency['vector']:.3f}s", style="blue")
            metrics.append(" | ", style="dim")
            metrics.append(f"Graph: {latency['graph']:.3f}s", style="magenta")
            metrics.append(" | ", style="dim")
            metrics.append(f"Answer: {latency['answer']:.1f}s", style="green")
            metrics.append(" | ", style="dim")
            metrics.append(f"Total: {latency['total']:.1f}s", style="bold yellow")
            metrics.append("\n")
            metrics.append(f"Tokens: {usage.get('input_tokens', '?')} in / {usage.get('output_tokens', '?')} out", style="cyan")
            self.console.print(Panel(metrics, title="[bold]Latency & Usage[/bold]", border_style="yellow"))
        else:
            print(f"\n⏱️  Latency: Vector={latency['vector']:.3f}s Graph={latency['graph']:.3f}s "
                  f"Answer={latency['answer']:.1f}s Total={latency['total']:.1f}s")
            print(f"   Tokens: {usage.get('input_tokens', '?')} in / {usage.get('output_tokens', '?')} out")

    def render_saved_files(self, files):
        """Panel 10: Saved file paths."""
        if not files:
            return
        if self.use_rich:
            file_text = Text()
            for f in files:
                file_text.append("  📄 ", style="green")
                file_text.append(f + "\n", style="dim white")
            self.console.print(Panel(file_text, title="[bold]Saved Files[/bold]", border_style="green"))
        else:
            print(f"\n💾 Saved Files:")
            for f in files:
                print(f"   📄 {f}")

    def render_compact(self, result, vec_results, graph_results, config):
        """Compact view: question + short answer + top 3 evidence + latency."""
        self.render_question(result["question"], result["search_terms"])

        # Short answer preview
        preview = result["answer"][:config.max_preview_chars]
        if self.use_rich:
            self.console.print(Panel(
                Text(preview + ("..." if len(result["answer"]) > config.max_preview_chars else ""),
                     style="white"),
                title="[bold green]Answer Preview[/bold green]",
                border_style="green",
            ))
        else:
            print(f"\n💡 Answer Preview:")
            print(f"   {preview[:200]}...")

        self.render_vector_evidence(vec_results, max_items=3, max_chars=config.max_evidence_preview_chars)
        self.render_graph_evidence(graph_results, max_items=3, max_chars=config.max_evidence_preview_chars)
        self.render_latency(result["latency"], result["usage"])

    def render_demo(self, result, vec_results, graph_results, vec_context, graph_context, config):
        """Demo view: pretty header + summary + top 5 evidence + full answer + saved files."""
        self.render_header(config)
        self.render_question(result["question"], result["search_terms"])
        self.render_retrieval_summary(result)
        if config.show_vector_evidence:
            self.render_vector_evidence(vec_results, max_items=5, max_chars=config.max_evidence_preview_chars)
        if config.show_graph_evidence:
            self.render_graph_evidence(graph_results, max_items=5, max_chars=config.max_evidence_preview_chars)
        if config.show_fusion_context:
            self.render_fusion_context(vec_context, graph_context, full=False)
        self.render_answer(result["answer"], use_pager=False)
        self.render_citations(vec_results, graph_results)
        if config.show_latency:
            self.render_latency(result["latency"], result["usage"])

    def render_debug(self, result, vec_results, graph_results, vec_context, graph_context, config):
        """Debug view: all of demo + full evidence + extraction details + fusion context."""
        self.render_header(config)
        self.render_question(result["question"], result["search_terms"])
        self.render_retrieval_summary(result)

        # Entity extraction details
        if self.use_rich:
            ext_text = Text()
            ext_text.append("Extracted search terms:\n", style="bold")
            for term in result["search_terms"]:
                ext_text.append(f"  • {term}\n", style="cyan")
            ext_text.append(f"\nQuestion length: {len(result['question'])} chars\n", style="dim")
            ext_text.append(f"Language: {result['language']}\n", style="dim")
            self.console.print(Panel(ext_text, title="[bold]Entity Extraction Details[/bold]", border_style="red"))
        else:
            print(f"\n🔍 Entity Extraction Details:")
            for term in result["search_terms"]:
                print(f"   • {term}")

        # Full evidence
        self.render_vector_evidence(vec_results, max_items=len(vec_results), max_chars=config.max_evidence_preview_chars)
        self.render_graph_evidence(graph_results, max_items=len(graph_results), max_chars=config.max_evidence_preview_chars)

        # Full fusion context
        self.render_fusion_context(vec_context, graph_context, full=True)

        self.render_answer(result["answer"], use_pager=False)
        self.render_citations(vec_results, graph_results)
        self.render_latency(result["latency"], result["usage"])

        # Warnings
        warnings = []
        if result["vector_hits"] == 0:
            warnings.append("No vector hits found - collection may be empty or query too specific")
        if result["graph_entities"] == 0:
            warnings.append("No graph entities found - check Neptune connectivity")
        if result["latency"]["total"] > 60:
            warnings.append(f"High total latency: {result['latency']['total']:.1f}s")
        for item in graph_results:
            if item.get("error"):
                warnings.append(f"Graph error for '{item.get('term', '?')}': {item['error'][:80]}")

        if warnings and self.use_rich:
            warn_text = Text()
            for w in warnings:
                warn_text.append(f"⚠️  {w}\n", style="bold yellow")
            self.console.print(Panel(warn_text, title="[bold yellow]Warnings[/bold yellow]", border_style="yellow"))
        elif warnings:
            print("\n⚠️  Warnings:")
            for w in warnings:
                print(f"   {w}")

    def render_full(self, result, vec_results, graph_results, vec_context, graph_context, config):
        """Full view: everything via pager."""
        if self.use_rich and config.pager:
            with self.console.pager(styles=True):
                self._render_full_content(result, vec_results, graph_results, vec_context, graph_context, config)
        else:
            self._render_full_content(result, vec_results, graph_results, vec_context, graph_context, config)

    def _render_full_content(self, result, vec_results, graph_results, vec_context, graph_context, config):
        """Internal: render all content (used inside or outside pager)."""
        self.render_header(config)
        self.render_question(result["question"], result["search_terms"])
        self.render_retrieval_summary(result)

        # Entity extraction details
        if self.use_rich:
            ext_text = Text()
            ext_text.append("Extracted search terms:\n", style="bold")
            for term in result["search_terms"]:
                ext_text.append(f"  • {term}\n", style="cyan")
            ext_text.append(f"\nQuestion length: {len(result['question'])} chars\n", style="dim")
            ext_text.append(f"Language: {result['language']}\n", style="dim")
            self.console.print(Panel(ext_text, title="[bold]Entity Extraction Details[/bold]", border_style="red"))
        else:
            print(f"\n🔍 Entity Extraction:")
            for term in result["search_terms"]:
                print(f"   • {term}")

        # Full vector evidence
        self.render_vector_evidence(vec_results, max_items=len(vec_results), max_chars=config.max_preview_chars)

        # Full graph evidence
        self.render_graph_evidence(graph_results, max_items=len(graph_results), max_chars=config.max_preview_chars)

        # Full fusion context
        self.render_fusion_context(vec_context, graph_context, full=True)

        # Full answer
        self.render_answer(result["answer"], use_pager=False)

        # Citations
        self.render_citations(vec_results, graph_results)

        # Latency
        self.render_latency(result["latency"], result["usage"])

    def render_view(self, result, vec_results, graph_results, vec_context, graph_context, config):
        """Route to appropriate view mode renderer."""
        view = config.view
        if view == "compact":
            self.render_compact(result, vec_results, graph_results, config)
        elif view == "demo":
            self.render_demo(result, vec_results, graph_results, vec_context, graph_context, config)
        elif view == "debug":
            self.render_debug(result, vec_results, graph_results, vec_context, graph_context, config)
        elif view == "full":
            self.render_full(result, vec_results, graph_results, vec_context, graph_context, config)
        else:
            self.render_demo(result, vec_results, graph_results, vec_context, graph_context, config)

    def render_init_status(self, tbl, config):
        """Show initialization status."""
        if self.use_rich:
            self.console.print(Rule("Initializing", style="blue"))
            self.console.print(f"  [green]✓[/green] LanceDB: {config.lancedb_collection} ({tbl.count_rows()} records)")
            self.console.print(f"  [green]✓[/green] Neptune: {config.run_id} (graph: {config.neptune_graph_id})")
            self.console.print(f"  [green]✓[/green] Bedrock: {TEXT_MODEL}")
            self.console.print(Rule(style="blue"))
        else:
            print(f"\n✅ LanceDB: {config.lancedb_collection} ({tbl.count_rows()} records)")
            print(f"✅ Neptune: {config.run_id}")
            print(f"✅ Bedrock: {TEXT_MODEL}")

    def render_interactive_help(self):
        """Show interactive mode help."""
        if self.use_rich:
            help_text = Text()
            help_text.append("Commands:\n", style="bold")
            help_text.append("  q1-q5    ", style="cyan")
            help_text.append("Run preset question\n")
            help_text.append("  ask      ", style="cyan")
            help_text.append("Enter custom question\n")
            help_text.append("  view     ", style="cyan")
            help_text.append("Change view mode (compact/demo/debug/full)\n")
            help_text.append("  help     ", style="cyan")
            help_text.append("Show this help\n")
            help_text.append("  exit     ", style="cyan")
            help_text.append("Quit\n")
            self.console.print(Panel(help_text, title="[bold]Interactive Mode[/bold]", border_style="blue"))
        else:
            print("\n  Commands: q1-q5 (presets), ask (custom), view (change mode), help, exit")

    def render_post_answer_menu(self):
        """Show post-answer interactive menu."""
        if self.use_rich:
            menu = Text()
            menu.append("[Enter]", style="bold cyan")
            menu.append(" next  ")
            menu.append("v", style="bold cyan")
            menu.append("=vector  ")
            menu.append("g", style="bold cyan")
            menu.append("=graph  ")
            menu.append("f", style="bold cyan")
            menu.append("=fusion  ")
            menu.append("a", style="bold cyan")
            menu.append("=full answer  ")
            menu.append("s", style="bold cyan")
            menu.append("=saved files  ")
            menu.append("q", style="bold cyan")
            menu.append("=quit")
            self.console.print(Panel(menu, border_style="dim"))
        else:
            print("\n  [Enter] next, v=vector, g=graph, f=fusion, a=full answer, s=saved files, q=quit")

    def pause(self):
        """Pause between sections."""
        input("  [Press Enter to continue...]")


# ======================================================================
# Main
# ======================================================================

def build_parser():
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Murata Enterprise GraphRAG — QA Terminal Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python scripts/qa_terminal_demo.py --preset q1\n"
               "  python scripts/qa_terminal_demo.py -q 'your question' --view debug\n"
               "  python scripts/qa_terminal_demo.py --interactive --view demo\n"
    )
    parser.add_argument("--question", "-q", help="Direct question to answer")
    parser.add_argument("--preset", "-p", choices=["q1", "q2", "q3", "q4", "q5"],
                        help="Use preset question")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--output", "-o", help="Save result to JSON file")
    parser.add_argument("--run-id", default=RUN_ID, help="Run ID (default: murata_rebuild_v1)")
    parser.add_argument("--dataset", default=DATASET, help="Dataset name (default: murata)")
    parser.add_argument("--lancedb-collection", default=COLLECTION,
                        help="LanceDB collection (default: murata_e2e_murata_rebuild_v1)")
    parser.add_argument("--neptune-graph-id", default="g-nbuyck5yl8",
                        help="Neptune graph ID (default: g-nbuyck5yl8)")
    parser.add_argument("--view", choices=["compact", "demo", "debug", "full"], default="demo",
                        help="View mode (default: demo)")
    parser.add_argument("--lang", choices=["zh", "ja", "en", "auto"], default="zh",
                        help="Output language (default: zh)")
    parser.add_argument("--top-k-vector", type=int, default=TOP_K,
                        help="Top-K for vector retrieval (default: 10)")
    parser.add_argument("--graph-depth", type=int, default=GRAPH_DEPTH,
                        help="Graph traversal depth (default: 2)")
    parser.add_argument("--max-graph-edges", type=int, default=MAX_EDGES,
                        help="Max graph edges per entity (default: 30)")
    parser.add_argument("--show-vector-evidence", type=str2bool, default=True,
                        help="Show vector evidence panel (default: true)")
    parser.add_argument("--show-graph-evidence", type=str2bool, default=True,
                        help="Show graph evidence panel (default: true)")
    parser.add_argument("--show-fusion-context", type=str2bool, default=True,
                        help="Show fusion context panel (default: true)")
    parser.add_argument("--show-latency", type=str2bool, default=True,
                        help="Show latency panel (default: true)")
    parser.add_argument("--export-trace", type=str2bool, default=True,
                        help="Export debug trace (default: true)")
    parser.add_argument("--pager", type=str2bool, default=True,
                        help="Use pager for full view (default: true)")
    parser.add_argument("--pause-between-sections", type=str2bool, default=False,
                        help="Pause between display sections (default: false)")
    parser.add_argument("--max-preview-chars", type=int, default=600,
                        help="Max chars in answer preview (default: 600)")
    parser.add_argument("--max-evidence-preview-chars", type=int, default=300,
                        help="Max chars per evidence preview (default: 300)")
    parser.add_argument("--output-dir", default="docs/demo_outputs",
                        help="Output directory (default: docs/demo_outputs)")
    return parser


def run_single_query(tbl, neptune, bedrock_rt, question, config, renderer):
    """Execute a single query and render + save results."""
    # Run QA pipeline
    result, vec_results, graph_results, vec_context, graph_context = run_qa(
        tbl, neptune, bedrock_rt, question, verbose=False
    )

    # Render output
    renderer.render_view(result, vec_results, graph_results, vec_context, graph_context, config)

    # Save outputs
    saved_files = save_outputs(result, vec_results, graph_results, vec_context, graph_context, config)
    renderer.render_saved_files(saved_files)

    return result, vec_results, graph_results, vec_context, graph_context, saved_files


def interactive_loop(tbl, neptune, bedrock_rt, config, renderer):
    """Run interactive QA loop."""
    renderer.render_interactive_help()

    while True:
        if HAS_RICH and renderer.use_rich:
            renderer.console.print("\n[bold cyan]❓ Command:[/bold cyan] ", end="")
        else:
            print("\n❓ Command: ", end="")

        try:
            cmd = input().strip()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd.lower() in ("exit", "quit"):
            break
        elif cmd.lower() == "help":
            renderer.render_interactive_help()
            continue
        elif cmd.lower() in ("q1", "q2", "q3", "q4", "q5"):
            config.preset = cmd.lower()
            question = PRESETS[cmd.lower()]
        elif cmd.lower() == "ask":
            if HAS_RICH and renderer.use_rich:
                renderer.console.print("[dim]Enter your question:[/dim] ", end="")
            else:
                print("Enter your question: ", end="")
            try:
                question = input().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            config.preset = None
        elif cmd.lower().startswith("view"):
            parts = cmd.split()
            if len(parts) > 1 and parts[1] in ("compact", "demo", "debug", "full"):
                config.view = parts[1]
                if HAS_RICH and renderer.use_rich:
                    renderer.console.print(f"[green]View changed to: {config.view}[/green]")
                else:
                    print(f"  View changed to: {config.view}")
            else:
                if HAS_RICH and renderer.use_rich:
                    renderer.console.print("[yellow]Usage: view <compact|demo|debug|full>[/yellow]")
                else:
                    print("  Usage: view <compact|demo|debug|full>")
            continue
        else:
            # Treat as direct question
            if not cmd:
                continue
            question = cmd
            config.preset = None

        # Run query
        result, vec_results, graph_results, vec_context, graph_context, saved_files = run_single_query(
            tbl, neptune, bedrock_rt, question, config, renderer
        )

        # Post-answer interactive menu
        renderer.render_post_answer_menu()
        while True:
            try:
                post_cmd = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return

            if post_cmd == "" or post_cmd == "n":
                break
            elif post_cmd == "v":
                renderer.render_vector_evidence(
                    vec_results, max_items=len(vec_results),
                    max_chars=config.max_preview_chars
                )
            elif post_cmd == "g":
                renderer.render_graph_evidence(
                    graph_results, max_items=len(graph_results),
                    max_chars=config.max_preview_chars
                )
            elif post_cmd == "f":
                renderer.render_fusion_context(vec_context, graph_context, full=True)
            elif post_cmd == "a":
                renderer.render_answer(result["answer"], use_pager=config.pager)
            elif post_cmd == "s":
                renderer.render_saved_files(saved_files)
            elif post_cmd == "q":
                return
            else:
                renderer.render_post_answer_menu()


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Create renderer
    renderer = TerminalRenderer(use_rich=HAS_RICH)

    # Update global config from args
    global COLLECTION, RUN_ID, DATASET, TOP_K, GRAPH_DEPTH, MAX_EDGES
    COLLECTION = args.lancedb_collection
    RUN_ID = args.run_id
    DATASET = args.dataset
    TOP_K = args.top_k_vector
    GRAPH_DEPTH = args.graph_depth
    MAX_EDGES = args.max_graph_edges

    # Initialize clients
    if renderer.use_rich:
        renderer.console.print("\n[bold blue]🚀 Initializing Murata Enterprise GraphRAG...[/bold blue]")
    else:
        print("\n🚀 Initializing Murata Enterprise GraphRAG...")

    tbl, neptune, bedrock_rt = init_clients()
    renderer.render_init_status(tbl, args)

    if args.interactive:
        interactive_loop(tbl, neptune, bedrock_rt, args, renderer)
    elif args.preset:
        args.preset = args.preset
        question = PRESETS[args.preset]
        run_single_query(tbl, neptune, bedrock_rt, question, args, renderer)
    elif args.question:
        args.preset = None
        run_single_query(tbl, neptune, bedrock_rt, args.question, args, renderer)
    else:
        # Default: run Q1 as demo
        if renderer.use_rich:
            renderer.console.print("\n[dim]Running Q1 as demo (use --interactive for live mode)...[/dim]")
        else:
            print("\n  Running Q1 as demo (use --interactive for live mode)...")
        args.preset = "q1"
        question = PRESETS["q1"]
        run_single_query(tbl, neptune, bedrock_rt, question, args, renderer)


if __name__ == "__main__":
    main()
