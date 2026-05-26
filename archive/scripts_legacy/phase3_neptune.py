#!/usr/bin/env python3
"""
Phase 3: Reset Neptune Analytics and import nodes/edges with provenance.
Uses HTTP REST on port 8182 with SigV4Auth.
"""
import boto3
import json
import time
import requests
from pathlib import Path
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

# Config
GRAPH_ID = "g-wruqsayuf4"
HOST = f"{GRAPH_ID}.ap-northeast-1.neptune-graph.amazonaws.com"
REGION = "ap-northeast-1"
SERVICE = "neptune-graph"
OUTPUT_DIR = Path.home() / "projects/data/output"

# Load data
nodes_path = OUTPUT_DIR / "nodes.jsonl"
edges_path = OUTPUT_DIR / "edges.jsonl"

def neptune_query(cypher: str, parameters: dict = None, timeout: int = 60) -> dict:
    """Execute openCypher query against Neptune Analytics."""
    sess = boto3.Session()
    creds = sess.get_credentials().get_frozen_credentials()
    
    body_dict = {"query": cypher}
    if parameters:
        body_dict["parameters"] = json.dumps(parameters)
    body = json.dumps(body_dict)
    url = f"https://{HOST}:8182/openCypher"
    
    req = AWSRequest(
        method="POST", url=url, data=body,
        headers={"Content-Type": "application/json", "host": HOST},
    )
    SigV4Auth(creds, SERVICE, REGION).add_auth(req)
    
    r = requests.post(url, headers=dict(req.headers), data=body,
                      timeout=timeout, stream=True)
    raw = b"".join(r.iter_content(65536)).decode()
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {raw[:500]}")
    return json.loads(raw)

def neptune_query_retry(cypher: str, parameters: dict = None, max_attempts: int = 3) -> dict:
    """Execute with retry on throttling."""
    for attempt in range(max_attempts):
        try:
            return neptune_query(cypher, parameters)
        except RuntimeError as e:
            if "429" in str(e) or "Throttl" in str(e):
                time.sleep(2 ** attempt)
            elif "ConflictException" in str(e):
                return {"results": []}
            else:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(1)
        except requests.exceptions.Timeout:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2)
    return {"results": []}

print("=" * 60)
print("Phase 3: Neptune Database Reset & Atomic Import")
print("=" * 60)

# === Step 1: Test connectivity ===
print("\n--- Step 1: Testing Neptune connectivity ---")
try:
    result = neptune_query("MATCH (n) RETURN count(n) AS total")
    print(f"  Connected! Current node count: {result['results'][0]['total']}")
except Exception as e:
    print(f"  ERROR: {e}")
    print("  Attempting alternative connection...")
    raise

# === Step 2: Clear database ===
print("\n--- Step 2: Clearing database ---")
try:
    # Delete all relationships first
    neptune_query("MATCH ()-[r]->() DELETE r", timeout=120)
    print("  Deleted all relationships")
    
    # Delete all nodes
    neptune_query("MATCH (n) DELETE n", timeout=120)
    print("  Deleted all nodes")
    
    # Verify
    result = neptune_query("MATCH (n) RETURN count(n) AS total")
    print(f"  Verified: {result['results'][0]['total']} nodes remaining")
except Exception as e:
    print(f"  Warning during clear: {e}")

# === Step 3: Import nodes ===
print("\n--- Step 3: Importing nodes ---")

nodes = []
with open(nodes_path, 'r', encoding='utf-8') as fp:
    for line in fp:
        nodes.append(json.loads(line))

print(f"  Loading {len(nodes)} nodes...")

# Batch import nodes - using MERGE for idempotency
node_success = 0
node_errors = 0

for i, node in enumerate(nodes):
    nid = node["id"].replace("'", "\\'")
    label = node["label"].replace("'", "\\'").replace("\\", "\\\\")[:200]
    ntype = node["type"].replace("'", "\\'")
    canonical = node.get("canonical_name", label).replace("'", "\\'")[:200]
    
    # Build SET clause with properties
    props = {
        "node_id": nid,
        "label": label,
        "type": ntype,
        "canonical_name": canonical,
    }
    
    if node.get("description"):
        props["description"] = node["description"].replace("'", "\\'")[:500]
    if node.get("category"):
        props["category"] = node["category"]
    if node.get("s3_path"):
        props["s3_path"] = node["s3_path"]
    if node.get("aliases"):
        props["aliases"] = json.dumps(node["aliases"][:10], ensure_ascii=False)[:500]
    
    # Store provenance as JSON string
    if node.get("provenance"):
        # Limit provenance to first 3 entries for storage
        prov_data = node["provenance"][:3]
        for p in prov_data:
            p["source_text"] = p.get("source_text", "")[:300]
        props["provenance"] = json.dumps(prov_data, ensure_ascii=False)[:4000]
    
    # Store embedding as JSON string
    if node.get("embedding") and any(v != 0 for v in node.get("embedding", [])):
        props["embedding"] = json.dumps(node["embedding"])[:3000]
    
    # Build MERGE statement
    set_parts = []
    for k, v in props.items():
        if isinstance(v, (int, float)):
            set_parts.append(f"v.`{k}` = {v}")
        else:
            safe_v = str(v).replace("'", "\\'").replace("\n", " ").replace("\r", "")
            set_parts.append(f"v.`{k}` = '{safe_v}'")
    
    set_clause = ", ".join(set_parts)
    stmt = f"MERGE (v {{`~id`: '{nid}'}}) SET {set_clause}"
    
    try:
        neptune_query_retry(stmt)
        node_success += 1
    except Exception as e:
        node_errors += 1
        if node_errors <= 5:
            print(f"  Error on node {nid} ({label}): {str(e)[:100]}")
    
    if (i + 1) % 50 == 0:
        print(f"  Progress: {i+1}/{len(nodes)} ({node_success} ok, {node_errors} err)")
        time.sleep(0.2)

print(f"  Nodes imported: {node_success} success, {node_errors} errors")

# === Step 4: Import edges ===
print("\n--- Step 4: Importing edges ---")

edges = []
with open(edges_path, 'r', encoding='utf-8') as fp:
    for line in fp:
        edges.append(json.loads(line))

print(f"  Loading {len(edges)} edges...")

edge_success = 0
edge_errors = 0

for i, edge in enumerate(edges):
    from_id = edge["from"].replace("'", "\\'")
    to_id = edge["to"].replace("'", "\\'")
    rel_type = edge["type"].replace(" ", "_").replace("-", "_")
    
    # Build properties
    props_parts = []
    
    if edge.get("properties"):
        for k, v in edge["properties"].items():
            if v:
                safe_v = str(v).replace("'", "\\'").replace("\n", " ")[:200]
                props_parts.append(f"r.`{k}` = '{safe_v}'")
    
    # Store provenance on edge
    if edge.get("provenance"):
        prov_data = edge["provenance"][:3]
        for p in prov_data:
            p["source_text"] = p.get("source_text", "")[:300]
        prov_json = json.dumps(prov_data, ensure_ascii=False)[:4000]
        prov_json = prov_json.replace("'", "\\'").replace("\n", " ")
        props_parts.append(f"r.`provenance` = '{prov_json}'")
    
    # Store edge embedding
    if edge.get("embedding") and any(v != 0 for v in edge.get("embedding", [])):
        emb_json = json.dumps(edge["embedding"])[:3000]
        props_parts.append(f"r.`embedding` = '{emb_json}'")
    
    set_clause = ", ".join(props_parts) if props_parts else ""
    set_stmt = f" SET {set_clause}" if set_clause else ""
    
    stmt = (
        f"MATCH (s {{`~id`: '{from_id}'}}), (o {{`~id`: '{to_id}'}}) "
        f"MERGE (s)-[r:`{rel_type}`]->(o)"
        f"{set_stmt}"
    )
    
    try:
        neptune_query_retry(stmt)
        edge_success += 1
    except Exception as e:
        edge_errors += 1
        if edge_errors <= 5:
            print(f"  Error on edge {from_id}->{to_id}: {str(e)[:100]}")
    
    if (i + 1) % 30 == 0:
        print(f"  Progress: {i+1}/{len(edges)} ({edge_success} ok, {edge_errors} err)")
        time.sleep(0.2)

print(f"  Edges imported: {edge_success} success, {edge_errors} errors")

# === Step 5: Verify ===
print("\n--- Step 5: Verification ---")
try:
    result = neptune_query("MATCH (n) RETURN count(n) AS total")
    print(f"  Total nodes in Neptune: {result['results'][0]['total']}")
    
    result = neptune_query("MATCH ()-[r]->() RETURN count(r) AS total")
    print(f"  Total edges in Neptune: {result['results'][0]['total']}")
    
    result = neptune_query("MATCH (n) RETURN n.type AS type, count(*) AS cnt ORDER BY cnt DESC")
    print("  Node types:")
    for row in result['results']:
        print(f"    {row['type']:20} {row['cnt']}")
    
    result = neptune_query("MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS cnt ORDER BY cnt DESC")
    print("  Edge types:")
    for row in result['results']:
        print(f"    {row['rel_type']:20} {row['cnt']}")
        
except Exception as e:
    print(f"  Verification error: {e}")

print(f"\n{'='*60}")
print(f"Phase 3 Complete!")
print(f"  Nodes: {node_success} imported")
print(f"  Edges: {edge_success} imported")
print(f"{'='*60}")
