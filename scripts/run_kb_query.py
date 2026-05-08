#!/usr/bin/env python
"""Script to query Bedrock Knowledge Bases.

Usage:
    python scripts/run_kb_query.py "your query here"
    python scripts/run_kb_query.py "payment process" --top-k 10
"""
import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from hermes_bedrock_agent.kb.kb_query import query_all_kbs


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Bedrock Knowledge Bases")
    parser.add_argument("query", type=str, help="Query text")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    parser.add_argument("--strategy", type=str, default="score", choices=["score", "round_robin", "kb_order"])
    args = parser.parse_args()

    results = query_all_kbs(args.query, top_k=args.top_k, merge_strategy=args.strategy)

    print(f"\nFound {len(results)} results for: {args.query!r}\n")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] (score={r.score:.3f}, kb={r.display_source})")
        print(f"      {r.text[:150]}...")
        print()


if __name__ == "__main__":
    main()
