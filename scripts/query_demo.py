#!/usr/bin/env python3
"""Query demo — interactive hybrid retrieval from LanceDB + Neptune.

Usage:
    python scripts/query_demo.py "仕訳基礎テーブルの構造は？"
    python scripts/query_demo.py --run-id murata_full_vlm_live_001 "付款申請の承認フロー"
    python scripts/query_demo.py --no-neptune "PaymentReqActionの機能"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger("query_demo")

DEFAULT_RUN_ID = "murata_full_vlm_live_001"
DEFAULT_LANCEDB_PATH = Path.home() / "projects/data/vector_store/lancedb"
DEFAULT_NEPTUNE_ENDPOINT = "g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com"


def main():
    parser = argparse.ArgumentParser(description="Query demo — hybrid GraphRAG retrieval")
    parser.add_argument("query", help="Natural language question")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID for LanceDB collection")
    parser.add_argument("--lancedb-path", type=Path, default=DEFAULT_LANCEDB_PATH)
    parser.add_argument("--no-neptune", action="store_true", help="Skip Neptune graph retrieval")
    parser.add_argument("--no-answer", action="store_true", help="Skip answer generation")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    parser.add_argument("--neptune-endpoint", default=DEFAULT_NEPTUNE_ENDPOINT)
    args = parser.parse_args()

    os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")

    print(f"\n{'='*60}")
    print(f"  QUERY: {args.query}")
    print(f"  Collection: murata_e2e_{args.run_id}")
    print(f"{'='*60}\n")

    # 1. Embed query
    from hermes_bedrock_agent.embedding.embedder import BedrockEmbedder, EmbedderConfig
    embedder = BedrockEmbedder(config=EmbedderConfig(
        model_id="amazon.titan-embed-text-v2:0",
        dimension=1024,
    ))

    print("[1/5] Embedding query...")
    query_embedding = embedder.embed_text(args.query)
    print(f"  → Vector dimension: {len(query_embedding)}")

    # 2. Text retrieval via LanceDB
    from hermes_bedrock_agent.vector_store import create_vector_store
    from hermes_bedrock_agent.retrieval.text_retriever import VectorStoreTextRetriever, TextRetrieverConfig

    collection_name = f"murata_e2e_{args.run_id}"
    store = create_vector_store(
        backend="lancedb",
        db_path=str(args.lancedb_path),
        collection=collection_name,
    )

    retriever = VectorStoreTextRetriever(store, config=TextRetrieverConfig(top_k=args.top_k))

    print("[2/5] Searching LanceDB (hybrid)...")
    text_evidence = retriever.hybrid_search(args.query, query_embedding=query_embedding)
    print(f"  → {len(text_evidence)} text evidence results")

    for i, ev in enumerate(text_evidence[:5]):
        print(f"  [{i+1}] score={ev.score:.3f} | {ev.source_uri or 'unknown'}")
        print(f"      {ev.content[:80]}...")
        print()

    # 3. Graph retrieval
    graph_evidence = []
    if not args.no_neptune:
        print("[3/5] Searching Neptune graph...")
        try:
            from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
            from hermes_bedrock_agent.retrieval.graph_retriever import NeptuneGraphRetriever

            graph_id = args.neptune_endpoint.split(".")[0]
            neptune = NeptuneClient(graph_id=graph_id, region="ap-northeast-1")
            graph_retriever = NeptuneGraphRetriever(neptune)

            terms = [t for t in args.query.split() if len(t) > 2][:5]
            graph_evidence = graph_retriever.retrieve_graph_context(terms)
            print(f"  → {len(graph_evidence)} graph evidence results")
        except Exception as e:
            print(f"  → Neptune unavailable: {e}")
    else:
        print("[3/5] Neptune skipped (--no-neptune)")

    # 4. Fuse
    print("[4/5] Fusing evidence...")
    from hermes_bedrock_agent.retrieval.fusion import fuse_evidence, FusionConfig
    fused = fuse_evidence(text_evidence, graph_evidence, query=args.query)
    print(f"  → Fused context: {fused.total_evidence_count} total evidence")

    # 5. Generate answer
    if not args.no_answer:
        print("[5/5] Generating answer...")
        import boto3
        from hermes_bedrock_agent.generation.answer_generator import AnswerGenerator, AnswerGeneratorConfig

        bedrock_runtime = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
        gen = AnswerGenerator(
            bedrock_client=bedrock_runtime,
            config=AnswerGeneratorConfig(model_id="anthropic.claude-sonnet-4-20250514-v1:0"),
        )

        answer = gen.generate_answer(args.query, fused)
        print(f"\n{'─'*60}")
        print(f"  ANSWER:")
        print(f"{'─'*60}")
        print(f"\n{answer.answer}\n")

        if answer.citations:
            print(f"  Citations ({len(answer.citations)}):")
            for c in answer.citations[:5]:
                print(f"    - {c.source_uri} ({c.section_title or c.chunk_id})")
    else:
        print("[5/5] Answer generation skipped (--no-answer)")

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
