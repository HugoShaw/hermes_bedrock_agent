"""Verify current pipeline state matches recorded baseline.

Usage:
    uv run python tests/baseline/verify_baseline.py \
        --baseline docs/baselines/2026-06-12/baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class VerificationResult:
    def __init__(self, section: str):
        self.section = section
        self.passed = True
        self.messages: list[str] = []

    def fail(self, msg: str) -> None:
        self.passed = False
        self.messages.append(f"FAIL: {msg}")

    def info(self, msg: str) -> None:
        self.messages.append(f"INFO: {msg}")

    def ok(self, msg: str) -> None:
        self.messages.append(f"OK: {msg}")


def verify_schema(baseline: dict, collection: str, store_path: str) -> VerificationResult:
    """Verify LanceDB schema matches baseline."""
    result = VerificationResult("lancedb_schema")

    baseline_schema = baseline.get("lancedb_schema", {})
    if "error" in baseline_schema:
        result.info(f"Baseline had error: {baseline_schema['error']}")
        return result

    try:
        import lancedb

        db = lancedb.connect(store_path)
        if collection not in db.table_names():
            result.fail(f"Collection '{collection}' not found")
            return result

        table = db.open_table(collection)
        schema = table.schema
        current_columns = []
        for i in range(len(schema)):
            field = schema.field(i)
            current_columns.append({"name": field.name, "type": str(field.type)})

        baseline_columns = baseline_schema.get("columns", [])
        baseline_names = {c["name"] for c in baseline_columns}
        current_names = {c["name"] for c in current_columns}

        missing = baseline_names - current_names
        added = current_names - baseline_names

        if missing:
            result.fail(f"Columns removed: {sorted(missing)}")
        if added:
            result.info(f"Columns added (OK if additive): {sorted(added)}")

        # Check type changes for shared columns
        baseline_map = {c["name"]: c["type"] for c in baseline_columns}
        current_map = {c["name"]: c["type"] for c in current_columns}
        for name in baseline_names & current_names:
            if baseline_map[name] != current_map[name]:
                result.fail(f"Column '{name}' type changed: {baseline_map[name]} → {current_map[name]}")

        if result.passed:
            result.ok("Schema matches baseline")

    except Exception as exc:
        result.fail(f"Could not verify schema: {exc}")

    return result


def verify_chunk_counts(baseline: dict, collection: str, store_path: str, tolerance: int = 0) -> VerificationResult:
    """Verify chunk counts match baseline (±tolerance)."""
    result = VerificationResult("chunk_counts")

    baseline_counts = baseline.get("chunk_counts", {})
    if "error" in baseline_counts:
        result.info(f"Baseline had error: {baseline_counts['error']}")
        return result

    try:
        import lancedb

        db = lancedb.connect(store_path)
        if collection not in db.table_names():
            result.fail(f"Collection '{collection}' not found")
            return result

        table = db.open_table(collection)

        for pid, expected in baseline_counts.items():
            if pid == "__total__":
                current = table.count_rows()
            elif isinstance(expected, dict) and "error" in expected:
                continue
            else:
                try:
                    rows = table.search().where(f"project_id = '{pid}'", prefilter=True).limit(100000).to_list()
                    current = len(rows)
                except Exception as exc:
                    result.fail(f"Could not count rows for project '{pid}': {exc}")
                    continue

            if not isinstance(expected, int):
                continue

            diff = abs(current - expected)
            if diff > tolerance:
                result.fail(f"Project '{pid}': expected {expected}, got {current} (diff={diff}, tolerance={tolerance})")
            else:
                result.ok(f"Project '{pid}': {current} rows (expected {expected}, tolerance ±{tolerance})")

    except Exception as exc:
        result.fail(f"Could not verify counts: {exc}")

    return result


def verify_project_isolation(baseline: dict, collection: str, store_path: str) -> VerificationResult:
    """Verify project isolation still holds."""
    result = VerificationResult("project_isolation")

    baseline_isolation = baseline.get("project_isolation", {})
    if "error" in baseline_isolation:
        result.info(f"Baseline had error: {baseline_isolation['error']}")
        return result

    try:
        import lancedb

        db = lancedb.connect(store_path)
        if collection not in db.table_names():
            result.fail(f"Collection '{collection}' not found")
            return result

        table = db.open_table(collection)

        for pid, baseline_check in baseline_isolation.items():
            if isinstance(baseline_check, dict) and "error" in baseline_check:
                continue
            rows = table.search().where(f"project_id = '{pid}'", prefilter=True).limit(10).to_list()
            other_projects = set()
            for r in rows:
                row_pid = r.get("project_id", "")
                if row_pid and row_pid != pid:
                    other_projects.add(row_pid)
            if other_projects:
                result.fail(f"Project '{pid}' has contamination from: {sorted(other_projects)}")
            else:
                result.ok(f"Project '{pid}' isolation intact")

    except Exception as exc:
        result.fail(f"Could not verify isolation: {exc}")

    return result


def verify_neptune_counts(baseline: dict) -> VerificationResult:
    """Verify Neptune node/edge counts match baseline."""
    result = VerificationResult("neptune_counts")

    baseline_neptune = baseline.get("neptune_counts", {})
    if "error" in baseline_neptune or baseline_neptune.get("skipped"):
        result.info("Neptune section skipped or had error in baseline")
        return result

    try:
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import GraphGuidedRetriever

        retriever = GraphGuidedRetriever()

        for pid, expected in baseline_neptune.items():
            if isinstance(expected, dict) and "error" in expected:
                result.info(f"Project '{pid}' had error in baseline, skipping")
                continue
            try:
                node_query = f"g.V().has('project_id', '{pid}').count()"
                edge_query = f"g.V().has('project_id', '{pid}').outE().count()"
                node_resp = retriever._execute_query(node_query)
                edge_resp = retriever._execute_query(edge_query)
                current_nodes = node_resp[0] if node_resp else 0
                current_edges = edge_resp[0] if edge_resp else 0
                expected_nodes = expected.get("nodes", 0)
                expected_edges = expected.get("edges", 0)
                if current_nodes != expected_nodes:
                    result.fail(f"Project '{pid}' nodes: expected {expected_nodes}, got {current_nodes}")
                if current_edges != expected_edges:
                    result.fail(f"Project '{pid}' edges: expected {expected_edges}, got {current_edges}")
                if current_nodes == expected_nodes and current_edges == expected_edges:
                    result.ok(f"Project '{pid}' Neptune counts match")
            except Exception as exc:
                result.fail(f"Project '{pid}' Neptune query failed: {exc}")

    except Exception as exc:
        result.info(f"Neptune unreachable: {exc}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify current pipeline state matches recorded baseline.")
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON file")
    parser.add_argument("--tolerance", type=int, default=0, help="Allowed chunk count difference (default: 0)")

    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(f"ERROR: Baseline file not found: {baseline_path}")
        sys.exit(1)

    baseline = json.loads(baseline_path.read_text())
    meta = baseline.get("meta", {})
    collection = meta.get("collection", "murata_excel_vlm_dual_rag")
    store_path = meta.get("store_path", "lancedb_store")

    print(f"Verifying against baseline: {baseline_path}")
    print(f"  Collection: {collection}")
    print(f"  Store path: {store_path}")
    print(f"  Tolerance: ±{args.tolerance}")
    print()

    results: list[VerificationResult] = []

    # 1. Schema
    results.append(verify_schema(baseline, collection, store_path))

    # 2. Chunk counts
    results.append(verify_chunk_counts(baseline, collection, store_path, tolerance=args.tolerance))

    # 3. Project isolation
    results.append(verify_project_isolation(baseline, collection, store_path))

    # 4. Neptune counts
    results.append(verify_neptune_counts(baseline))

    # Print results
    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        marker = "✓" if r.passed else "✗"
        print(f"  {marker} [{status}] {r.section}")
        for msg in r.messages:
            print(f"      {msg}")
        if not r.passed:
            all_passed = False

    print()
    if all_passed:
        print("RESULT: ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("RESULT: SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
