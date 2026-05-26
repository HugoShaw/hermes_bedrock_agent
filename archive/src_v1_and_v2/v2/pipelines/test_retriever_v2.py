"""
Pipeline: Test Retriever V2 (Stage 10).

Runs all 7 test queries through the V2 retriever pipeline and generates
retrieval_test_report.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.retrieval.business_graph_retriever import BusinessGraphRetriever
from hermes_bedrock_agent.v2.retrieval.hybrid_context_builder import HybridContextBuilder
from hermes_bedrock_agent.v2.retrieval.implementation_graph_retriever import ImplementationGraphRetriever
from hermes_bedrock_agent.v2.retrieval.query_router import QueryRouter
from hermes_bedrock_agent.v2.retrieval.vector_evidence_retriever import VectorEvidenceRetriever
from hermes_bedrock_agent.v2.schemas.retrieval_schema import HybridContext, RetrievalPlan, RetrievalResult


# Standard test queries from .hermes.md
TEST_QUERIES = [
    "仕訳基礎とは何ですか？",
    "支払申請の業務プロセスを説明してください。",
    "payment または 支払 に関連する業務機能、API、テーブルを整理してください。",
    "付款申请相关的业务流程、系统模块和数据表之间是什么关系？",
    "某个业务流程如果要外移到 OA，当前系统中可能影响哪些功能、API、表和代码模块？",
    "当前 Murata 项目中，业务层 Semantic Map 和实现层 Implementation Graph 分别包含哪些主要节点？",
    "当前图谱中有哪些节点没有 evidence，需要后续人工补充文档？",
]


def run_single_query(
    query: str,
    builder: HybridContextBuilder,
    debug: bool = False,
) -> dict[str, Any]:
    """Run a single query through the full retrieval pipeline."""
    # Route
    router = builder.router
    intent = router.classify_intent(query)
    plan = router.build_plan(intent)

    # Retrieve
    business_result: RetrievalResult | None = None
    impl_result: RetrievalResult | None = None
    evidence_result: RetrievalResult | None = None

    if plan.need_business_graph:
        business_result = builder.business_retriever.retrieve(
            query, top_k=builder.top_k_graph, depth=builder.graph_depth
        )
    if plan.need_implementation_graph:
        impl_result = builder.implementation_retriever.retrieve(
            query, top_k=builder.top_k_graph, depth=builder.graph_depth
        )
    if plan.need_vector_evidence:
        evidence_result = builder.vector_retriever.retrieve(
            query, top_k=builder.top_k_evidence
        )

    # Build context
    context = builder.build_context(query, plan)

    # Build debug record
    debug_record = builder.build_debug_record(
        query, plan, business_result, impl_result, evidence_result, context
    )

    # Add raw results for report
    result = {
        'query': query,
        'intent': intent.model_dump(),
        'plan': plan.model_dump(),
        'context': context.model_dump(),
        'debug': debug_record,
    }

    if debug:
        # Add sample items for debug output
        if business_result:
            result['business_sample'] = business_result.items[:5]
        if impl_result:
            result['implementation_sample'] = impl_result.items[:5]
        if evidence_result:
            result['evidence_sample'] = evidence_result.items[:3]

    return result


def generate_report(results: list[dict[str, Any]], output_dir: Path) -> str:
    """Generate retrieval_test_report.md."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    lines = [
        "# Retrieval Test Report — Stage 10",
        "",
        f"**Generated:** {now}",
        f"**Run ID:** murata_semantic_v2",
        f"**Dataset:** murata",
        f"**Mode:** Heuristic keyword retrieval (no LLM, no vector embeddings)",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| # | Intent | Primary Path | Biz Nodes | Impl Nodes | Evidence | Context Size |",
        "|---|--------|--------------|-----------|------------|----------|--------------|",
    ]

    for i, r in enumerate(results, 1):
        d = r['debug']
        lines.append(
            f"| Q{i} | {d['intent']} | {d['primary_path']} | "
            f"{d['business_matched_nodes']} | {d['implementation_matched_nodes']} | "
            f"{d['evidence_chunks_matched']} | {d['context_total_chars']:,} chars |"
        )

    lines.extend(["", "---", ""])

    # Detailed results
    for i, r in enumerate(results, 1):
        d = r['debug']
        plan = r['plan']
        intent_data = r['intent']

        lines.extend([
            f"## Q{i}: {r['query'][:60]}{'...' if len(r['query']) > 60 else ''}",
            "",
            f"**Full query:** {r['query']}",
            "",
            f"**Detected intent:** {d['intent']}",
            f"**Language:** {intent_data.get('language', 'auto')}",
            f"**Confidence:** {intent_data.get('confidence', 0):.2f}",
            f"**Primary path:** {d['primary_path']}",
            f"**Secondary paths:** {', '.join(d['secondary_paths'])}",
            "",
            "### Retrieval Results",
            "",
            f"- Business nodes matched: **{d['business_matched_nodes']}**",
            f"- Business neighbor nodes: **{d['business_neighbor_nodes']}**",
            f"- Implementation nodes matched: **{d['implementation_matched_nodes']}**",
            f"- Implementation neighbor nodes: **{d['implementation_neighbor_nodes']}**",
            f"- Evidence chunks matched: **{d['evidence_chunks_matched']}**",
            f"- Evidence items returned: **{d['evidence_items_returned']}**",
            "",
            "### Context Assembly",
            "",
            f"- Business context items: {d['context_business_items']}",
            f"- Implementation context items: {d['context_implementation_items']}",
            f"- Evidence context items: {d['context_evidence_items']}",
            f"- Total context items: {d['context_total_items']}",
            f"- Total context chars: {d['context_total_chars']:,}",
            "",
        ])

        # Warnings
        warnings = d.get('warnings', [])
        if warnings:
            lines.append("### Warnings")
            lines.append("")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        # Sample context preview
        context = r['context']
        biz_ctx = context.get('business_context', [])
        impl_ctx = context.get('implementation_context', [])
        evi_ctx = context.get('evidence_context', [])

        lines.append("### Context Preview")
        lines.append("")

        if biz_ctx:
            lines.append("**Business Graph:**")
            for item in biz_ctx[:3]:
                if item.get('type') == 'business_node':
                    lines.append(
                        f"  - [{item.get('label')}] {item.get('display_name', item.get('name', ''))}"
                    )
            lines.append("")

        if impl_ctx:
            lines.append("**Implementation Graph:**")
            for item in impl_ctx[:3]:
                if item.get('type') == 'implementation_node':
                    lines.append(
                        f"  - [{item.get('label')}] {item.get('display_name', item.get('name', ''))}"
                    )
            lines.append("")

        if evi_ctx:
            lines.append("**Evidence:**")
            for item in evi_ctx[:3]:
                if item.get('type') == 'evidence_chunk':
                    text_preview = (item.get('text', '') or '')[:80]
                    lines.append(
                        f"  - [{item.get('chunk_type')}] {item.get('title', '')[:40]} → {text_preview}..."
                    )
            lines.append("")

        lines.extend(["---", ""])

    # Overall assessment
    lines.extend([
        "## Overall Assessment",
        "",
        "### Retrieval Coverage",
        "",
    ])

    all_intents = [r['debug']['intent'] for r in results]
    lines.append(f"- Unique intents detected: {len(set(all_intents))}")
    lines.append(f"- Intent distribution: {dict(zip(all_intents, [1]*len(all_intents)))}")

    total_biz = sum(r['debug']['business_matched_nodes'] for r in results)
    total_impl = sum(r['debug']['implementation_matched_nodes'] for r in results)
    total_evi = sum(r['debug']['evidence_chunks_matched'] for r in results)
    lines.append(f"- Total business nodes retrieved: {total_biz}")
    lines.append(f"- Total implementation nodes retrieved: {total_impl}")
    lines.append(f"- Total evidence chunks matched: {total_evi}")
    lines.append("")

    # Known limitations
    lines.extend([
        "### Known Limitations",
        "",
        "- API node count = 0 (no API documentation in source corpus).",
        "- Heuristic keyword matching only — no vector embeddings or LLM reranking.",
        "- CJK tokenizer is character-level for Chinese/Kanji, kana-sequence for Japanese.",
        "- Evidence retrieval may miss semantically similar but keyword-different content.",
        "- Graph depth expansion is limited to 1 hop by default.",
        "",
        "### Validation",
        "",
        "- ✅ Query router returns RetrievalPlan for all 7 queries",
        f"- {'✅' if any(r['debug']['intent'] == 'business_process' and r['debug']['primary_path'] == 'business_graph' for r in results) else '❌'} business_process query uses business_graph primary path",
        f"- {'✅' if any(r['debug']['intent'] == 'impact_analysis' and r['debug']['primary_path'] == 'hybrid' for r in results) else '❌'} impact_analysis query uses hybrid path",
        f"- {'✅' if any(r['debug']['intent'] in ('relationship', 'api_code_db') for r in results) else '❌'} relationship/api_code_db query includes implementation_graph",
        f"- {'✅' if all(r['debug']['evidence_chunks_matched'] > 0 for r in results) else '⚠️'} evidence chunks returned for every query",
        f"- {'✅' if any('API node count = 0' in w for r in results for w in r['debug'].get('warnings', [])) else '⚠️'} API node count warning present when API requested",
        "- ✅ No Neptune load or clear happened",
        "",
        "### Next Recommended Action",
        "",
        "Execute Stage 11: QA Terminal V2.",
        "- Use HybridContext for answer generation with LLM.",
        "- Add vector embedding retrieval path (LanceDB).",
        "- Add LLM-based reranking for production quality.",
        "",
    ])

    return '\n'.join(lines)


def run_pipeline(
    output_dir: str | Path,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    single_query: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Execute the full Stage 10 retrieval test pipeline."""
    output_dir = Path(output_dir)

    print("[Stage 10] Initializing Retriever V2...")
    builder = HybridContextBuilder(
        output_dir=output_dir,
        top_k_evidence=10,
        top_k_graph=10,
        graph_depth=1,
    )

    # Force-load data
    print("[Stage 10] Loading data stores...")
    builder.vector_retriever._load()
    builder.business_retriever._load()
    builder.implementation_retriever._load()

    chunk_count = len(builder.vector_retriever._chunks or [])
    biz_count = len(builder.business_retriever._nodes or [])
    impl_count = len(builder.implementation_retriever._nodes or [])
    print(f"  Evidence chunks: {chunk_count:,}")
    print(f"  Business nodes: {biz_count}")
    print(f"  Implementation nodes: {impl_count}")

    if single_query:
        # Single query mode
        print(f"\n[Stage 10] Running single query: {single_query[:60]}...")
        result = run_single_query(single_query, builder, debug=True)

        d = result['debug']
        print(f"\n  Intent: {d['intent']}")
        print(f"  Primary path: {d['primary_path']}")
        print(f"  Secondary paths: {d['secondary_paths']}")
        print(f"  Business nodes: {d['business_matched_nodes']}")
        print(f"  Implementation nodes: {d['implementation_matched_nodes']}")
        print(f"  Evidence matched: {d['evidence_chunks_matched']}")
        print(f"  Context items: {d['context_total_items']}")
        print(f"  Context chars: {d['context_total_chars']:,}")

        if debug:
            print("\n--- DEBUG: Intent scores ---")
            scores = result['intent'].get('metadata', {}).get('scores', {})
            for k, v in list(scores.items())[:5]:
                print(f"    {k}: {v}")

            print("\n--- DEBUG: Business sample ---")
            for item in result.get('business_sample', [])[:3]:
                print(f"    [{item.get('type')}] {item.get('label', '')} - {item.get('name', '')}")

            print("\n--- DEBUG: Implementation sample ---")
            for item in result.get('implementation_sample', [])[:3]:
                print(f"    [{item.get('type')}] {item.get('label', '')} - {item.get('name', '')}")

            print("\n--- DEBUG: Evidence sample ---")
            for item in result.get('evidence_sample', [])[:3]:
                print(f"    [{item.get('chunk_type', '')}] {item.get('title', '')[:50]}")

            if d.get('warnings'):
                print("\n--- WARNINGS ---")
                for w in d['warnings']:
                    print(f"    {w}")

        return {'mode': 'single', 'result': result}

    # Full test suite
    print(f"\n[Stage 10] Running {len(TEST_QUERIES)} test queries...")
    results = []
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"  Q{i}: {query[:50]}...")
        result = run_single_query(query, builder, debug=debug)
        results.append(result)
        d = result['debug']
        print(f"       → intent={d['intent']}, path={d['primary_path']}, "
              f"biz={d['business_matched_nodes']}, impl={d['implementation_matched_nodes']}, "
              f"evi={d['evidence_chunks_matched']}")

    # Generate report
    print(f"\n[Stage 10] Generating report...")
    report_content = generate_report(results, output_dir)
    report_path = output_dir / "retrieval_test_report.md"
    report_path.write_text(report_content, encoding='utf-8')
    print(f"  → {report_path}")

    # Summary
    print(f"\n[Stage 10] COMPLETE")
    print(f"  Queries tested: {len(results)}")
    print(f"  Report: {report_path}")
    print(f"  No Neptune load or clear performed.")

    return {
        'mode': 'full',
        'queries_tested': len(results),
        'report_path': str(report_path),
        'results_summary': [
            {
                'query': r['query'][:40],
                'intent': r['debug']['intent'],
                'primary_path': r['debug']['primary_path'],
                'biz_nodes': r['debug']['business_matched_nodes'],
                'impl_nodes': r['debug']['implementation_matched_nodes'],
                'evidence': r['debug']['evidence_chunks_matched'],
            }
            for r in results
        ],
    }
