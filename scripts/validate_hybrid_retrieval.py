"""Validation script for hybrid retrieval pipeline.

Tests keyword retrieval against actual LanceDB data (read-only).
Vector search is skipped (requires Bedrock API for embedding).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_bedrock_agent.retrieval.query_preprocessing import (
    detect_intent,
    normalize_query,
    rewrite_queries,
)
from hermes_bedrock_agent.retrieval.keyword_retriever import keyword_search
from hermes_bedrock_agent.retrieval.trace import HybridTrace
from hermes_bedrock_agent.config import Config


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def validate_preprocessing() -> None:
    _section("Query Preprocessing")

    queries = [
        "マッピングテーブルの変換ルール",
        "API endpoint の呼出仕様",
        "フローチャートの処理順序",
        "仕訳基礎の概要",
        "ビジネスルールの条件分岐ロジック",
    ]

    for q in queries:
        normalized = normalize_query(q)
        intent = detect_intent(normalized)
        rewritten = rewrite_queries(normalized, intent)

        print(f"\n  Query: {q}")
        print(f"  Normalized: {normalized}")
        print(f"  Intent: {intent.label} (confidence={intent.confidence:.2f})")
        print(f"  Chunk hints: {intent.chunk_type_hints}")
        print(f"  Business:  {rewritten.business_query[:70]}")
        print(f"  Technical: {rewritten.technical_query[:70]}")
        print(f"  Keywords:  {rewritten.keyword_query[:70]}")


def validate_keyword_search() -> None:
    _section("Keyword Search (LanceDB read-only)")

    cfg = Config()
    db_path = cfg.lancedb_path
    collection = "murata_e2e_murata_full_vlm_live_001"

    print(f"\n  DB path: {db_path}")
    print(f"  Collection: {collection}")

    # Check if LanceDB data exists
    lance_path = Path(db_path)
    if not lance_path.exists():
        print(f"\n  WARNING: LanceDB path not found: {db_path}")
        print("  Skipping keyword search validation.")
        return

    test_queries = [
        ("仕訳基礎", "saimu_bugyo_cloud"),
        ("対帳単", "saimu_bugyo_cloud"),
        ("マッピング", ""),
        ("API", ""),
    ]

    for query, project_id in test_queries:
        print(f"\n  Query: '{query}' (project={project_id or 'ALL'})")
        try:
            results = keyword_search(
                query=query,
                top_k=3,
                project_id=project_id,
                cfg=cfg,
                collection=collection,
            )
            print(f"  Results: {len(results)}")
            for i, r in enumerate(results[:3]):
                chunk_id = r.get("id", "?")
                score = r.get("_keyword_score", 0.0)
                chunk_type = r.get("chunk_type", "?")
                text_preview = str(r.get("text", ""))[:60].replace("\n", " ")
                print(f"    [{i+1}] id={chunk_id} score={score:.2f} type={chunk_type}")
                print(f"        {text_preview}...")
        except Exception as e:
            print(f"  ERROR: {e}")


def validate_trace() -> None:
    _section("HybridTrace Integration")

    trace = HybridTrace()
    trace.normalized_query = "テスト"
    trace.intent_label = "overview"
    trace.intent_confidence = 0.5
    trace.vector_hits_count = 5
    trace.keyword_hits_count = 3
    trace.merged_count = 7
    trace.dedup_removed = 1

    print(f"  Trace populated successfully:")
    print(f"    normalized_query: {trace.normalized_query}")
    print(f"    intent: {trace.intent_label} ({trace.intent_confidence})")
    print(f"    vector_hits: {trace.vector_hits_count}")
    print(f"    keyword_hits: {trace.keyword_hits_count}")
    print(f"    merged: {trace.merged_count}")
    print(f"    dedup_removed: {trace.dedup_removed}")


def main() -> None:
    print("Hybrid Retrieval Pipeline — Validation")
    print("=" * 60)

    validate_preprocessing()
    validate_keyword_search()
    validate_trace()

    _section("DONE")
    print("  All validations complete.\n")


if __name__ == "__main__":
    main()
