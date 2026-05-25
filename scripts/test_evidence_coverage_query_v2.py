#!/usr/bin/env python
"""
P0 Regression Test: Evidence Coverage Query Handler.

Tests that Q7-like queries about evidence coverage are answered correctly
using actual coverage stats, without claiming nodes lack evidence when
coverage is 100%.

Usage (no-LLM, fast):
    PYTHONPATH=src python scripts/test_evidence_coverage_query_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --no-llm \
      --debug

Usage (LLM mode):
    PYTHONPATH=src python scripts/test_evidence_coverage_query_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --debug
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


# Test queries that should trigger evidence_coverage intent
EVIDENCE_COVERAGE_QUERIES = [
    "当前图谱中有哪些节点没有 evidence，需要后续人工补充文档？",
    "nodes without evidence",
    "evidence coverage",
    "哪些节点缺少证据？",
]

# Regression assertions
REQUIRED_IN_ANSWER = [
    "100%",  # Must mention 100% coverage
]

FORBIDDEN_IN_ANSWER = [
    # Must NOT claim nodes lack evidence (unless explicitly saying "0 nodes")
]

REQUIRED_INTENT = "evidence_coverage"


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 Evidence Coverage Regression Test")
    parser.add_argument("--config", type=str, default="configs/murata_semantic_v2.yaml")
    parser.add_argument("--run-id", type=str, default="murata_semantic_v2")
    parser.add_argument("--dataset", type=str, default="murata")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM, use deterministic preview")
    parser.add_argument("--debug", action="store_true", help="Show full debug output")
    parser.add_argument("--query", type=str, help="Override test query (single query mode)")
    args = parser.parse_args()

    output_dir = Path("data/outputs") / args.run_id

    # Import V2 modules
    from hermes_bedrock_agent.v2.qa.answer_generator import AnswerGeneratorV2, ContextBudget
    from hermes_bedrock_agent.v2.retrieval.hybrid_context_builder import HybridContextBuilder
    from hermes_bedrock_agent.v2.retrieval.evidence_coverage_stats import compute_evidence_coverage_stats

    print("=" * 70)
    print("P0 Regression Test: Evidence Coverage Query Handler")
    print("=" * 70)
    print(f"  run_id: {args.run_id}")
    print(f"  dataset: {args.dataset}")
    print(f"  output_dir: {output_dir}")
    print(f"  mode: {'no_llm' if args.no_llm else 'llm'}")
    print()

    # Compute actual stats first
    print("[1/4] Computing actual evidence coverage stats...")
    stats = compute_evidence_coverage_stats(output_dir)
    print(f"  linked_nodes_total: {stats['linked_nodes_total']}")
    print(f"  nodes_with_evidence_links: {stats['nodes_with_evidence_links']}")
    print(f"  nodes_without_evidence_links: {stats['nodes_without_evidence_links']}")
    print(f"  node_evidence_coverage: {stats['node_evidence_coverage_pct']}")
    print(f"  linked_edges_total: {stats['linked_edges_total']}")
    print(f"  edges_with_evidence_links: {stats['edges_with_evidence_links']}")
    print(f"  edges_without_evidence_links: {stats['edges_without_evidence_links']}")
    print(f"  edge_evidence_coverage: {stats['edge_evidence_coverage_pct']}")
    print(f"  api_node_count: {stats['api_node_count']}")
    print(f"  isolated_node_count: {stats['isolated_node_count']}")
    print()

    # Initialize QA pipeline
    print("[2/4] Initializing QA pipeline...")
    budget = ContextBudget(max_evidence_chunks=12, max_total_context_chars=12000)
    context_builder = HybridContextBuilder(output_dir=output_dir)
    answer_gen = AnswerGeneratorV2(budget=budget)
    print("  OK")
    print()

    # Select queries
    queries = [args.query] if args.query else EVIDENCE_COVERAGE_QUERIES

    # Run tests
    print(f"[3/4] Running {len(queries)} evidence coverage queries...")
    print()

    all_passed = True
    results = []

    for i, query in enumerate(queries, 1):
        print(f"  --- Query {i}: {query[:60]}{'...' if len(query) > 60 else ''}")

        start = time.time()

        # Route
        plan = context_builder.router.route(query)
        intent = plan.intent
        context = context_builder.build_context(query, plan)

        # Generate answer
        result = answer_gen.generate_answer(
            query=query,
            hybrid_context=context,
            use_llm=not args.no_llm,
        )
        elapsed = time.time() - start

        answer = result['answer']
        mode = result['mode']

        if args.debug:
            print(f"      intent: {intent}")
            print(f"      mode: {mode}")
            print(f"      elapsed: {elapsed:.2f}s")
            print(f"      context_chars: {result.get('context_chars', 0)}")
            print(f"      reasoning_constraints: {len(context.reasoning_constraints)}")
            print(f"      evidence_coverage_stats in metadata: {'evidence_coverage_stats' in context.metadata}")
            print()
            print("      --- ANSWER ---")
            for line in answer.split('\n')[:30]:
                print(f"      {line}")
            if len(answer.split('\n')) > 30:
                print(f"      ... ({len(answer.split(chr(10)))} lines total)")
            print("      --- END ---")
            print()

        # Run assertions
        test_pass = True
        failures = []

        # Assert 1: Intent must be evidence_coverage
        if intent != REQUIRED_INTENT:
            test_pass = False
            failures.append(f"FAIL: intent={intent}, expected={REQUIRED_INTENT}")

        # Assert 2: Answer must contain "100%" (could be "100%" or "100.0%")
        if "100%" not in answer and "100.0%" not in answer:
            test_pass = False
            failures.append("FAIL: answer does not contain '100%' or '100.0%'")

        # Assert 3: Answer must contain "0" (nodes without evidence = 0)
        # Look for "= 0" or "没有缺少" or "no nodes without"
        has_zero_claim = (
            "= 0" in answer
            or "没有缺少" in answer
            or "no nodes without" in answer
            or "存在しません" in answer
            or "nodes_without_evidence_links = 0" in answer
        )
        if not has_zero_claim:
            test_pass = False
            failures.append("FAIL: answer does not claim zero nodes without evidence")

        # Assert 4: Answer must NOT falsely claim nodes lack evidence
        # Pattern: "以下节点没有 evidence" or "these nodes lack evidence"
        false_claims = [
            "以下节点没有",
            "以下节点缺少",
            "these nodes lack evidence",
            "following nodes do not have evidence",
        ]
        for claim in false_claims:
            if claim.lower() in answer.lower():
                test_pass = False
                failures.append(f"FAIL: answer contains false claim: '{claim}'")

        # Assert 5: Answer should mention API docs as a limitation
        mentions_api = (
            "API" in answer
            or "api" in answer.lower()
        )
        if not mentions_api:
            # Not a hard fail, but warn
            failures.append("WARN: answer does not mention API documentation gap")

        if not test_pass:
            all_passed = False

        result_record = {
            'query': query,
            'intent': intent,
            'mode': mode,
            'passed': test_pass,
            'failures': failures,
            'elapsed': round(elapsed, 2),
        }
        results.append(result_record)

        status = "PASS" if test_pass else "FAIL"
        print(f"      Result: {status}")
        if failures:
            for f in failures:
                print(f"        {f}")
        print()

    # Summary
    print("=" * 70)
    print(f"[4/4] SUMMARY")
    print(f"  Total queries: {len(results)}")
    print(f"  Passed: {sum(1 for r in results if r['passed'])}")
    print(f"  Failed: {sum(1 for r in results if not r['passed'])}")
    print(f"  Overall: {'PASS' if all_passed else 'FAIL'}")
    print()
    print(f"  Evidence Stats Verification:")
    print(f"    nodes_without_evidence_links = {stats['nodes_without_evidence_links']}")
    print(f"    edges_without_evidence_links = {stats['edges_without_evidence_links']}")
    print(f"    coverage = {stats['node_evidence_coverage_pct']} nodes / {stats['edge_evidence_coverage_pct']} edges")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
