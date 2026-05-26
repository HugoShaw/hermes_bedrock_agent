#!/usr/bin/env python3
"""
Phase 3 v2: Batch import to Neptune Analytics using UNWIND for speed.
"""
import boto3, json, requests, time
from pathlib import Path
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

HOST = "g-wruqsayuf4.ap-northeast-1.neptune-graph.amazonaws.com"
REGION = "ap-northeast-1"
SERVICE = "neptune-graph"
OUTPUT_DIR = Path.home() / "projects/data/output"

def nq(cypher, params=None, timeout=120):
    sess = boto3.Session()
    creds = sess.get_credentials().get_frozen_credentials()
    body_dict = {"query": cypher}
    if params:
        body_dict["parameters"] = json.dumps(params)
    body = json.dumps(body_dict)
    url = f"https://{HOST}:8182/openCypher"
    req = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/json", "host": HOST})
    SigV4Auth(creds, SERVICE, REGION).add_auth(req)
    r = requests.post(url, headers=dict(req.headers), data=body, timeout=timeout, stream=True)
    raw = b"".join(r.iter_content(65536)).decode()
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {raw[:500]}")
    return json.loads(raw)

def safe_str(s, max_len=500):
    if s is None: return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").replace("\r", "")[:max_len]

print("=" * 60)
print("Phase 3 v2: Neptune Batch Import")
print("=" * 60)

# Verify connectivity
result = nq("MATCH (n) RETURN count(n) AS total")
print(f"Current nodes: {result['results'][0]['total']}")

# Clear if anything exists
result_n = result['results'][0]['total']
if result_n > 0:
    print("Clearing existing data...")
    nq("MATCH ()-[r]->() DELETE r", timeout=120)
    nq("MATCH (n) DELETE n", timeout=120)
    print("Cleared.")

# Load nodes
nodes = []
with open(OUTPUT_DIR / "nodes.jsonl") as f:
    for line in f:
        nodes.append(json.loads(line))
print(f"\nLoading {len(nodes)} nodes...")

# Import nodes one at a time but with simplified queries for speed
node_ok = 0
node_err = 0
t0 = time.time()

for i, node in enumerate(nodes):
    nid = safe_str(node["id"], 50)
    label = safe_str(node["label"], 200)
    ntype = safe_str(node["type"], 50)
    canonical = safe_str(node.get("canonical_name", node["label"]), 200)
    
    # Core properties 
    # Neptune Analytics requires a label on MERGE nodes
    safe_type = ntype if ntype.isalnum() else "Entity"
    stmt = f"MERGE (v:`{safe_type}` {{`~id`: '{nid}'}}) SET v.`label` = '{label}', v.`type` = '{ntype}', v.`canonical_name` = '{canonical}'"
    
    # Add optional props
    if node.get("description"):
        desc = safe_str(node["description"], 400)
        stmt += f", v.`description` = '{desc}'"
    if node.get("aliases"):
        aliases = safe_str(json.dumps(node["aliases"][:5], ensure_ascii=False), 400)
        stmt += f", v.`aliases` = '{aliases}'"
    if node.get("s3_path"):
        stmt += f", v.`s3_path` = '{safe_str(node['s3_path'], 300)}'"
    if node.get("category"):
        stmt += f", v.`category` = '{safe_str(node['category'], 50)}'"
    
    # Provenance (JSON string, trimmed)
    if node.get("provenance"):
        prov = node["provenance"][:3]
        for p in prov:
            p["source_text"] = p.get("source_text", "")[:200]
        prov_str = safe_str(json.dumps(prov, ensure_ascii=False), 3500)
        stmt += f", v.`provenance` = '{prov_str}'"
    
    # Embedding (JSON string)
    if node.get("embedding") and any(v != 0 for v in node.get("embedding", [])):
        emb_str = json.dumps([round(x, 6) for x in node["embedding"]])
        stmt += f", v.`embedding` = '{emb_str[:2500]}'"
    
    try:
        nq(stmt, timeout=30)
        node_ok += 1
    except Exception as e:
        node_err += 1
        if node_err <= 3:
            print(f"  ERR node [{ntype}] {label}: {str(e)[:120]}")
    
    if (i + 1) % 50 == 0:
        elapsed = time.time() - t0
        rate = (i + 1) / elapsed
        print(f"  Nodes: {i+1}/{len(nodes)} ({node_ok} ok, {node_err} err, {rate:.1f}/s)")

elapsed = time.time() - t0
print(f"  Nodes done: {node_ok} ok, {node_err} err in {elapsed:.1f}s")

# Import edges
edges = []
with open(OUTPUT_DIR / "edges.jsonl") as f:
    for line in f:
        edges.append(json.loads(line))
print(f"\nLoading {len(edges)} edges...")

edge_ok = 0
edge_err = 0
t1 = time.time()

for i, edge in enumerate(edges):
    from_id = safe_str(edge["from"], 50)
    to_id = safe_str(edge["to"], 50)
    rel_type = edge["type"].replace(" ", "_").replace("-", "_")
    
    stmt = f"MATCH (s {{`~id`: '{from_id}'}}), (o {{`~id`: '{to_id}'}}) MERGE (s)-[r:`{rel_type}`]->(o)"
    
    # Edge properties
    set_parts = []
    if edge.get("properties"):
        for k, v in edge["properties"].items():
            if v:
                set_parts.append(f"r.`{k}` = '{safe_str(v, 200)}'")
    
    # Edge provenance
    if edge.get("provenance"):
        prov = edge["provenance"][:3]
        for p in prov:
            p["source_text"] = p.get("source_text", "")[:200]
        prov_str = safe_str(json.dumps(prov, ensure_ascii=False), 3500)
        set_parts.append(f"r.`provenance` = '{prov_str}'")
    
    # Edge embedding
    if edge.get("embedding") and any(v != 0 for v in edge.get("embedding", [])):
        emb_str = json.dumps([round(x, 6) for x in edge["embedding"]])
        set_parts.append(f"r.`embedding` = '{emb_str[:2500]}'")
    
    if set_parts:
        stmt += " SET " + ", ".join(set_parts)
    
    try:
        nq(stmt, timeout=30)
        edge_ok += 1
    except Exception as e:
        edge_err += 1
        if edge_err <= 3:
            print(f"  ERR edge {rel_type} {from_id}->{to_id}: {str(e)[:120]}")
    
    if (i + 1) % 30 == 0:
        elapsed2 = time.time() - t1
        rate = (i + 1) / elapsed2
        print(f"  Edges: {i+1}/{len(edges)} ({edge_ok} ok, {edge_err} err, {rate:.1f}/s)")

elapsed2 = time.time() - t1
print(f"  Edges done: {edge_ok} ok, {edge_err} err in {elapsed2:.1f}s")

# Verify final state
print("\n--- Verification ---")
result = nq("MATCH (n) RETURN count(n) AS total")
print(f"  Total nodes: {result['results'][0]['total']}")

result = nq("MATCH ()-[r]->() RETURN count(r) AS total")
print(f"  Total edges: {result['results'][0]['total']}")

result = nq("MATCH (n) RETURN n.type AS type, count(*) AS cnt ORDER BY cnt DESC")
print("  Node types:")
for row in result['results']:
    print(f"    {str(row.get('type','')):20} {row['cnt']}")

result = nq("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS cnt ORDER BY cnt DESC")
print("  Edge types:")
for row in result['results']:
    print(f"    {str(row.get('t','')):20} {row['cnt']}")

total_time = time.time() - t0
print(f"\n{'='*60}")
print(f"Phase 3 Complete: {node_ok} nodes + {edge_ok} edges in {total_time:.0f}s")
print(f"{'='*60}")
