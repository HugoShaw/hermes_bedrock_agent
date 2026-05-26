#!/usr/bin/env python3
"""Demo script: Verify the QA evidence flow end-to-end.

This script runs a single query through the full evidence pipeline and prints
detailed information about each evidence source used, so you can manually verify:
  1. Which Markdown chunks were retrieved
  2. Which PDF/PNG pages were resolved from chunk metadata
  3. Which Business Semantic Graph context was fetched
  4. Which Implementation Graph context was fetched
  5. What the final grounded answer looks like

Usage:
  uv run python scripts/demo_qa_evidence_flow.py
  uv run python scripts/demo_qa_evidence_flow.py "SAP発注データのフロー"
  uv run python scripts/demo_qa_evidence_flow.py --top-k 3 --no-images
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("demo")

# Suppress boto noise
for n in ("boto3", "botocore", "urllib3"):
    logging.getLogger(n).setLevel(logging.WARNING)


def _divider(title: str) -> str:
    return f"\n{'─' * 10} {title} {'─' * (60 - len(title))}"


def main():
    parser = argparse.ArgumentParser(description="Demo: QA evidence flow verification")
    parser.add_argument("query", nargs="?", default="SAP から ANDPAD への発注データのフローを説明してください",
                        help="Query to test")
    parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to retrieve")
    parser.add_argument("--no-images", action="store_true", help="Skip PDF/PNG evidence loading")
    parser.add_argument("--no-graph", action="store_true", help="Skip graph context retrieval")
    parser.add_argument("--no-answer", action="store_true", help="Skip VLM answer generation (retrieval only)")
    parser.add_argument("--verbose", action="store_true", help="Show full chunk content")
    args = parser.parse_args()

    from hermes_bedrock_agent.config import config
    from hermes_bedrock_agent.retrieval.vector_retriever import retrieve_chunks
    from hermes_bedrock_agent.retrieval.graph_retriever import fetch_dual_graph_context
    from hermes_bedrock_agent.retrieval.answer_generator import load_evidence_images, generate_answer

    print(_divider("QA Evidence Flow Demo"))
    print(f"  Query: {args.query}")
    print(f"  Top-K: {args.top_k}")
    print(f"  LanceDB: {config.lancedb_path} / {config.vector_collection}")
    print(f"  Neptune: {config.neptune_graph_id or '(not configured)'}")
    print(f"  VLM Model: {config.vlm_model_id}")

    # ────────────────────────────────────────────────────────────────────
    # Step 1: Markdown chunk retrieval
    # ────────────────────────────────────────────────────────────────────
    print(_divider("① Markdown Chunk Retrieval"))
    t0 = time.time()
    chunks = retrieve_chunks(args.query, top_k=args.top_k)
    t1 = time.time()
    print(f"  Retrieved {len(chunks)} chunks in {t1-t0:.2f}s\n")

    for i, chunk in enumerate(chunks, 1):
        print(f"  [{i}] sheet={chunk.sheet_index} name={chunk.sheet_name} type={chunk.chunk_type} score={chunk.score:.4f}")
        print(f"      PDF evidence: {chunk.source_pdf_s3_path}")
        if args.verbose:
            preview = chunk.content[:200].replace("\n", " ")
            print(f"      Content: {preview}...")
        print()

    # ────────────────────────────────────────────────────────────────────
    # Step 2: Dual-layer graph context
    # ────────────────────────────────────────────────────────────────────
    dual_graph = None
    if not args.no_graph:
        print(_divider("②③ Dual Graph Context Retrieval"))
        t2 = time.time()
        dual_graph = fetch_dual_graph_context(chunks, query=args.query)
        t3 = time.time()

        if dual_graph and not dual_graph.is_empty:
            print(f"  Fetched in {t3-t2:.2f}s")
            print(f"\n  ② Business Semantic Graph:")
            print(f"     Nodes: {len(dual_graph.business.nodes)}")
            for n in dual_graph.business.nodes[:8]:
                props = n.get("properties", {})
                name = props.get("name", props.get("display_name", n.get("id", "")))
                print(f"       [{n.get('label', '')}] {name}")
            print(f"     Edges: {len(dual_graph.business.edges)}")
            for e in dual_graph.business.edges[:5]:
                print(f"       {e.get('from', '?')} --{e.get('relationship', '?')}--> {e.get('to', '?')}")

            print(f"\n  ③ Implementation Graph:")
            print(f"     Nodes: {len(dual_graph.implementation.nodes)}")
            for n in dual_graph.implementation.nodes[:8]:
                props = n.get("properties", {})
                name = props.get("name", props.get("display_name", n.get("id", "")))
                print(f"       [{n.get('label', '')}] {name}")
            print(f"     Edges: {len(dual_graph.implementation.edges)}")
            for e in dual_graph.implementation.edges[:5]:
                print(f"       {e.get('from', '?')} --{e.get('relationship', '?')}--> {e.get('to', '?')}")
        else:
            print(f"  No graph context available (Neptune not configured or no results)")
            t3 = t2
        print()
    else:
        print(_divider("②③ Graph Context (SKIPPED)"))
        t3 = t1

    # ────────────────────────────────────────────────────────────────────
    # Step 3: PDF/PNG evidence resolution
    # ────────────────────────────────────────────────────────────────────
    evidence_images: list = []
    if not args.no_images:
        print(_divider("④ PDF/PNG Evidence Resolution"))
        t4 = time.time()
        evidence_images = load_evidence_images(chunks, config.project_root)
        t5 = time.time()
        print(f"  Resolved {len(evidence_images)} evidence image(s) in {t5-t4:.2f}s\n")
        for label, img_bytes, path in evidence_images:
            size_kb = len(img_bytes) / 1024
            print(f"  ✓ {label}")
            print(f"    Path: {path}")
            print(f"    Size: {size_kb:.1f} KB")
        if not evidence_images:
            print("  (No PDF/PNG files found on local filesystem)")
        print()
    else:
        print(_divider("④ Evidence Images (SKIPPED)"))
        t5 = t3

    # ────────────────────────────────────────────────────────────────────
    # Step 4: VLM answer generation
    # ────────────────────────────────────────────────────────────────────
    if not args.no_answer:
        print(_divider("⑤ Multimodal VLM Answer Generation"))
        print("  Sending evidence pack to VLM:")
        print(f"    - {len(chunks)} Markdown chunks")
        if dual_graph and not dual_graph.is_empty:
            print(f"    - Business Graph: {len(dual_graph.business.nodes)} nodes, {len(dual_graph.business.edges)} edges")
            print(f"    - Implementation Graph: {len(dual_graph.implementation.nodes)} nodes, {len(dual_graph.implementation.edges)} edges")
        print(f"    - {len(evidence_images)} PDF/PNG evidence image(s)")
        print()

        t6 = time.time()
        ans = generate_answer(
            query=args.query,
            retrieved_chunks=chunks,
            evidence_images=evidence_images,
            graph_context=dual_graph.to_merged_context() if dual_graph else None,
            business_graph=dual_graph.business if dual_graph else None,
            implementation_graph=dual_graph.implementation if dual_graph else None,
        )
        t7 = time.time()

        print(f"  Answer generated in {t7-t6:.1f}s")
        print(f"  Tokens: {ans.input_tokens:,} in / {ans.output_tokens:,} out")
        print(f"  Model: {ans.model_id}")
        print(f"\n{'─' * 72}")
        print(f"\n{ans.answer}\n")
        print(f"{'─' * 72}")
    else:
        print(_divider("⑤ Answer Generation (SKIPPED)"))

    # ────────────────────────────────────────────────────────────────────
    # Summary
    # ────────────────────────────────────────────────────────────────────
    total = time.time() - t0
    print(_divider("Evidence Flow Summary"))
    print(f"  ① Markdown chunks: {len(chunks)} (sheets: {sorted({c.sheet_index for c in chunks})})")
    if dual_graph and not dual_graph.is_empty:
        print(f"  ② Business Graph: {len(dual_graph.business.nodes)} nodes, {len(dual_graph.business.edges)} edges")
        print(f"  ③ Implementation Graph: {len(dual_graph.implementation.nodes)} nodes, {len(dual_graph.implementation.edges)} edges")
    else:
        print(f"  ②③ Graph context: (not available)")
    print(f"  ④ Visual evidence: {len(evidence_images)} PDF/PNG pages")
    print(f"  Total time: {total:.1f}s")
    print()


if __name__ == "__main__":
    main()
