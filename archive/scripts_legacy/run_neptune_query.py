#!/usr/bin/env python
"""Script to run openCypher queries against Neptune Analytics.

Usage:
    python scripts/run_neptune_query.py "MATCH (n) RETURN n LIMIT 10"
    python scripts/run_neptune_query.py --file graph/query_examples.cypher
"""
import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from hermes_bedrock_agent.graph.neptune_client import NeptuneClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Neptune Analytics openCypher queries")
    parser.add_argument("query", nargs="?", type=str, help="Cypher query string")
    parser.add_argument("--file", type=str, help="Path to .cypher file (runs first non-comment query)")
    args = parser.parse_args()

    if not args.query and not args.file:
        parser.error("Provide a query string or --file")

    query = args.query
    if args.file:
        with open(args.file) as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("--")]
            query = " ".join(lines)

    client = NeptuneClient()
    print(f"Executing: {query[:200]}...")
    result = client.execute_query(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
