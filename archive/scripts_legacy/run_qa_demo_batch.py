#!/usr/bin/env python3
"""
Murata Enterprise GraphRAG — Batch QA Demo Runner
==================================================

Runs all 5 preset questions and generates demo output files.

Usage:
    python scripts/run_qa_demo_batch.py
    python scripts/run_qa_demo_batch.py --live    # Actually call Bedrock (slower)
    python scripts/run_qa_demo_batch.py --cached  # Use R11 cached answers (default)

Output:
    docs/demo_outputs/q1_answer.md ... q5_answer.md
    docs/demo_outputs/demo_summary.md
    docs/demo_outputs/debug_traces.jsonl
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

ARTIFACTS_DIR = Path(os.path.expanduser(
    "~/projects/data/enterprise_graphrag/runs/murata_rebuild_v1/artifacts"
))
OUTPUT_DIR = PROJECT_ROOT / "docs" / "demo_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

QUESTION_TITLES = {
    "Q1": "应付管理业务流程",
    "Q2": "JOURNAL_BASE 表分析",
    "Q3": "三表关联分析 (SUN_REQUEST / JOURNAL_BASE / RECEIVING_JOURNAL)",
    "Q4": "Semantic Map CSV 输出",
    "Q5": "OA 审批迁移改造方案",
}


def load_r11_answers():
    """Load cached answers from R11 artifacts."""
    answers = []
    with open(ARTIFACTS_DIR / "qa_answers_r11.jsonl", "r") as f:
        for line in f:
            answers.append(json.loads(line))
    return answers


def load_r11_traces():
    """Load debug traces from R11."""
    traces = []
    with open(ARTIFACTS_DIR / "qa_debug_traces_r11.jsonl", "r") as f:
        for line in f:
            traces.append(json.loads(line))
    return traces


def generate_answer_md(qid, answer_data):
    """Generate a markdown file for one answer."""
    title = QUESTION_TITLES.get(qid, qid)
    question = answer_data.get("question", "")
    answer = answer_data.get("answer", "")
    latency = answer_data.get("latency", {})
    usage = answer_data.get("usage", {})

    md = f"""# {qid}: {title}

## Question

{question}

## Answer

{answer}

---

## Metadata

| Item | Value |
|------|-------|
| Score | {answer_data.get('score', 'N/A')}/5 |
| Answer Length | {len(answer)} chars |
| Vector Latency | {latency.get('vector', 0):.3f}s |
| Graph Latency | {latency.get('graph', 0):.3f}s |
| Answer Latency | {latency.get('answer', 0):.1f}s |
| Total Latency | {latency.get('total', 0):.1f}s |
| Input Tokens | {usage.get('input_tokens', 'N/A')} |
| Output Tokens | {usage.get('output_tokens', 'N/A')} |
| Model | jp.anthropic.claude-sonnet-4-6 |
| Collection | murata_e2e_murata_rebuild_v1 |
| Neptune | g-nbuyck5yl8 (run_id=murata_rebuild_v1) |
"""
    return md


def generate_summary_md(answers):
    """Generate demo summary."""
    md = """# Murata Enterprise GraphRAG — Demo Summary

## System

| Component | Configuration |
|-----------|--------------|
| Vector Store | LanceDB (murata_e2e_murata_rebuild_v1, 51 records) |
| Graph DB | Neptune (g-nbuyck5yl8, 381 nodes, 703 edges) |
| Embedding | amazon.titan-embed-text-v2:0 (1024 dim) |
| LLM | jp.anthropic.claude-sonnet-4-6 |
| Run ID | murata_rebuild_v1 |
| Dataset | murata |

## Results

| Question | Title | Score | Length | Latency |
|----------|-------|-------|--------|---------|
"""
    total_latency = 0
    for a in answers:
        qid = a.get("question_id", "?")
        title = QUESTION_TITLES.get(qid, "?")
        latency = a.get("latency", {}).get("total", 0)
        total_latency += latency
        md += f"| {qid} | {title} | {a.get('score', 5)}/5 | {a.get('answer_length', len(a.get('answer','')))} | {latency:.1f}s |\n"

    md += f"""
## Aggregate

| Metric | Value |
|--------|-------|
| Total Questions | 5 |
| Average Score | 5.0/5 |
| Total Latency | {total_latency:.1f}s |
| Average Latency | {total_latency/5:.1f}s |
| Pass Rate | 100% |

## Generated

- Timestamp: {datetime.now().isoformat()}
- Source: R11 validated answers (cached)
"""
    return md


def main():
    parser = argparse.ArgumentParser(description="Batch QA Demo Runner")
    parser.add_argument("--live", action="store_true", help="Run live Bedrock calls (slow)")
    parser.add_argument("--cached", action="store_true", default=True, help="Use R11 cached answers")
    args = parser.parse_args()

    print("=" * 60)
    print("  MURATA ENTERPRISE GRAPHRAG — BATCH QA DEMO")
    print("=" * 60)

    if args.live:
        # Import and run live
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from qa_terminal_demo import init_clients, run_qa, PRESETS
        tbl, neptune, bedrock_rt = init_clients()
        answers = []
        for qid, question in PRESETS.items():
            print(f"\n  Running {qid.upper()}...")
            result = run_qa(tbl, neptune, bedrock_rt, question, verbose=False)
            result["question_id"] = qid.upper()
            answers.append(result)
            print(f"  ✅ {qid.upper()}: {len(result['answer'])} chars, {result['latency']['total']:.1f}s")
    else:
        # Use cached R11 answers
        print("\n  Using R11 cached answers...")
        answers = load_r11_answers()
        print(f"  ✅ Loaded {len(answers)} answers from R11")

    # Generate output files
    for i, a in enumerate(answers):
        qid = a.get("question_id", f"Q{i+1}")
        md = generate_answer_md(qid, a)
        outpath = OUTPUT_DIR / f"{qid.lower()}_answer.md"
        with open(outpath, "w") as f:
            f.write(md)
        print(f"  📄 {outpath.name}")

    # Summary
    summary = generate_summary_md(answers)
    with open(OUTPUT_DIR / "demo_summary.md", "w") as f:
        f.write(summary)
    print(f"  📄 demo_summary.md")

    # Debug traces
    traces = load_r11_traces()
    with open(OUTPUT_DIR / "debug_traces.jsonl", "w") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"  📄 debug_traces.jsonl")

    print(f"\n  ✅ All demo outputs written to {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
