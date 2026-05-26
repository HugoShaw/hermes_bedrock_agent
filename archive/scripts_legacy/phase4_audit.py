#!/usr/bin/env python3
"""
Phase 4: Quality Audit & Topology Analysis
- Basic stats
- Longest cross-system data flow paths
- Orphan detection
- Evidence audit (random 5 cross-system relations)
"""
import boto3, json, requests, random
from pathlib import Path
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

HOST = "g-wruqsayuf4.ap-northeast-1.neptune-graph.amazonaws.com"
REGION = "ap-northeast-1"
OUTPUT_DIR = Path.home() / "projects/data/output"

def nq(cypher, timeout=60):
    sess = boto3.Session()
    creds = sess.get_credentials().get_frozen_credentials()
    body = json.dumps({"query": cypher})
    url = f"https://{HOST}:8182/openCypher"
    req = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/json", "host": HOST})
    SigV4Auth(creds, "neptune-graph", REGION).add_auth(req)
    r = requests.post(url, headers=dict(req.headers), data=body, timeout=timeout, stream=True)
    raw = b"".join(r.iter_content(65536)).decode()
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {raw[:300]}")
    return json.loads(raw)

print("=" * 70)
print("  PHASE 4: QUALITY AUDIT & TOPOLOGY ANALYSIS")
print("=" * 70)

# ================================================================
# 1. Basic Statistics
# ================================================================
print("\n" + "=" * 70)
print("  1. BASIC STATISTICS")
print("=" * 70)

r = nq("MATCH (n) RETURN count(n) AS total")
total_nodes = r["results"][0]["total"]
print(f"  Total Nodes: {total_nodes}")

r = nq("MATCH ()-[r]->() RETURN count(r) AS total")
total_edges = r["results"][0]["total"]
print(f"  Total Edges: {total_edges}")

r = nq("MATCH (n) RETURN n.type AS type, count(*) AS cnt ORDER BY cnt DESC")
print("\n  Node Type Distribution:")
for row in r["results"]:
    print(f"    {str(row.get('type','')):20} {row['cnt']:>5}")

r = nq("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS cnt ORDER BY cnt DESC")
print("\n  Edge Type Distribution:")
for row in r["results"]:
    print(f"    {str(row.get('t','')):20} {row['cnt']:>5}")

# ================================================================
# 2. Cross-System Data Flow Path Analysis
# ================================================================
print("\n" + "=" * 70)
print("  2. CROSS-SYSTEM DATA FLOW PATHS (Longest 3)")
print("=" * 70)

# Find FLOWS_TO paths between System nodes
r = nq("""
MATCH path = (a:System)-[:FLOWS_TO*1..5]->(b:System)
WHERE a <> b
RETURN [n IN nodes(path) | n.label] AS chain, length(path) AS hops
ORDER BY hops DESC
LIMIT 10
""")

if r["results"]:
    seen = set()
    count = 0
    for row in r["results"]:
        chain = row["chain"]
        chain_key = "->".join(chain)
        if chain_key not in seen:
            seen.add(chain_key)
            count += 1
            print(f"\n  Path {count}: ({row['hops']} hops)")
            print(f"    {' -> '.join(chain)}")
            if count >= 3:
                break
else:
    print("  No multi-hop system paths found. Trying broader search...")
    
# Also look at data flow through tables
r = nq("""
MATCH (a:System)<-[:BELONGS_TO]-(t1:Table)-[:FLOWS_TO]->(t2:Table)-[:BELONGS_TO]->(b:System)
WHERE a <> b
RETURN a.label AS sys_from, t1.label AS tbl_from, t2.label AS tbl_to, b.label AS sys_to
LIMIT 10
""")

if r["results"]:
    print("\n  Table-level cross-system data flows:")
    for row in r["results"]:
        print(f"    [{row['sys_from']}] {row['tbl_from']} -> {row['tbl_to']} [{row['sys_to']}]")

# Extended: System->Table->View chains
r = nq("""
MATCH (s:System)<-[:BELONGS_TO]-(t:Table)<-[:AGGREGATES]-(v:View)
RETURN s.label AS system, t.label AS table, v.label AS view
ORDER BY s.label
LIMIT 20
""")

if r["results"]:
    print("\n  System -> Table -> View lineage:")
    for row in r["results"]:
        print(f"    [{row['system']}] {row['table']} <- aggregated by -> {row['view']}")

# System-to-system flows (direct)
r = nq("""
MATCH (a:System)-[r:FLOWS_TO|TRANSFERS_VIA]->(b:System)
RETURN a.label AS from_sys, type(r) AS rel, b.label AS to_sys, r.protocol AS protocol, r.trigger_condition AS trigger
""")

if r["results"]:
    print("\n  Direct System-to-System flows:")
    for row in r["results"]:
        print(f"    {row['from_sys']:10} --[{row['rel']}:{row.get('protocol','?')}]--> {row['to_sys']}")
        if row.get("trigger"):
            print(f"      Trigger: {row['trigger']}")

# ================================================================
# 3. Orphan (Isolated) Node Detection
# ================================================================
print("\n" + "=" * 70)
print("  3. ORPHAN NODE DETECTION")
print("=" * 70)

r = nq("""
MATCH (n)
WHERE NOT (n)--()
RETURN n.type AS type, n.label AS label
ORDER BY n.type, n.label
""")

if r["results"]:
    print(f"  Found {len(r['results'])} isolated nodes:")
    by_type = {}
    for row in r["results"]:
        t = row.get("type", "Unknown")
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(row.get("label", "?"))
    for t, labels in sorted(by_type.items()):
        print(f"\n    {t} ({len(labels)}):")
        for l in labels[:10]:
            print(f"      - {l}")
        if len(labels) > 10:
            print(f"      ... and {len(labels)-10} more")
else:
    print("  No isolated nodes found. All nodes have at least one connection.")

# ================================================================
# 4. Evidence Audit (5 random cross-system relations)
# ================================================================
print("\n" + "=" * 70)
print("  4. EVIDENCE AUDIT (Cross-System Relations)")
print("=" * 70)

r = nq("""
MATCH (a)-[r]->(b)
WHERE r.provenance IS NOT NULL
AND a.type <> 'Document' AND b.type <> 'Document'
RETURN a.label AS from_label, a.type AS from_type, 
       type(r) AS rel_type, b.label AS to_label, b.type AS to_type,
       r.provenance AS provenance, r.trigger_condition AS trigger, r.protocol AS protocol
LIMIT 30
""")

if r["results"]:
    # Pick 5 random
    audit_sample = random.sample(r["results"], min(5, len(r["results"])))
    
    for i, row in enumerate(audit_sample, 1):
        print(f"\n  --- Audit Sample {i} ---")
        print(f"  Relation: [{row['from_type']}] {row['from_label']} --[{row['rel_type']}]--> [{row['to_type']}] {row['to_label']}")
        print(f"  Protocol: {row.get('protocol', 'N/A')}")
        print(f"  Trigger:  {row.get('trigger', 'N/A')}")
        
        # Parse provenance
        prov_str = row.get("provenance", "")
        if prov_str:
            try:
                provs = json.loads(prov_str)
                for j, p in enumerate(provs[:2]):
                    print(f"  Evidence [{j+1}]:")
                    print(f"    Source:     {p.get('source_type', '?')}")
                    print(f"    File:       {p.get('source_path', '?')}")
                    print(f"    Chunk ID:   {p.get('source_chunk_id', '?')}")
                    print(f"    Confidence: {p.get('confidence', '?')}")
                    src_text = p.get("source_text", "")
                    if src_text:
                        print(f"    Text:       {src_text[:200]}")
            except:
                print(f"  Provenance: {prov_str[:200]}")

# ================================================================
# 5. Provenance Coverage Analysis (from local JSONL)
# ================================================================
print("\n" + "=" * 70)
print("  5. PROVENANCE COVERAGE ANALYSIS")
print("=" * 70)

nodes = []
with open(OUTPUT_DIR / "nodes.jsonl") as f:
    for line in f:
        nodes.append(json.loads(line))
edges = []
with open(OUTPUT_DIR / "edges.jsonl") as f:
    for line in f:
        edges.append(json.loads(line))

nodes_with_prov = sum(1 for n in nodes if n.get("provenance") and len(n["provenance"]) > 0)
edges_with_prov = sum(1 for e in edges if e.get("provenance") and len(e["provenance"]) > 0)
nodes_with_embed = sum(1 for n in nodes if n.get("embedding") and any(v != 0 for v in n.get("embedding", [])))
edges_with_embed = sum(1 for e in edges if e.get("embedding") and any(v != 0 for v in e.get("embedding", [])))

print(f"  Nodes with provenance: {nodes_with_prov}/{len(nodes)} ({100*nodes_with_prov/len(nodes):.1f}%)")
print(f"  Edges with provenance: {edges_with_prov}/{len(edges)} ({100*edges_with_prov/len(edges):.1f}%)")
print(f"  Nodes with embedding:  {nodes_with_embed}/{len(nodes)} ({100*nodes_with_embed/len(nodes):.1f}%)")
print(f"  Edges with embedding:  {edges_with_embed}/{len(edges)} ({100*edges_with_embed/len(edges):.1f}%)")

# Source type distribution
from collections import Counter
source_types = Counter()
for n in nodes:
    for p in n.get("provenance", []):
        source_types[p.get("source_type", "unknown")] += 1
for e in edges:
    for p in e.get("provenance", []):
        source_types[p.get("source_type", "unknown")] += 1

print(f"\n  Provenance source type distribution:")
for st, cnt in source_types.most_common():
    print(f"    {st:20} {cnt:>5}")

# ================================================================
# 6. Sample Node Provenance (3 nodes)
# ================================================================
print("\n" + "=" * 70)
print("  6. SAMPLE NODE PROVENANCE (3 nodes)")
print("=" * 70)

# Pick interesting non-Document nodes
interesting = [n for n in nodes if n["type"] in ("System", "Table", "Controller", "Service") and n.get("provenance")]
sample_nodes = random.sample(interesting, min(3, len(interesting)))

for i, node in enumerate(sample_nodes, 1):
    print(f"\n  --- Node Sample {i} ---")
    print(f"  ID:     {node['id']}")
    print(f"  Label:  {node['label']}")
    print(f"  Type:   {node['type']}")
    print(f"  Canon:  {node.get('canonical_name', 'N/A')}")
    for j, p in enumerate(node.get("provenance", [])[:2]):
        print(f"  Prov [{j+1}]:")
        print(f"    Source:     {p.get('source_type', '?')}")
        print(f"    File:       {p.get('source_path', '?')}")
        print(f"    Chunk ID:   {p.get('source_chunk_id', '?')}")
        print(f"    Confidence: {p.get('confidence', '?')}")
        print(f"    Text:       {p.get('source_text', '')[:200]}")

# ================================================================
# 7. Sample Edge Provenance (3 edges)
# ================================================================
print("\n" + "=" * 70)
print("  7. SAMPLE EDGE PROVENANCE (3 edges)")
print("=" * 70)

interesting_edges = [e for e in edges if e["type"] in ("FLOWS_TO", "ACCESSES", "AGGREGATES", "TRANSFORMS") and e.get("provenance")]
sample_edges = random.sample(interesting_edges, min(3, len(interesting_edges)))

# Build node lookup for labels
node_map = {n["id"]: n for n in nodes}

for i, edge in enumerate(sample_edges, 1):
    from_node = node_map.get(edge["from"], {})
    to_node = node_map.get(edge["to"], {})
    print(f"\n  --- Edge Sample {i} ---")
    print(f"  From:   [{from_node.get('type','?')}] {from_node.get('label','?')}")
    print(f"  To:     [{to_node.get('type','?')}] {to_node.get('label','?')}")
    print(f"  Type:   {edge['type']}")
    props = edge.get("properties", {})
    if props.get("trigger_condition"):
        print(f"  Trigger:  {props['trigger_condition']}")
    if props.get("frequency"):
        print(f"  Freq:     {props['frequency']}")
    if props.get("protocol"):
        print(f"  Protocol: {props['protocol']}")
    for j, p in enumerate(edge.get("provenance", [])[:2]):
        print(f"  Prov [{j+1}]:")
        print(f"    Source:     {p.get('source_type', '?')}")
        print(f"    File:       {p.get('source_path', '?')}")
        print(f"    Chunk ID:   {p.get('source_chunk_id', '?')}")
        print(f"    Confidence: {p.get('confidence', '?')}")
        print(f"    Text:       {p.get('source_text', '')[:250]}")

# ================================================================
# Summary
# ================================================================
print("\n" + "=" * 70)
print("  AUDIT SUMMARY")
print("=" * 70)
print(f"  Graph: {total_nodes} nodes, {total_edges} edges")
print(f"  Provenance: {nodes_with_prov}/{len(nodes)} nodes (100%), {edges_with_prov}/{len(edges)} edges (100%)")
print(f"  Embeddings: {nodes_with_embed} nodes, {edges_with_embed} edges")
print(f"  Cross-system flows: {len([e for e in edges if e['type'] == 'FLOWS_TO'])}")
print(f"  Table lineage relations: {len([e for e in edges if e['type'] in ('AGGREGATES', 'TRANSFORMS', 'ACCESSES')])}")
print("=" * 70)
