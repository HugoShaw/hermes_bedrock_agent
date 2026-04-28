"""Graph traversal helpers for GraphRAG query expansion."""

from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path

from hermes_bedrock_agent.graphrag import db as db_mod


def expand_from_nodes(
    db_path: Path,
    node_ids: list[str],
    hops: int = 1,
) -> tuple[dict[str, dict], list[dict]]:
    """BFS-expand *node_ids* up to *hops* hops in the graph.

    Returns ``(nodes_dict, edges_list)`` where:

    - ``nodes_dict``: mapping of node_id → ``{id, type, data}`` for every node
      encountered (seeds + neighbours).
    - ``edges_list``: all edges traversed (as plain dicts).
    """
    db_mod.init_db(db_path)

    with db_mod.get_connection(db_path) as conn:
        nodes: dict[str, dict] = {}
        edges_seen: set[str] = set()
        edges_out: list[dict] = []

        frontier = set(node_ids)
        visited = set(node_ids)

        for _ in range(hops):
            next_frontier: set[str] = set()
            for nid in frontier:
                edge_rows = db_mod.get_edges_for_node(conn, nid)
                for edge in edge_rows:
                    eid = edge["id"]
                    if eid not in edges_seen:
                        edges_seen.add(eid)
                        edges_out.append(dict(edge))

                    neighbour = edge["dst_id"] if edge["src_id"] == nid else edge["src_id"]
                    if neighbour not in visited:
                        visited.add(neighbour)
                        next_frontier.add(neighbour)
            frontier = next_frontier

        # Resolve node data for all visited IDs
        for nid in visited:
            row = _resolve_node(conn, nid)
            if row:
                nodes[nid] = row

    return nodes, edges_out


def _resolve_node(conn: sqlite3.Connection, node_id: str) -> dict | None:
    """Look up a node in chunks, entities, or documents by its id."""
    for table, ntype in (("gr_chunks", "chunk"), ("gr_entities", "entity"), ("gr_documents", "document")):
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (node_id,)).fetchone()
        if row:
            return {"id": node_id, "type": ntype, "data": dict(row)}
    return None


def get_context_for_chunks(
    db_path: Path,
    chunk_ids: list[str],
    expand_hops: int = 1,
) -> dict:
    """Return enriched context for a set of chunk IDs.

    Fetches chunk text, their parent documents, and neighbouring entities
    via graph expansion. Returns a structured dict ready for display or LLM
    context assembly.
    """
    db_mod.init_db(db_path)

    with db_mod.get_connection(db_path) as conn:
        chunks = []
        doc_ids: set[str] = set()
        for cid in chunk_ids:
            row = conn.execute("SELECT * FROM gr_chunks WHERE id = ?", (cid,)).fetchone()
            if row:
                chunks.append(dict(row))
                doc_ids.add(row["doc_id"])

        documents = {}
        for did in doc_ids:
            row = conn.execute("SELECT * FROM gr_documents WHERE id = ?", (did,)).fetchone()
            if row:
                documents[did] = dict(row)

    nodes, edges = expand_from_nodes(db_path, chunk_ids, hops=expand_hops)

    entities = {nid: n for nid, n in nodes.items() if n["type"] == "entity"}
    neighbour_chunks = {nid: n for nid, n in nodes.items() if n["type"] == "chunk" and nid not in chunk_ids}

    return {
        "chunks": chunks,
        "documents": documents,
        "entities": entities,
        "neighbour_chunks": neighbour_chunks,
        "edges": edges,
    }
