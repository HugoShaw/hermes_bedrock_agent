"""Phase 9.3B — Neptune Sample Live Import.

Loads a small sample (--max-nodes, --max-edges) to verify the live write path.
Uses parameterized queries from graph/neptune_loader.py (Phase 6.5).
Does NOT use the dry-run .cypher files (those are for human review only).

Usage:
    python scripts/neptune_sample_import.py \
        --run-id murata_live_v1 \
        --dataset murata \
        --max-nodes 100 \
        --max-edges 200 \
        --batch-size 50
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Project imports
from hermes_bedrock_agent.clients.neptune_client import NeptuneClient, NeptuneClientError
from hermes_bedrock_agent.graph.neptune_loader import (
    entity_type_to_label,
    relation_type_to_cypher_type,
    serialize_property_value,
)
from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARTIFACTS_DIR = Path.home() / "projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts"
NEPTUNE_GRAPH_ID = "g-nbuyck5yl8"
NEPTUNE_REGION = "ap-northeast-1"
SOURCE_PREFIX = "s3://s3-hulftchina-rd/Murata/"

# i18n display fields to propagate if present
ENTITY_DISPLAY_FIELDS = [
    "display_name", "display_name_zh", "display_name_en", "display_name_ja",
    "description_zh", "description_en", "description_ja", "label_mode_hint",
]
RELATION_DISPLAY_FIELDS = ["display_label", "label_zh", "label_en", "label_ja"]


# ---------------------------------------------------------------------------
# Property builders with run_id/dataset/i18n
# ---------------------------------------------------------------------------

def build_node_props(entity: dict, run_id: str, dataset: str) -> dict[str, Any]:
    """Build property dict for a node from raw JSONL entity dict."""
    props: dict[str, Any] = {
        "entity_id": entity["entity_id"],
        "name": entity.get("name", ""),
        "canonical_name": entity.get("canonical_name", ""),
        "entity_type": entity.get("entity_type", "unknown"),
        "description": entity.get("description", ""),
        "confidence": entity.get("confidence", 0.0),
        "extraction_count": entity.get("extraction_count", 1),
        # Provenance metadata for cleanup/isolation
        "run_id": run_id,
        "dataset": dataset,
        "source_prefix": SOURCE_PREFIX,
    }

    # Source chunk IDs as comma-separated (Neptune doesn't support arrays)
    if entity.get("source_chunk_ids"):
        props["source_chunk_ids"] = ", ".join(entity["source_chunk_ids"])
    if entity.get("aliases"):
        props["aliases"] = ", ".join(entity["aliases"])
    if entity.get("acl"):
        props["acl"] = ", ".join(entity["acl"])
    if entity.get("model_name"):
        props["model_name"] = entity["model_name"]
    if entity.get("created_at"):
        props["created_at"] = entity["created_at"]

    # Display/i18n fields — with fallback
    display_name = (
        entity.get("display_name")
        or entity.get("canonical_name")
        or entity.get("name")
        or entity["entity_id"]
    )
    props["display_name"] = display_name

    # Only add i18n fields if they exist and are non-empty
    for field in ENTITY_DISPLAY_FIELDS:
        if field == "display_name":
            continue  # already handled
        val = entity.get(field)
        if val:
            props[field] = val

    return props


def build_edge_props(relation: dict, run_id: str, dataset: str) -> dict[str, Any]:
    """Build property dict for an edge from raw JSONL relation dict."""
    props: dict[str, Any] = {
        "relation_id": relation["relation_id"],
        "relation_type": relation.get("relation_type", "related_to"),
        "description": relation.get("description", ""),
        "confidence": relation.get("confidence", 0.0),
        "weight": relation.get("weight", 1.0),
        "source_chunk_id": relation.get("source_chunk_id", ""),
        "evidence_id": relation.get("evidence_id", ""),
        # Provenance
        "run_id": run_id,
        "dataset": dataset,
        "source_prefix": SOURCE_PREFIX,
    }

    if relation.get("source_chunk_ids"):
        props["source_chunk_ids"] = ", ".join(relation["source_chunk_ids"])
    if relation.get("evidence_text"):
        # Truncate evidence_text for Neptune (max ~10KB per property)
        props["evidence_text"] = relation["evidence_text"][:2000]
    if relation.get("acl"):
        props["acl"] = ", ".join(relation["acl"])
    if relation.get("model_name"):
        props["model_name"] = relation["model_name"]
    if relation.get("created_at"):
        props["created_at"] = relation["created_at"]

    # Display/i18n with fallback
    display_label = relation.get("display_label") or relation.get("relation_type", "related_to")
    props["display_label"] = display_label

    for field in RELATION_DISPLAY_FIELDS:
        if field == "display_label":
            continue
        val = relation.get(field)
        if val:
            props[field] = val

    return props


# ---------------------------------------------------------------------------
# Batch loading with retry and failure tracking
# ---------------------------------------------------------------------------

def load_nodes_batch(
    client: NeptuneClient,
    entities: list[dict],
    run_id: str,
    dataset: str,
    batch_size: int = 50,
    max_retries: int = 2,
) -> tuple[int, int, list[dict]]:
    """Load entity nodes to Neptune with batch retry.

    Returns: (loaded_count, error_count, failed_batches)
    """
    loaded = 0
    errors = 0
    failed_batches = []

    for i in range(0, len(entities), batch_size):
        batch = entities[i: i + batch_size]
        batch_failures = []

        for entity in batch:
            label = entity_type_to_label(entity.get("entity_type", "unknown"))
            props = build_node_props(entity, run_id, dataset)
            eid = entity["entity_id"]

            query = (
                f"MERGE (n:`{label}` {{entity_id: $entity_id}}) "
                f"SET n += $props "
                f"RETURN n.entity_id AS id"
            )
            params = {"entity_id": eid, "props": props}

            success = False
            for attempt in range(max_retries + 1):
                try:
                    client.execute_query(query, parameters=params)
                    loaded += 1
                    success = True
                    break
                except NeptuneClientError as e:
                    if attempt < max_retries:
                        time.sleep(1 * (attempt + 1))
                    else:
                        logger.warning(f"Node load failed after {max_retries + 1} attempts: {eid}: {e}")
                        errors += 1
                        batch_failures.append({
                            "entity_id": eid,
                            "error": str(e),
                            "label": label,
                        })

        if batch_failures:
            failed_batches.append({
                "batch_index": i // batch_size,
                "batch_start": i,
                "type": "node",
                "failures": batch_failures,
            })

        if (i // batch_size + 1) % 2 == 0:
            logger.info(f"  Nodes progress: {loaded}/{len(entities)} loaded, {errors} errors")

    return loaded, errors, failed_batches


def load_edges_batch(
    client: NeptuneClient,
    relations: list[dict],
    run_id: str,
    dataset: str,
    batch_size: int = 50,
    max_retries: int = 2,
) -> tuple[int, int, list[dict]]:
    """Load relation edges to Neptune with batch retry.

    Returns: (loaded_count, error_count, failed_batches)
    """
    loaded = 0
    errors = 0
    failed_batches = []

    for i in range(0, len(relations), batch_size):
        batch = relations[i: i + batch_size]
        batch_failures = []

        for relation in batch:
            rtype = relation_type_to_cypher_type(relation.get("relation_type", "related_to"))
            props = build_edge_props(relation, run_id, dataset)
            rid = relation["relation_id"]
            src = relation["source_entity_id"]
            tgt = relation["target_entity_id"]

            query = (
                f"MATCH (a {{entity_id: $from_id}}), (b {{entity_id: $to_id}}) "
                f"MERGE (a)-[r:`{rtype}`]->(b) "
                f"SET r += $props "
                f"RETURN r.relation_id AS id"
            )
            params = {"from_id": src, "to_id": tgt, "props": props}

            success = False
            for attempt in range(max_retries + 1):
                try:
                    client.execute_query(query, parameters=params)
                    loaded += 1
                    success = True
                    break
                except NeptuneClientError as e:
                    if attempt < max_retries:
                        time.sleep(1 * (attempt + 1))
                    else:
                        logger.warning(f"Edge load failed after {max_retries + 1} attempts: {rid}: {e}")
                        errors += 1
                        batch_failures.append({
                            "relation_id": rid,
                            "error": str(e),
                            "source_entity_id": src,
                            "target_entity_id": tgt,
                            "relation_type": relation.get("relation_type", ""),
                        })

        if batch_failures:
            failed_batches.append({
                "batch_index": i // batch_size,
                "batch_start": i,
                "type": "edge",
                "failures": batch_failures,
            })

        if (i // batch_size + 1) % 4 == 0:
            logger.info(f"  Edges progress: {loaded}/{len(relations)} loaded, {errors} errors")

    return loaded, errors, failed_batches


# ---------------------------------------------------------------------------
# Verification queries
# ---------------------------------------------------------------------------

def verify_import(client: NeptuneClient, run_id: str, dataset: str) -> dict[str, Any]:
    """Run verification queries after import."""
    results = {}

    # 1. Node count by run_id + dataset
    try:
        r = client.execute_query(
            "MATCH (n {run_id: $run_id, dataset: $dataset}) RETURN count(n) AS cnt",
            parameters={"run_id": run_id, "dataset": dataset},
        )
        results["node_count"] = r.get("results", [{}])[0].get("cnt", 0)
    except Exception as e:
        results["node_count"] = f"ERROR: {e}"

    # 2. Edge count by run_id
    try:
        r = client.execute_query(
            "MATCH (a {run_id: $run_id})-[r]->(b {run_id: $run_id}) RETURN count(r) AS cnt",
            parameters={"run_id": run_id},
        )
        results["edge_count"] = r.get("results", [{}])[0].get("cnt", 0)
    except Exception as e:
        results["edge_count"] = f"ERROR: {e}"

    # 3. Label distribution
    try:
        r = client.execute_query(
            "MATCH (n {run_id: $run_id, dataset: $dataset}) "
            "RETURN labels(n) AS lbl, count(n) AS cnt ORDER BY cnt DESC",
            parameters={"run_id": run_id, "dataset": dataset},
        )
        results["label_distribution"] = r.get("results", [])
    except Exception as e:
        results["label_distribution"] = f"ERROR: {e}"

    # 4. Relation type distribution
    try:
        r = client.execute_query(
            "MATCH (a {run_id: $run_id})-[r]->(b {run_id: $run_id}) "
            "RETURN type(r) AS rtype, count(r) AS cnt ORDER BY cnt DESC",
            parameters={"run_id": run_id},
        )
        results["relation_type_distribution"] = r.get("results", [])
    except Exception as e:
        results["relation_type_distribution"] = f"ERROR: {e}"

    # 5. Random 5 nodes with run_id/dataset/source_prefix check
    try:
        r = client.execute_query(
            "MATCH (n {run_id: $run_id, dataset: $dataset}) "
            "RETURN n.entity_id AS eid, n.name AS name, n.entity_type AS etype, "
            "n.run_id AS run_id, n.dataset AS dataset, n.source_prefix AS src, "
            "n.display_name AS display_name "
            "LIMIT 5",
            parameters={"run_id": run_id, "dataset": dataset},
        )
        results["sample_nodes"] = r.get("results", [])
    except Exception as e:
        results["sample_nodes"] = f"ERROR: {e}"

    # 6. Random 5 edges with run_id/dataset/source_prefix check
    try:
        r = client.execute_query(
            "MATCH (a {run_id: $run_id})-[r]->(b {run_id: $run_id}) "
            "RETURN r.relation_id AS rid, type(r) AS rtype, r.confidence AS conf, "
            "r.run_id AS run_id, r.dataset AS dataset, r.source_prefix AS src, "
            "r.display_label AS display_label "
            "LIMIT 5",
            parameters={"run_id": run_id},
        )
        results["sample_edges"] = r.get("results", [])
    except Exception as e:
        results["sample_edges"] = f"ERROR: {e}"

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Neptune Sample Live Import")
    parser.add_argument("--run-id", default="murata_live_v1")
    parser.add_argument("--dataset", default="murata")
    parser.add_argument("--max-nodes", type=int, default=100)
    parser.add_argument("--max-edges", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--graph-id", default=NEPTUNE_GRAPH_ID)
    parser.add_argument("--region", default=NEPTUNE_REGION)
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    artifacts = Path(args.artifacts_dir)
    run_id = args.run_id
    dataset = args.dataset

    logger.info("=" * 70)
    logger.info("PHASE 9.3B — NEPTUNE SAMPLE LIVE IMPORT")
    logger.info("=" * 70)
    logger.info(f"  Run ID: {run_id}")
    logger.info(f"  Dataset: {dataset}")
    logger.info(f"  Max nodes: {args.max_nodes}")
    logger.info(f"  Max edges: {args.max_edges}")
    logger.info(f"  Batch size: {args.batch_size}")
    logger.info(f"  Graph ID: {args.graph_id}")
    logger.info(f"  Region: {args.region}")
    logger.info(f"  Source prefix: {SOURCE_PREFIX}")
    logger.info("=" * 70)

    # Load data
    logger.info("Loading entities from entities.jsonl...")
    with open(artifacts / "entities.jsonl") as f:
        all_entities = [json.loads(l) for l in f]
    logger.info(f"  Loaded {len(all_entities)} entities total")

    logger.info("Loading relations from relations_clean.jsonl...")
    with open(artifacts / "relations_clean.jsonl") as f:
        all_relations = [json.loads(l) for l in f]
    logger.info(f"  Loaded {len(all_relations)} relations total")

    # Take sample
    sample_entities = all_entities[: args.max_nodes]
    # For edges: only take edges where BOTH endpoints are in the sample entity set
    sample_entity_ids = {e["entity_id"] for e in sample_entities}
    sample_relations = []
    for r in all_relations:
        if r["source_entity_id"] in sample_entity_ids and r["target_entity_id"] in sample_entity_ids:
            sample_relations.append(r)
            if len(sample_relations) >= args.max_edges:
                break

    logger.info(f"  Sample: {len(sample_entities)} nodes, {len(sample_relations)} edges")

    # Connect to Neptune
    logger.info("Connecting to Neptune...")
    client = NeptuneClient(graph_id=args.graph_id, region=args.region)

    # Ping
    if not client.ping():
        logger.error("Neptune ping failed! Aborting.")
        return

    logger.info("  Neptune ping: OK")

    # Check existing data
    pre_stats = client.get_graph_statistics()
    logger.info(f"  Pre-import graph: {pre_stats.get('node_count', '?')} nodes, {pre_stats.get('edge_count', '?')} edges")

    # --- Load nodes ---
    logger.info(f"Loading {len(sample_entities)} nodes...")
    t0 = time.time()
    nodes_loaded, node_errors, node_failures = load_nodes_batch(
        client, sample_entities, run_id, dataset, batch_size=args.batch_size
    )
    node_time = time.time() - t0
    logger.info(f"  Nodes: {nodes_loaded} loaded, {node_errors} errors, {node_time:.1f}s")

    # --- Load edges ---
    logger.info(f"Loading {len(sample_relations)} edges...")
    t1 = time.time()
    edges_loaded, edge_errors, edge_failures = load_edges_batch(
        client, sample_relations, run_id, dataset, batch_size=args.batch_size
    )
    edge_time = time.time() - t1
    logger.info(f"  Edges: {edges_loaded} loaded, {edge_errors} errors, {edge_time:.1f}s")

    total_time = node_time + edge_time
    logger.info(f"  Total time: {total_time:.1f}s")

    # --- Verify ---
    logger.info("Running verification queries...")
    verification = verify_import(client, run_id, dataset)
    logger.info(f"  Verified node count: {verification.get('node_count')}")
    logger.info(f"  Verified edge count: {verification.get('edge_count')}")

    # --- Save failed batches ---
    all_failures = node_failures + edge_failures
    failed_path = artifacts / "failed_neptune_batches.jsonl"
    with open(failed_path, "w") as f:
        for fb in all_failures:
            f.write(json.dumps(fb, ensure_ascii=False) + "\n")
    logger.info(f"  Failed batches: {len(all_failures)} (saved to {failed_path})")

    # --- Generate report ---
    report = {
        "run_id": run_id,
        "dataset": dataset,
        "phase": "9.3B_neptune_sample_live_import",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "SAMPLE LIVE IMPORT",
        "config": {
            "max_nodes": args.max_nodes,
            "max_edges": args.max_edges,
            "batch_size": args.batch_size,
            "graph_id": args.graph_id,
            "region": args.region,
            "source_prefix": SOURCE_PREFIX,
        },
        "sample_selection": {
            "entities_available": len(all_entities),
            "entities_selected": len(sample_entities),
            "relations_available": len(all_relations),
            "relations_selected": len(sample_relations),
            "selection_method": "first N entities + relations where both endpoints in sample",
        },
        "load_results": {
            "nodes_loaded": nodes_loaded,
            "node_errors": node_errors,
            "edges_loaded": edges_loaded,
            "edge_errors": edge_errors,
            "total_loaded": nodes_loaded + edges_loaded,
            "total_errors": node_errors + edge_errors,
            "node_time_seconds": round(node_time, 1),
            "edge_time_seconds": round(edge_time, 1),
            "total_time_seconds": round(total_time, 1),
            "avg_node_time_ms": round(1000 * node_time / max(nodes_loaded, 1), 1),
            "avg_edge_time_ms": round(1000 * edge_time / max(edges_loaded, 1), 1),
        },
        "verification": verification,
        "failed_batches": {
            "count": len(all_failures),
            "file": "failed_neptune_batches.jsonl",
        },
        "i18n_statistics": {
            "entities_with_display_name": sum(1 for e in sample_entities if e.get("display_name")),
            "entities_with_i18n_fields": sum(1 for e in sample_entities if any(e.get(f) for f in ["display_name_zh", "display_name_en", "display_name_ja"])),
            "relations_with_display_label": sum(1 for r in sample_relations if r.get("display_label")),
            "relations_with_i18n_fields": sum(1 for r in sample_relations if any(r.get(f) for f in ["label_zh", "label_en", "label_ja"])),
            "note": "i18n display fields reserved but empty — Phase 10 enrichment",
        },
        "cleanup_query": {
            "delete_nodes": f"MATCH (n {{run_id: '{run_id}', dataset: '{dataset}'}}) DETACH DELETE n",
            "warning": "DO NOT auto-execute — review before cleanup",
        },
        "pre_import_graph_stats": pre_stats,
    }

    # Save JSON report
    report_path = artifacts / "neptune_sample_load_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"  Report: {report_path}")

    # Save MD report
    md_report = _generate_md_report(report, verification, sample_entities, sample_relations)
    md_path = artifacts / "neptune_sample_load_report.md"
    with open(md_path, "w") as f:
        f.write(md_report)
    logger.info(f"  Report: {md_path}")

    # Save cleanup commands
    cleanup_md = f"""# Neptune Cleanup Commands — Phase 9.3B Sample Import

**Run ID:** {run_id}
**Dataset:** {dataset}
**Imported:** {nodes_loaded} nodes + {edges_loaded} edges

## Cleanup (remove sample data)

```cypher
// WARNING: Removes ALL nodes/edges with this run_id + dataset
MATCH (n {{run_id: '{run_id}', dataset: '{dataset}'}})
DETACH DELETE n
```

## Verify cleanup

```cypher
MATCH (n {{run_id: '{run_id}', dataset: '{dataset}'}})
RETURN count(n) AS remaining_nodes
```

## DO NOT auto-execute cleanup without human confirmation.
"""
    cleanup_path = artifacts / "cleanup_commands.md"
    with open(cleanup_path, "w") as f:
        f.write(cleanup_md)
    logger.info(f"  Cleanup: {cleanup_path}")

    logger.info("=" * 70)
    logger.info("PHASE 9.3B COMPLETE")
    logger.info(f"  Nodes: {nodes_loaded}/{len(sample_entities)} loaded")
    logger.info(f"  Edges: {edges_loaded}/{len(sample_relations)} loaded")
    logger.info(f"  Errors: {node_errors + edge_errors}")
    logger.info(f"  Time: {total_time:.1f}s")
    logger.info("=" * 70)


def _generate_md_report(report: dict, verification: dict, entities: list, relations: list) -> str:
    """Generate markdown report."""
    r = report
    lr = r["load_results"]
    cfg = r["config"]

    lines = [
        "# Phase 9.3B — Neptune Sample Live Import Report\n",
        f"**Run ID:** {r['run_id']}",
        f"**Dataset:** {r['dataset']}",
        f"**Date:** {r['timestamp']}",
        f"**Mode:** SAMPLE LIVE IMPORT",
        "",
        "---",
        "",
        "## Configuration\n",
        f"| Parameter | Value |",
        f"|-----------|-------|",
        f"| Graph ID | {cfg['graph_id']} |",
        f"| Region | {cfg['region']} |",
        f"| Max nodes | {cfg['max_nodes']} |",
        f"| Max edges | {cfg['max_edges']} |",
        f"| Batch size | {cfg['batch_size']} |",
        f"| Source prefix | {cfg['source_prefix']} |",
        "",
        "## Load Results\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Nodes loaded | {lr['nodes_loaded']} |",
        f"| Node errors | {lr['node_errors']} |",
        f"| Edges loaded | {lr['edges_loaded']} |",
        f"| Edge errors | {lr['edge_errors']} |",
        f"| Total time | {lr['total_time_seconds']}s |",
        f"| Avg node time | {lr['avg_node_time_ms']}ms |",
        f"| Avg edge time | {lr['avg_edge_time_ms']}ms |",
        "",
        "## Verification\n",
        f"| Query | Result |",
        f"|-------|--------|",
        f"| Node count (run_id + dataset) | {verification.get('node_count', '?')} |",
        f"| Edge count (run_id) | {verification.get('edge_count', '?')} |",
        "",
        "### Label Distribution\n",
        "```",
    ]

    label_dist = verification.get("label_distribution", [])
    if isinstance(label_dist, list):
        for item in label_dist:
            lines.append(f"  {item.get('lbl', '?')}: {item.get('cnt', '?')}")
    else:
        lines.append(f"  {label_dist}")
    lines.append("```\n")

    lines.append("### Relation Type Distribution\n")
    lines.append("```")
    rtype_dist = verification.get("relation_type_distribution", [])
    if isinstance(rtype_dist, list):
        for item in rtype_dist:
            lines.append(f"  {item.get('rtype', '?')}: {item.get('cnt', '?')}")
    else:
        lines.append(f"  {rtype_dist}")
    lines.append("```\n")

    lines.append("### Sample Nodes (run_id/dataset/source_prefix check)\n")
    lines.append("```")
    sample_nodes = verification.get("sample_nodes", [])
    if isinstance(sample_nodes, list):
        for node in sample_nodes:
            lines.append(f"  {node.get('eid', '?')[:25]} | {node.get('name', '?')[:20]} | "
                        f"run_id={node.get('run_id', '?')} | dataset={node.get('dataset', '?')} | "
                        f"display={node.get('display_name', '?')[:20]}")
    lines.append("```\n")

    lines.append("### Sample Edges (run_id/dataset/source_prefix check)\n")
    lines.append("```")
    sample_edges = verification.get("sample_edges", [])
    if isinstance(sample_edges, list):
        for edge in sample_edges:
            lines.append(f"  {edge.get('rid', '?')[:25]} | {edge.get('rtype', '?')} | "
                        f"run_id={edge.get('run_id', '?')} | display_label={edge.get('display_label', '?')}")
    lines.append("```\n")

    i18n = r.get("i18n_statistics", {})
    lines.extend([
        "## i18n Field Statistics\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| entities_with_display_name | {i18n.get('entities_with_display_name', 0)} (fallback to canonical_name) |",
        f"| entities_with_i18n_fields | {i18n.get('entities_with_i18n_fields', 0)} (Phase 10) |",
        f"| relations_with_display_label | {i18n.get('relations_with_display_label', 0)} (fallback to relation_type) |",
        f"| relations_with_i18n_fields | {i18n.get('relations_with_i18n_fields', 0)} (Phase 10) |",
        "",
        "> 多语言展示将在 Phase 10 实现。当前只是 import 兼容字段预留。",
        "",
        "## Cleanup Command\n",
        "```cypher",
        f"// Remove sample data (DO NOT auto-execute)",
        f"MATCH (n {{run_id: '{r['run_id']}', dataset: '{r['dataset']}'}}) DETACH DELETE n",
        "```",
        "",
        "## Verdict\n",
    ])

    total_errors = lr['node_errors'] + lr['edge_errors']
    if total_errors == 0:
        lines.append("**✓ SAMPLE IMPORT SUCCESSFUL** — Ready for Phase 9.3C full live import upon user confirmation.")
    else:
        lines.append(f"**⚠️ SAMPLE IMPORT HAD {total_errors} ERRORS** — Review failed_neptune_batches.jsonl before proceeding.")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
