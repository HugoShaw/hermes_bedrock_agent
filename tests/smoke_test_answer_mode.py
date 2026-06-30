"""Answer-mode smoke test: exercises full pipeline including LLM answer generation.

Tests the complete flow:
  User Question → Normalization → Intent → Rewrite → Vector + Keyword →
  Merge/Dedup → Graph Expansion → Rerank → Evidence Loading → LLM Answer

Does NOT modify any data. Read-only operations only.
Uses live Bedrock API for answer generation.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault("LANCEDB_PATH", "/home/ubuntu/projects/data/vector_store/lancedb")
os.environ.setdefault("VECTOR_COLLECTION", "murata_e2e_murata_full_vlm_live_001")


def run_answer_mode_test(project_id: str, query: str, label: str):
    """Run a single answer-mode query and report results."""
    from hermes_bedrock_agent.retrieval.graph_guided_retrieval import retrieve_with_graph_guidance
    from hermes_bedrock_agent.retrieval.answer_generator import load_evidence_images, generate_answer
    from hermes_bedrock_agent.retrieval.trace import RetrievalTrace
    from hermes_bedrock_agent.config import config

    print(f"\n{'='*80}")
    print(f"  PROJECT: {project_id}")
    print(f"  QUERY:   {query}")
    print(f"  LABEL:   {label}")
    print(f"{'='*80}")

    trace = RetrievalTrace(enabled=True)

    # Step 1: Graph-guided retrieval
    t0 = time.time()
    try:
        chunks, dual_graph, guidance_status = retrieve_with_graph_guidance(
            query=query, top_k=5, project_id=project_id,
            trace=trace,
        )
    except Exception as e:
        print(f"  ✗ RETRIEVAL FAILED: {e}")
        return {"status": "error", "error": str(e)}
    t1 = time.time()

    print(f"\n  [Retrieval] {t1-t0:.2f}s")
    print(f"    Chunks returned: {len(chunks)}")
    print(f"    Guidance status: {guidance_status}")
    print(f"    Dual graph: {'present' if dual_graph and not dual_graph.is_empty else 'empty/None'}")

    # Graph expansion trace
    ge = trace.graph_expansion
    print(f"\n  [Graph Expansion Trace]")
    print(f"    Enabled: {ge.enabled}")
    if ge.enabled:
        print(f"    Entities extracted: {ge.entities_extracted}")
        print(f"    Graph nodes matched: {ge.graph_nodes_matched}")
        print(f"    Candidates resolved: {ge.graph_candidates_resolved}")
        print(f"    New (non-duplicate): {ge.graph_candidates_new}")
        print(f"    Duplicates: {ge.graph_candidates_duplicate}")
        print(f"    Survived rerank: {ge.graph_candidates_survived_rerank}")
        print(f"    Candidates detail count: {len(ge.candidates)}")

    # Evidence metadata check
    print(f"\n  [Evidence Metadata]")
    for i, c in enumerate(chunks[:3]):
        has_evidence_path = bool(c.evidence_path)
        has_parsed_md = bool(c.parsed_markdown_path)
        has_source_md = bool(c.source_markdown_file)
        has_pdf_s3 = bool(c.source_pdf_s3_path)
        print(f"    Chunk {i}: ev_path={has_evidence_path} parsed_md={has_parsed_md} "
              f"source_md={has_source_md} pdf_s3={has_pdf_s3}")

    # Step 2: Evidence loading
    t2 = time.time()
    try:
        evidence_images = load_evidence_images(chunks, config.project_root)
    except Exception as e:
        print(f"  ✗ EVIDENCE LOADING FAILED: {e}")
        evidence_images = []
    t2_end = time.time()

    print(f"\n  [Evidence Loading] {t2_end-t2:.2f}s")
    print(f"    Images loaded: {len(evidence_images)}")
    for label_img, png_bytes, path_str in evidence_images:
        print(f"      {label_img}: {len(png_bytes):,} bytes")

    # Step 3: LLM answer generation
    print(f"\n  [Answer Generation]")
    t3 = time.time()
    try:
        answer = generate_answer(
            query=query,
            retrieved_chunks=chunks,
            evidence_images=evidence_images,
            graph_context=dual_graph.to_merged_context() if dual_graph else None,
            business_graph=dual_graph.business if dual_graph else None,
            implementation_graph=dual_graph.implementation if dual_graph else None,
        )
    except Exception as e:
        print(f"  ✗ ANSWER GENERATION FAILED: {e}")
        return {
            "status": "partial",
            "retrieval_ok": True,
            "evidence_ok": len(evidence_images) > 0,
            "answer_error": str(e),
        }
    t3_end = time.time()

    print(f"    Duration: {t3_end-t3:.2f}s")
    print(f"    Input tokens: {answer.input_tokens}")
    print(f"    Output tokens: {answer.output_tokens}")
    print(f"    Answer length: {len(answer.answer)} chars")
    print(f"    Answer preview: {answer.answer[:200]}...")

    # Determine if graph-added candidates contributed to final answer
    graph_contributed = (ge.enabled and ge.graph_candidates_survived_rerank
                        and ge.graph_candidates_survived_rerank > 0)

    result = {
        "status": "success",
        "project_id": project_id,
        "query": query,
        "retrieval_time_s": round(t1 - t0, 2),
        "evidence_images_count": len(evidence_images),
        "answer_time_s": round(t3_end - t3, 2),
        "answer_tokens": answer.output_tokens,
        "guidance_status": guidance_status,
        "graph_expansion_enabled": ge.enabled,
        "graph_candidates_new": ge.graph_candidates_new,
        "graph_survived_rerank": ge.graph_candidates_survived_rerank,
        "graph_contributed_to_answer": graph_contributed,
    }

    # Validation checks
    checks = []
    checks.append(("Retrieval returned chunks", len(chunks) > 0))
    checks.append(("Evidence metadata populated", any(c.evidence_path for c in chunks)))
    checks.append(("Evidence images loaded", len(evidence_images) > 0))
    checks.append(("Answer generated", len(answer.answer) > 50))
    checks.append(("GraphExpansionTrace populated", ge.enabled))
    checks.append(("No empty parsed_markdown_path after fallback",
                   all(c.parsed_markdown_path for c in chunks if c.source_markdown_file)))

    print(f"\n  [Validation]")
    all_pass = True
    for check_name, check_result in checks:
        status = "✓" if check_result else "✗"
        print(f"    {status} {check_name}")
        if not check_result:
            all_pass = False

    result["all_checks_pass"] = all_pass
    return result


def main():
    print("=" * 80)
    print("  ANSWER-MODE SMOKE TEST")
    print("  Tests full pipeline: retrieval → evidence → LLM answer generation")
    print("=" * 80)

    test_cases = [
        # sample_20260519 queries
        ("sample_20260519", "Sheet_03のマッピング仕様の項目一覧を教えてください", "sample: mapping spec"),
        ("sample_20260519", "APIパラメータのデータ型定義はどこに記載されていますか", "sample: API data types"),
        # saimu_bugyo_cloud queries
        ("saimu_bugyo_cloud", "仕訳データ連携のAPI認証方式を説明してください", "saimu: API auth"),
        ("saimu_bugyo_cloud", "債務奉行クラウドのアプリケーション概要を教えてください", "saimu: app overview"),
    ]

    results = []
    for project_id, query, label in test_cases:
        result = run_answer_mode_test(project_id, query, label)
        results.append(result)

    # Summary
    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    total = len(results)
    success = sum(1 for r in results if r.get("status") == "success")
    partial = sum(1 for r in results if r.get("status") == "partial")
    errors = sum(1 for r in results if r.get("status") == "error")
    all_pass = sum(1 for r in results if r.get("all_checks_pass"))

    print(f"  Total: {total} | Success: {success} | Partial: {partial} | Errors: {errors}")
    print(f"  All checks passed: {all_pass}/{total}")

    graph_contributed = sum(1 for r in results if r.get("graph_contributed_to_answer"))
    print(f"  Graph candidates survived rerank: {graph_contributed}/{total}")

    for r in results:
        if r.get("status") == "success":
            print(f"    {r['project_id']}: guidance={r['guidance_status']} "
                  f"graph_new={r['graph_candidates_new']} "
                  f"survived={r['graph_survived_rerank']} "
                  f"evidence={r['evidence_images_count']} "
                  f"answer={r['answer_tokens']}tok")

    # Write JSON results
    out_path = Path(__file__).parent / "smoke_test_answer_mode_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results written to: {out_path}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
