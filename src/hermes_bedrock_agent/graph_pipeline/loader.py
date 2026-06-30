"""Execute Cypher statements against Neptune Analytics.

Supports:
  - dry-run mode (parse and log only, no network calls)
  - batched execution with configurable inter-call delay
  - error counting and retry for throttling (ThrottlingException)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from ..clients.neptune import NeptuneClient, NeptuneClientError

logger = logging.getLogger(__name__)

_THROTTLE_CODES = {"ThrottlingException", "Throttling", "LimitExceededException"}


def _execute_with_retry(
    client: NeptuneClient,
    cypher: str,
    max_retries: int = 3,
    base_delay: float = 5.0,
) -> bool:
    """Execute a single Cypher statement with exponential backoff on throttling."""
    for attempt in range(1, max_retries + 1):
        try:
            client.execute_query(cypher)
            return True
        except NeptuneClientError as exc:
            if exc.code in _THROTTLE_CODES and attempt < max_retries:
                wait = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Throttled (attempt %d/%d), retrying in %.1fs", attempt, max_retries, wait
                )
                time.sleep(wait)
            else:
                logger.error("Neptune error [%s]: %s", exc.code, exc)
                return False
    return False


def load_nodes(
    nodes: list,
    client: NeptuneClient,
    delay_seconds: float = 0.1,
    dry_run: bool = False,
) -> dict:
    """Load nodes into Neptune. Accepts PipelineNode models or plain dicts."""
    from .cypher_gen import node_to_cypher

    success = 0
    errors = 0

    for node in nodes:
        cypher = node_to_cypher(node)
        if dry_run:
            logger.debug("[dry-run] Node: %s", node.id if hasattr(node, "id") else node.get("id"))
            success += 1
            continue
        ok = _execute_with_retry(client, cypher)
        if ok:
            success += 1
        else:
            errors += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    logger.info("Nodes loaded: %d success, %d errors", success, errors)
    return {"success": success, "errors": errors}


def load_edges(
    edges: list,
    client: NeptuneClient,
    delay_seconds: float = 0.1,
    dry_run: bool = False,
) -> dict:
    """Load edges into Neptune. Accepts PipelineEdge models or plain dicts."""
    from .cypher_gen import edge_to_cypher

    success = 0
    errors = 0

    for edge in edges:
        cypher = edge_to_cypher(edge)
        if dry_run:
            logger.debug(
                "[dry-run] Edge: %s → %s",
                edge.start_id if hasattr(edge, "start_id") else edge.get("start_id"),
                edge.end_id if hasattr(edge, "end_id") else edge.get("end_id"),
            )
            success += 1
            continue
        ok = _execute_with_retry(client, cypher)
        if ok:
            success += 1
        else:
            errors += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    logger.info("Edges loaded: %d success, %d errors", success, errors)
    return {"success": success, "errors": errors}


def load_from_cypher_file(
    cypher_file: Path,
    client: NeptuneClient,
    delay_seconds: float = 0.1,
    dry_run: bool = False,
) -> dict:
    """Execute all statements from a .cypher file split on ';' newline."""
    text = cypher_file.read_text(encoding="utf-8")
    raw_stmts = [s.strip() for s in text.split(";") if s.strip()]

    success = 0
    errors = 0

    for stmt in raw_stmts:
        cypher = stmt + ";"
        if dry_run:
            success += 1
            continue
        ok = _execute_with_retry(client, cypher)
        if ok:
            success += 1
        else:
            errors += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return {"success": success, "errors": errors, "total": len(raw_stmts)}


def run_load(
    nodes: list,
    edges: list,
    neptune_graph_id: Optional[str],
    aws_region: str,
    delay_seconds: float = 0.1,
    dry_run: bool = False,
) -> dict:
    """Top-level load: nodes first, then edges. Accepts dicts or Pydantic models."""
    client = NeptuneClient(graph_id=neptune_graph_id, region=aws_region)

    if not dry_run and not client.is_configured:
        logger.warning("NEPTUNE_GRAPH_ID not configured — switching to dry-run mode")
        dry_run = True

    if not dry_run:
        logger.info("Pinging Neptune...")
        if not client.ping():
            logger.error("Neptune ping failed — aborting load")
            return {"error": "ping_failed", "node_stats": {}, "edge_stats": {}}

    node_stats = load_nodes(nodes, client, delay_seconds=delay_seconds, dry_run=dry_run)
    edge_stats = load_edges(edges, client, delay_seconds=delay_seconds, dry_run=dry_run)

    return {
        "dry_run": dry_run,
        "node_stats": node_stats,
        "edge_stats": edge_stats,
    }
