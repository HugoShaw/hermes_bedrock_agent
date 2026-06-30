"""Record baseline metrics for DualRAG pipeline.

Usage:
    uv run python tests/baseline/record_baseline.py \
        --output docs/baselines/2026-06-12/baseline.json \
        --collection murata_excel_vlm_dual_rag \
        --projects saimu_bugyo_cloud,sample_20260529
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any


def _serialize_chunk(obj: Any) -> Any:
    """Serialize an object to JSON-safe types.

    Handles dict, dataclass, Pydantic BaseModel, and objects with __dict__.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize_chunk(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_chunk(v) for k, v in obj.items()}
    # Pydantic BaseModel
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # dataclass
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    # fallback
    if hasattr(obj, "__dict__"):
        return {k: _serialize_chunk(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def _sha256_dir(dir_path: Path) -> str:
    """Compute SHA-256 over sorted file contents of a directory."""
    h = hashlib.sha256()
    for f in sorted(dir_path.rglob("*")):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()


def _discover_vlm_dirs(base_dir: Path) -> list[Path]:
    """Auto-discover vlm_parsed directories under a base path."""
    return sorted(base_dir.rglob("vlm_parsed"))


def record_lancedb_schema(collection: str, store_path: str) -> dict:
    """Record LanceDB schema (column names and types)."""
    try:
        import lancedb

        db = lancedb.connect(store_path)
        if collection not in db.table_names():
            return {"error": f"Collection '{collection}' not found"}
        table = db.open_table(collection)
        schema = table.schema
        columns = []
        for i in range(len(schema)):
            field = schema.field(i)
            columns.append({"name": field.name, "type": str(field.type)})
        return {"columns": columns}
    except Exception as exc:
        return {"error": str(exc)}


def record_chunk_counts(collection: str, store_path: str, project_ids: list[str]) -> dict:
    """Record per-project_id row counts in LanceDB."""
    try:
        import lancedb
        import pyarrow.compute as pc

        db = lancedb.connect(store_path)
        if collection not in db.table_names():
            return {"error": f"Collection '{collection}' not found"}
        table = db.open_table(collection)
        counts = {}
        for pid in project_ids:
            try:
                rows = table.search().where(f"project_id = '{pid}'", prefilter=True).limit(100000).to_list()
                counts[pid] = len(rows)
            except Exception as exc:
                counts[pid] = {"error": str(exc)}
        total = table.count_rows()
        counts["__total__"] = total
        return counts
    except Exception as exc:
        return {"error": str(exc)}


def record_project_isolation(collection: str, store_path: str, project_ids: list[str]) -> dict:
    """Verify no cross-project_id contamination."""
    try:
        import lancedb

        db = lancedb.connect(store_path)
        if collection not in db.table_names():
            return {"error": f"Collection '{collection}' not found"}
        table = db.open_table(collection)
        results = {}
        for pid in project_ids:
            rows = table.search().where(f"project_id = '{pid}'", prefilter=True).limit(10).to_list()
            other_projects = set()
            for r in rows:
                row_pid = r.get("project_id", "")
                if row_pid and row_pid != pid:
                    other_projects.add(row_pid)
            results[pid] = {
                "contamination": list(other_projects),
                "is_clean": len(other_projects) == 0,
            }
        return results
    except Exception as exc:
        return {"error": str(exc)}


def record_neptune_counts(project_ids: list[str]) -> dict:
    """Record Neptune node/edge counts per project. Graceful degradation."""
    try:
        from hermes_bedrock_agent.config import config
        from hermes_bedrock_agent.retrieval.graph_guided_retrieval import GraphGuidedRetriever

        retriever = GraphGuidedRetriever()
        counts = {}
        for pid in project_ids:
            try:
                node_query = f"g.V().has('project_id', '{pid}').count()"
                edge_query = f"g.V().has('project_id', '{pid}').outE().count()"
                node_resp = retriever._execute_query(node_query)
                edge_resp = retriever._execute_query(edge_query)
                counts[pid] = {
                    "nodes": node_resp[0] if node_resp else 0,
                    "edges": edge_resp[0] if edge_resp else 0,
                }
            except Exception as exc:
                counts[pid] = {"error": str(exc)}
        return counts
    except Exception as exc:
        return {"error": f"Neptune unreachable: {exc}"}


def record_qa_snapshot(
    collection: str, store_path: str, project_ids: list[str], queries: list[str] | None = None
) -> dict:
    """Record QA vector search snapshot: queries × projects → top-5 results."""
    default_queries = [
        "データ連携の方法を教えてください",
        "システム構成図について説明してください",
        "エラーが発生した場合の対処法",
    ]
    queries = queries or default_queries

    try:
        from hermes_bedrock_agent.knowledge_base.vector_store import query_vector_store

        results = {}
        for pid in project_ids:
            pid_results = {}
            for q in queries:
                try:
                    hits = query_vector_store(
                        q, top_k=5, store_path=store_path,
                        collection=collection, project_id=pid,
                    )
                    pid_results[q] = [
                        {
                            "id": h.get("id", ""),
                            "distance": h.get("_distance", 0.0),
                            "chunk_type": h.get("chunk_type", ""),
                            "sheet_name": h.get("sheet_name", ""),
                            "text_preview": h.get("text", "")[:200],
                        }
                        for h in hits
                    ]
                except Exception as exc:
                    pid_results[q] = {"error": str(exc)}
            results[pid] = pid_results
        return results
    except Exception as exc:
        return {"error": f"Embedding/search failed: {exc}"}


def record_test_suite() -> dict:
    """Run pytest and capture exit code + counts."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--tb=no", "-q"],
            capture_output=True, text=True, timeout=120,
        )
        return {
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": "pytest timed out (120s)"}
    except Exception as exc:
        return {"error": str(exc)}


def record_chunker_snapshot(vlm_dirs: list[Path]) -> dict:
    """SHA-256 of known vlm_parsed directories."""
    snapshots = {}
    for d in vlm_dirs:
        if d.exists() and d.is_dir():
            snapshots[str(d)] = _sha256_dir(d)
        else:
            snapshots[str(d)] = {"error": "directory not found"}
    return snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description="Record baseline metrics for DualRAG pipeline.")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--collection", default="murata_excel_vlm_dual_rag", help="LanceDB collection name")
    parser.add_argument("--store-path", default="", help="LanceDB store path (default: from config)")
    parser.add_argument("--projects", required=True, help="Comma-separated project_ids")
    parser.add_argument("--snapshot-vlm-dir", default="", help="Base dir to discover vlm_parsed/ (auto-discovers if empty)")
    parser.add_argument("--skip-neptune", action="store_true", help="Skip Neptune recording")
    parser.add_argument("--skip-qa", action="store_true", help="Skip QA snapshot recording")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test suite recording")

    args = parser.parse_args()

    project_ids = [p.strip() for p in args.projects.split(",") if p.strip()]

    # Resolve store path
    store_path = args.store_path
    if not store_path:
        try:
            from hermes_bedrock_agent.config import config
            store_path = config.lancedb_path
        except Exception:
            store_path = "lancedb_store"

    baseline: dict[str, Any] = {
        "meta": {
            "collection": args.collection,
            "store_path": store_path,
            "project_ids": project_ids,
        },
    }

    print(f"Recording baseline for projects: {project_ids}")
    print(f"  Collection: {args.collection}")
    print(f"  Store path: {store_path}")

    # 1. LanceDB schema
    print("  [1/7] LanceDB schema...")
    baseline["lancedb_schema"] = record_lancedb_schema(args.collection, store_path)

    # 2. Chunk counts
    print("  [2/7] Chunk counts...")
    baseline["chunk_counts"] = record_chunk_counts(args.collection, store_path, project_ids)

    # 3. Project isolation
    print("  [3/7] Project isolation check...")
    baseline["project_isolation"] = record_project_isolation(args.collection, store_path, project_ids)

    # 4. Neptune counts
    if not args.skip_neptune:
        print("  [4/7] Neptune counts...")
        baseline["neptune_counts"] = record_neptune_counts(project_ids)
    else:
        print("  [4/7] Neptune counts... SKIPPED")
        baseline["neptune_counts"] = {"skipped": True}

    # 5. QA snapshot
    if not args.skip_qa:
        print("  [5/7] QA vector search snapshot...")
        baseline["qa_snapshot"] = record_qa_snapshot(args.collection, store_path, project_ids)
    else:
        print("  [5/7] QA vector search snapshot... SKIPPED")
        baseline["qa_snapshot"] = {"skipped": True}

    # 6. Test suite
    if not args.skip_tests:
        print("  [6/7] Test suite results...")
        baseline["test_suite"] = record_test_suite()
    else:
        print("  [6/7] Test suite results... SKIPPED")
        baseline["test_suite"] = {"skipped": True}

    # 7. Chunker snapshot
    print("  [7/7] Chunker snapshot...")
    if args.snapshot_vlm_dir:
        vlm_dirs = [Path(args.snapshot_vlm_dir)]
    else:
        vlm_dirs = _discover_vlm_dirs(Path("outputs"))
    baseline["chunker_snapshot"] = record_chunker_snapshot(vlm_dirs)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False, default=str))
    print(f"\nBaseline recorded → {output_path}")


if __name__ == "__main__":
    main()
