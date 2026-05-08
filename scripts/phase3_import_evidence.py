#!/usr/bin/env python3
"""
Phase 3: Neptune Reset & Import with Evidence Properties
=========================================================
1. Clears all data from Neptune Analytics instance
2. Imports nodes.jsonl (with embedding, evidence_source, evidence_text)
3. Imports edges.jsonl (with evidence_source, evidence_text)
4. Uses openCypher MERGE with SigV4 authentication
"""

import json, time, sys, re
import boto3, requests
from pathlib import Path
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

DATA_DIR   = Path.home() / "projects/data/output"
NODES_FILE = DATA_DIR / "nodes.jsonl"
EDGES_FILE = DATA_DIR / "edges.jsonl"
CYPHER_OUT = DATA_DIR / "import.cypher"

HOST    = "g-wruqsayuf4.ap-northeast-1.neptune-graph.amazonaws.com"
REGION  = "ap-northeast-1"
SERVICE = "neptune-graph"
BASE_URL = f"https://{HOST}:8182"

# ── Neptune Connection ─────────────────────────────────────────────────

session = boto3.Session()

def neptune_query(cypher: str, params: dict = None) -> dict:
    """Execute openCypher query with SigV4 signing."""
    creds = session.get_credentials()
    body_dict = {"query": cypher}
    if params:
        body_dict["parameters"] = params
    body = json.dumps(body_dict)
    url = f"{BASE_URL}/openCypher"

    req = AWSRequest(
        method="POST", url=url, data=body,
        headers={"Content-Type": "application/json", "host": HOST},
    )
    SigV4Auth(creds, SERVICE, REGION).add_auth(req)

    r = requests.post(url, headers=dict(req.headers), data=body,
                      timeout=60, stream=True)
    raw = b"".join(r.iter_content(65536)).decode("utf-8")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {raw[:300]}")
    return json.loads(raw)


def esc(s, maxlen=500):
    """Escape string for Cypher literal."""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").replace("\r", "").replace("\t", " ")[:maxlen]


# ── Phase 3a: Reset ───────────────────────────────────────────────────

def reset_graph():
    """Clear all data from Neptune instance."""
    print("Phase 3a: Resetting Neptune graph...")

    # Check current counts
    try:
        result = neptune_query("MATCH (n) RETURN count(n) AS total")
        current = result["results"][0]["total"]
        print(f"  Current node count: {current}")
    except Exception as e:
        print(f"  Could not get count: {e}")
        current = 0

    if current > 0:
        # Delete edges first, then nodes (avoid timeout)
        print("  Deleting all relationships...")
        neptune_query("MATCH ()-[r]->() DELETE r")
        time.sleep(1)
        print("  Deleting all nodes...")
        neptune_query("MATCH (n) DELETE n")
        time.sleep(1)

    # Verify
    result = neptune_query("MATCH (n) RETURN count(n) AS total")
    assert result["results"][0]["total"] == 0, "Reset failed!"
    print("  Graph reset complete (0 nodes, 0 edges)")


# ── Phase 3b: Import Nodes ────────────────────────────────────────────

def import_nodes():
    """Import nodes with evidence and embedding properties."""
    print(f"\nPhase 3b: Importing nodes from {NODES_FILE}...")
    cypher_lines = []

    nodes = []
    with open(NODES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            nodes.append(json.loads(line.strip()))

    total = len(nodes)
    success = 0
    errors = 0

    for i, node in enumerate(nodes):
        nid = esc(node["~id"])
        ntype = node.get("~label", node.get("type", "Entity"))
        # Sanitize label for Cypher (must be alphanumeric)
        graph_label = re.sub(r'[^a-zA-Z0-9]', '', ntype) or "Entity"

        name = esc(node.get("name", ""), 200)
        evidence_source = esc(node.get("evidence_source", ""), 300)
        evidence_text = esc(node.get("evidence_text", ""), 300)
        page_context = esc(node.get("page_context", ""), 200)

        # Build SET clause
        set_parts = [
            f"n.name = '{name}'",
            f"n.type = '{esc(ntype)}'",
            f"n.source_doc = '{evidence_source}'",
            f"n.evidence = '{evidence_text}'",
        ]

        if page_context:
            set_parts.append(f"n.page_context = '{page_context}'")
        if node.get("description"):
            set_parts.append(f"n.description = '{esc(node['description'], 300)}'")
        if node.get("category"):
            set_parts.append(f"n.category = '{esc(node['category'], 50)}'")
        if node.get("s3_path"):
            set_parts.append(f"n.s3_path = '{esc(node['s3_path'], 300)}'")
        if node.get("relative_path"):
            set_parts.append(f"n.relative_path = '{esc(node['relative_path'], 200)}'")

        # Store embedding as JSON string
        emb = node.get("embedding", [])
        if emb and any(v != 0.0 for v in emb):
            emb_str = json.dumps([round(x, 6) for x in emb[:256]])
            set_parts.append(f"n.embedding = '{esc(emb_str, 3000)}'")

        set_clause = ", ".join(set_parts)
        cypher = f"MERGE (n:`{graph_label}` {{`~id`: '{nid}'}}) SET {set_clause}"

        try:
            neptune_query(cypher)
            success += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [ERROR] Node {nid}: {str(e)[:100]}")

        cypher_lines.append(cypher + ";")

        if (i + 1) % 50 == 0:
            print(f"  Imported {i+1}/{total} nodes ({success} ok, {errors} errors)")

    print(f"  Nodes import complete: {success} success, {errors} errors")
    return cypher_lines


# ── Phase 3c: Import Edges ────────────────────────────────────────────

def import_edges():
    """Import edges with evidence properties."""
    print(f"\nPhase 3c: Importing edges from {EDGES_FILE}...")
    cypher_lines = []

    edges = []
    with open(EDGES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            edges.append(json.loads(line.strip()))

    total = len(edges)
    success = 0
    errors = 0

    for i, edge in enumerate(edges):
        src = esc(edge["~from"])
        tgt = esc(edge["~to"])
        pred = re.sub(r'[^a-zA-Z0-9_]', '_', edge.get("~label", "RELATED_TO"))
        evidence_source = esc(edge.get("evidence_source", ""), 300)
        evidence_text = esc(edge.get("evidence_text", ""), 300)

        set_parts = [
            f"r.source_doc = '{evidence_source}'",
            f"r.evidence = '{evidence_text}'",
        ]

        # Additional edge properties
        for k in ("trigger_condition", "frequency", "protocol", "confidence"):
            if edge.get(k):
                set_parts.append(f"r.`{k}` = '{esc(str(edge[k]), 200)}'")

        set_clause = ", ".join(set_parts)
        cypher = (
            f"MATCH (s {{`~id`: '{src}'}}), (o {{`~id`: '{tgt}'}}) "
            f"MERGE (s)-[r:`{pred}`]->(o) "
            f"SET {set_clause}"
        )

        try:
            neptune_query(cypher)
            success += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [ERROR] Edge {src}->{tgt}: {str(e)[:100]}")

        cypher_lines.append(cypher + ";")

        if (i + 1) % 50 == 0:
            print(f"  Imported {i+1}/{total} edges ({success} ok, {errors} errors)")

    print(f"  Edges import complete: {success} success, {errors} errors")
    return cypher_lines


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 3: Neptune Reset & Import with Evidence")
    print("=" * 60)
    print(f"  Neptune: {HOST}")
    print(f"  Nodes: {NODES_FILE}")
    print(f"  Edges: {EDGES_FILE}")
    print()

    # Test connectivity
    try:
        result = neptune_query("RETURN 1 AS ping")
        print("  Neptune connectivity: OK")
    except Exception as e:
        print(f"  Neptune connectivity FAILED: {e}")
        sys.exit(1)

    # Execute phases
    reset_graph()
    node_cyphers = import_nodes()
    edge_cyphers = import_edges()

    # Save Cypher script
    print(f"\nSaving import.cypher...")
    with open(CYPHER_OUT, "w", encoding="utf-8") as f:
        f.write("// Neptune Import Script - Generated by Phase 3\n")
        f.write(f"// Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"// Nodes: {len(node_cyphers)}, Edges: {len(edge_cyphers)}\n\n")
        f.write("// === NODES ===\n")
        for c in node_cyphers:
            f.write(c + "\n")
        f.write("\n// === EDGES ===\n")
        for c in edge_cyphers:
            f.write(c + "\n")

    cypher_size = CYPHER_OUT.stat().st_size / 1024
    print(f"  import.cypher: {cypher_size:.1f} KB")

    # Final verification
    print(f"\n{'='*60}")
    print("Final Verification:")
    result = neptune_query("MATCH (n) RETURN count(n) AS total")
    print(f"  Total nodes: {result['results'][0]['total']}")
    result = neptune_query("MATCH ()-[r]->() RETURN count(r) AS total")
    print(f"  Total edges: {result['results'][0]['total']}")

    # Type distribution
    result = neptune_query(
        "MATCH (n) RETURN n.type AS type, count(*) AS cnt ORDER BY cnt DESC LIMIT 15")
    print(f"\n  Node type distribution:")
    for row in result["results"]:
        print(f"    {row['type']:20s} {row['cnt']:4d}")

    result = neptune_query(
        "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY cnt DESC LIMIT 15")
    print(f"\n  Edge type distribution:")
    for row in result["results"]:
        print(f"    {row['rel']:20s} {row['cnt']:4d}")


if __name__ == "__main__":
    main()
