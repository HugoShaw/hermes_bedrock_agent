"""Phase 9.3C — Neptune Full Live Import.

Loads ALL entities (3,034) and clean relations (6,536) to Neptune.
Uses parameterized queries — no inline Cypher execution.

Prerequisites:
- Sample data cleaned (count = 0)
- entities.jsonl ready
- relations_clean.jsonl ready (orphans removed)
"""
from __future__ import annotations

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, "/home/ubuntu/projects/hermes_bedrock_agent/src")

from hermes_bedrock_agent.clients.neptune_client import NeptuneClient, NeptuneClientError
from hermes_bedrock_agent.graph.neptune_loader import (
    entity_type_to_label,
    relation_type_to_cypher_type,
    serialize_property_value,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Config
ARTIFACTS = Path("/home/ubuntu/projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts")
GRAPH_ID = "g-nbuyck5yl8"
REGION = "ap-northeast-1"
RUN_ID = "murata_live_v1"
DATASET = "murata"
SOURCE_PREFIX = "s3://s3-hulftchina-rd/Murata/"
BATCH_SIZE = 50
MAX_RETRIES = 2

ENTITY_DISPLAY_FIELDS = [
    "display_name", "display_name_zh", "display_name_en", "display_name_ja",
    "description_zh", "description_en", "description_ja", "label_mode_hint",
]
RELATION_DISPLAY_FIELDS = ["display_label", "label_zh", "label_en", "label_ja"]


def build_node_props(entity: dict) -> dict[str, Any]:
    props = {
        "entity_id": entity["entity_id"],
        "name": entity.get("name", ""),
        "canonical_name": entity.get("canonical_name", ""),
        "entity_type": entity.get("entity_type", "unknown"),
        "description": entity.get("description", "")[:2000],
        "confidence": entity.get("confidence", 0.0),
        "extraction_count": entity.get("extraction_count", 1),
        "run_id": RUN_ID,
        "dataset": DATASET,
        "source_prefix": SOURCE_PREFIX,
    }
    if entity.get("source_chunk_ids"):
        props["source_chunk_ids"] = ", ".join(entity["source_chunk_ids"][:50])
    if entity.get("aliases"):
        props["aliases"] = ", ".join(entity["aliases"][:20])
    if entity.get("acl"):
        props["acl"] = ", ".join(entity["acl"])
    if entity.get("model_name"):
        props["model_name"] = entity["model_name"]
    if entity.get("created_at"):
        props["created_at"] = entity["created_at"]

    # Display fallback
    props["display_name"] = (
        entity.get("display_name")
        or entity.get("canonical_name")
        or entity.get("name")
        or entity["entity_id"]
    )
    for field in ENTITY_DISPLAY_FIELDS:
        if field == "display_name":
            continue
        val = entity.get(field)
        if val:
            props[field] = val
    return props


def build_edge_props(relation: dict) -> dict[str, Any]:
    props = {
        "relation_id": relation["relation_id"],
        "relation_type": relation.get("relation_type", "related_to"),
        "description": relation.get("description", "")[:2000],
        "confidence": relation.get("confidence", 0.0),
        "weight": relation.get("weight", 1.0),
        "source_chunk_id": relation.get("source_chunk_id", ""),
        "evidence_id": relation.get("evidence_id", ""),
        "run_id": RUN_ID,
        "dataset": DATASET,
        "source_prefix": SOURCE_PREFIX,
    }
    if relation.get("source_chunk_ids"):
        props["source_chunk_ids"] = ", ".join(relation["source_chunk_ids"][:20])
    if relation.get("evidence_text"):
        props["evidence_text"] = relation["evidence_text"][:2000]
    if relation.get("acl"):
        props["acl"] = ", ".join(relation["acl"])
    if relation.get("model_name"):
        props["model_name"] = relation["model_name"]
    if relation.get("created_at"):
        props["created_at"] = relation["created_at"]

    props["display_label"] = relation.get("display_label") or relation.get("relation_type", "related_to")
    for field in RELATION_DISPLAY_FIELDS:
        if field == "display_label":
            continue
        val = relation.get(field)
        if val:
            props[field] = val
    return props


def main():
    logger.info("=" * 70)
    logger.info("PHASE 9.3C — NEPTUNE FULL LIVE IMPORT")
    logger.info("=" * 70)

    # Load data
    with open(ARTIFACTS / "entities.jsonl") as f:
        entities = [json.loads(l) for l in f]
    with open(ARTIFACTS / "relations_clean.jsonl") as f:
        relations = [json.loads(l) for l in f]
    logger.info(f"Loaded: {len(entities)} entities, {len(relations)} relations")

    client = NeptuneClient(graph_id=GRAPH_ID, region=REGION)
    assert client.ping(), "Neptune ping failed"
    logger.info("Neptune ping: OK")

    # Pre-check: should be 0
    r = client.execute_query(
        "MATCH (n {run_id: $run_id, dataset: $dataset}) RETURN count(n) AS cnt",
        parameters={"run_id": RUN_ID, "dataset": DATASET},
    )
    pre_count = r.get("results", [{}])[0].get("cnt", -1)
    logger.info(f"Pre-import count: {pre_count} (should be 0)")
    assert pre_count == 0, f"ABORT: graph not clean, {pre_count} nodes exist"

    # === LOAD NODES ===
    logger.info(f"Loading {len(entities)} nodes (batch_size={BATCH_SIZE})...")
    nodes_loaded = 0
    node_errors = 0
    node_failures = []
    t0 = time.time()

    for i in range(0, len(entities), BATCH_SIZE):
        batch = entities[i: i + BATCH_SIZE]
        for entity in batch:
            label = entity_type_to_label(entity.get("entity_type", "unknown"))
            props = build_node_props(entity)
            eid = entity["entity_id"]

            query = (
                f"MERGE (n:`{label}` {{entity_id: $entity_id}}) "
                f"SET n += $props "
                f"RETURN n.entity_id AS id"
            )
            params = {"entity_id": eid, "props": props}

            success = False
            for attempt in range(MAX_RETRIES + 1):
                try:
                    client.execute_query(query, parameters=params)
                    nodes_loaded += 1
                    success = True
                    break
                except NeptuneClientError as e:
                    if attempt < MAX_RETRIES:
                        time.sleep(1 * (attempt + 1))
                    else:
                        node_errors += 1
                        node_failures.append({
                            "entity_id": eid, "error": str(e), "label": label
                        })

        batch_num = i // BATCH_SIZE + 1
        if batch_num % 10 == 0:
            elapsed = time.time() - t0
            logger.info(f"  Nodes: {nodes_loaded}/{len(entities)} ({elapsed:.0f}s, {node_errors} errors)")

    node_time = time.time() - t0
    logger.info(f"  Nodes complete: {nodes_loaded} loaded, {node_errors} errors, {node_time:.1f}s")

    # === LOAD EDGES ===
    logger.info(f"Loading {len(relations)} edges (batch_size={BATCH_SIZE})...")
    edges_loaded = 0
    edge_errors = 0
    edge_failures = []
    t1 = time.time()

    for i in range(0, len(relations), BATCH_SIZE):
        batch = relations[i: i + BATCH_SIZE]
        for relation in batch:
            rtype = relation_type_to_cypher_type(relation.get("relation_type", "related_to"))
            props = build_edge_props(relation)
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
            for attempt in range(MAX_RETRIES + 1):
                try:
                    client.execute_query(query, parameters=params)
                    edges_loaded += 1
                    success = True
                    break
                except NeptuneClientError as e:
                    if attempt < MAX_RETRIES:
                        time.sleep(1 * (attempt + 1))
                    else:
                        edge_errors += 1
                        edge_failures.append({
                            "relation_id": rid, "error": str(e),
                            "source": src, "target": tgt, "type": relation.get("relation_type"),
                        })

        batch_num = i // BATCH_SIZE + 1
        if batch_num % 20 == 0:
            elapsed = time.time() - t1
            logger.info(f"  Edges: {edges_loaded}/{len(relations)} ({elapsed:.0f}s, {edge_errors} errors)")

    edge_time = time.time() - t1
    total_time = node_time + edge_time
    logger.info(f"  Edges complete: {edges_loaded} loaded, {edge_errors} errors, {edge_time:.1f}s")
    logger.info(f"  TOTAL: {nodes_loaded + edges_loaded} loaded, {node_errors + edge_errors} errors, {total_time:.1f}s")

    # Save failures
    all_failures = []
    if node_failures:
        all_failures.append({"type": "node", "failures": node_failures})
    if edge_failures:
        all_failures.append({"type": "edge", "failures": edge_failures})
    with open(ARTIFACTS / "failed_neptune_batches.jsonl", "w") as f:
        for fb in all_failures:
            f.write(json.dumps(fb, ensure_ascii=False) + "\n")

    # Save summary for verification script
    summary = {
        "nodes_loaded": nodes_loaded,
        "node_errors": node_errors,
        "edges_loaded": edges_loaded,
        "edge_errors": edge_errors,
        "node_time": node_time,
        "edge_time": edge_time,
        "total_time": total_time,
        "node_failures": node_failures,
        "edge_failures": edge_failures,
    }
    with open(ARTIFACTS / "_full_load_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("=" * 70)
    logger.info(f"PHASE 9.3C LOAD COMPLETE")
    logger.info(f"  Nodes: {nodes_loaded}/{len(entities)}")
    logger.info(f"  Edges: {edges_loaded}/{len(relations)}")
    logger.info(f"  Errors: {node_errors + edge_errors}")
    logger.info(f"  Time: {total_time:.1f}s")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
