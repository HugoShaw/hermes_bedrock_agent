#!/usr/bin/env python3
"""
Phase 2: Generate embeddings with Bedrock Titan, normalize entities, produce nodes.jsonl and edges.jsonl
"""
import boto3
import json
import time
import hashlib
import re
from pathlib import Path
from collections import defaultdict

# Config
REGION = "ap-northeast-1"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 256
OUTPUT_DIR = Path.home() / "projects/data/output"
MAX_EMBED_TEXT = 7000  # Titan v2 token limit safety

# Load Phase 1 results
entities = {e["id"]: e for e in json.loads((OUTPUT_DIR / "entities_raw.json").read_text())}
relations = json.loads((OUTPUT_DIR / "relations_raw.json").read_text())

print("=" * 60)
print("Phase 2: Embedding Generation & Entity Normalization")
print("=" * 60)
print(f"  Entities: {len(entities)}")
print(f"  Relations: {len(relations)}")

# === Step 1: Entity Normalization ===
print("\n--- Step 1: Entity Normalization ---")

# Canonical name normalization rules
ALIAS_MAP = {
    "IMAPS": ["iMaps", "imaps", "IMAPS"],
    "MDW": ["MDW", "Murata Data Warehouse", "murata_mdw"],
    "HDS": ["HDS", "hds", "HDS中间件"],
    "HULFT": ["HULFT", "hulft", "HULFT Transfer"],
    "SUN": ["SUN", "SUN系统", "SUN accounting"],
    "MURATA": ["MURATA", "Murata", "murata", "村田"],
    "ERP": ["ERP", "erp", "企业资源计划"],
    "ORACLE": ["ORACLE", "Oracle", "oracle"],
}

# Normalize system names
normalized_count = 0
for eid, entity in entities.items():
    if entity["type"] == "System":
        label = entity["label"].upper()
        for canonical, aliases in ALIAS_MAP.items():
            if label == canonical or entity["label"] in aliases:
                entity["canonical_name"] = canonical
                entity["aliases"] = list(set(entity.get("aliases", []) + aliases))
                normalized_count += 1
                break
    
    # Java class canonical names
    elif entity["type"] in ("JavaClass", "Controller", "Service", "DataAccess", "Entity", "Interface"):
        # Strip common suffixes for canonical grouping
        name = entity["label"]
        canonical = name
        for sfx in ["Action", "ServiceImpl", "DaoImpl", "Service", "DaoI", "Dao"]:
            if name.endswith(sfx) and len(name) > len(sfx):
                canonical = name[:-len(sfx)]
                break
        entity["canonical_name"] = canonical
        entity["aliases"] = list(set(entity.get("aliases", []) + [name]))
    
    # Table canonical: uppercase
    elif entity["type"] == "Table":
        entity["canonical_name"] = entity["label"].upper()

print(f"  Normalized {normalized_count} system entities")

# Deduplicate provenance per entity
for eid, entity in entities.items():
    if "provenance" in entity:
        seen_texts = set()
        deduped = []
        for p in entity["provenance"]:
            key = p.get("source_text", "")[:100]
            if key not in seen_texts:
                seen_texts.add(key)
                deduped.append(p)
        entity["provenance"] = deduped

# === Step 2: Generate Embeddings ===
print("\n--- Step 2: Generating Embeddings ---")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

def get_embedding(text: str) -> list:
    """Get embedding from Bedrock Titan."""
    if not text or len(text.strip()) < 5:
        return [0.0] * EMBED_DIM
    
    # Truncate to safe limit
    text = text[:MAX_EMBED_TEXT]
    
    body = json.dumps({
        "inputText": text,
        "dimensions": EMBED_DIM,
        "normalize": True
    })
    
    resp = bedrock.invoke_model(
        modelId=EMBED_MODEL,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    result = json.loads(resp["body"].read())
    return result["embedding"]

# Build embedding text for each non-Document entity (excluding provenance!)
entities_to_embed = []
for eid, entity in entities.items():
    if entity["type"] == "Document":
        continue  # Skip document nodes for embedding (too many, low value)
    entities_to_embed.append(eid)

print(f"  Entities to embed: {len(entities_to_embed)}")

embed_count = 0
embed_errors = 0
batch_start = time.time()

for i, eid in enumerate(entities_to_embed):
    entity = entities[eid]
    
    # Build embedding text (NO provenance!)
    parts = [
        f"Type: {entity['type']}",
        f"Name: {entity['label']}",
        f"Canonical: {entity.get('canonical_name', entity['label'])}",
    ]
    if entity.get("description"):
        parts.append(f"Description: {entity['description']}")
    if entity.get("aliases"):
        parts.append(f"Aliases: {', '.join(entity['aliases'][:5])}")
    
    embed_text = "\n".join(parts)
    
    try:
        embedding = get_embedding(embed_text)
        entity["embedding"] = embedding
        embed_count += 1
    except Exception as e:
        if "ThrottlingException" in str(e):
            time.sleep(2)
            try:
                embedding = get_embedding(embed_text)
                entity["embedding"] = embedding
                embed_count += 1
            except Exception as e2:
                entity["embedding"] = [0.0] * EMBED_DIM
                embed_errors += 1
        else:
            entity["embedding"] = [0.0] * EMBED_DIM
            embed_errors += 1
    
    # Throttle
    if (i + 1) % 10 == 0:
        time.sleep(0.3)
        elapsed = time.time() - batch_start
        rate = (i + 1) / elapsed
        print(f"  Progress: {i+1}/{len(entities_to_embed)} ({rate:.1f}/s)")

print(f"  Embedded: {embed_count} entities, {embed_errors} errors")

# === Step 3: Generate Edge Embeddings (key relations only) ===
print("\n--- Step 3: Generating Edge Embeddings ---")

edge_embed_count = 0
for i, rel in enumerate(relations):
    # Build embedding text for edge (NO provenance!)
    from_entity = entities.get(rel["from"], {})
    to_entity = entities.get(rel["to"], {})
    
    parts = [
        f"Relationship: {rel['type']}",
        f"From: {from_entity.get('label', 'unknown')} ({from_entity.get('type', '')})",
        f"To: {to_entity.get('label', 'unknown')} ({to_entity.get('type', '')})",
    ]
    if rel.get("properties"):
        props = rel["properties"]
        if props.get("trigger_condition"):
            parts.append(f"Trigger: {props['trigger_condition']}")
        if props.get("protocol"):
            parts.append(f"Protocol: {props['protocol']}")
    
    embed_text = "\n".join(parts)
    
    try:
        rel["embedding"] = get_embedding(embed_text)
        edge_embed_count += 1
    except Exception as e:
        rel["embedding"] = [0.0] * EMBED_DIM
    
    if (i + 1) % 20 == 0:
        time.sleep(0.3)

print(f"  Embedded: {edge_embed_count} edges")

# === Step 4: Generate nodes.jsonl and edges.jsonl ===
print("\n--- Step 4: Generating JSONL output ---")

nodes_path = OUTPUT_DIR / "nodes.jsonl"
edges_path = OUTPUT_DIR / "edges.jsonl"

# Write nodes
with open(nodes_path, 'w', encoding='utf-8') as fp:
    for entity in entities.values():
        node = {
            "id": entity["id"],
            "label": entity["label"],
            "type": entity["type"],
            "canonical_name": entity.get("canonical_name", entity["label"]),
            "aliases": entity.get("aliases", []),
            "provenance": entity.get("provenance", []),
        }
        if entity.get("description"):
            node["description"] = entity["description"]
        if entity.get("embedding"):
            node["embedding"] = entity["embedding"]
        if entity.get("category"):
            node["category"] = entity["category"]
        if entity.get("s3_path"):
            node["s3_path"] = entity["s3_path"]
        if entity.get("relative_path"):
            node["relative_path"] = entity["relative_path"]
        
        fp.write(json.dumps(node, ensure_ascii=False) + "\n")

# Write edges
with open(edges_path, 'w', encoding='utf-8') as fp:
    for rel in relations:
        edge = {
            "from": rel["from"],
            "to": rel["to"],
            "type": rel["type"],
            "properties": rel.get("properties", {}),
            "provenance": rel.get("provenance", []),
        }
        if rel.get("embedding"):
            edge["embedding"] = rel["embedding"]
        
        fp.write(json.dumps(edge, ensure_ascii=False) + "\n")

# Stats
nodes_size = nodes_path.stat().st_size / 1024
edges_size = edges_path.stat().st_size / 1024

print(f"\n{'='*60}")
print(f"Phase 2 Complete!")
print(f"  nodes.jsonl: {nodes_path} ({nodes_size:.1f} KB)")
print(f"  edges.jsonl: {edges_path} ({edges_size:.1f} KB)")
print(f"  Total nodes: {len(entities)}")
print(f"  Total edges: {len(relations)}")
print(f"  Nodes with embeddings: {sum(1 for e in entities.values() if e.get('embedding') and any(v != 0 for v in e.get('embedding',[])))}")
print(f"  Edges with embeddings: {sum(1 for r in relations if r.get('embedding') and any(v != 0 for v in r.get('embedding',[])))}")
print(f"  Provenance coverage (nodes): {sum(1 for e in entities.values() if e.get('provenance'))}/{len(entities)} ({100*sum(1 for e in entities.values() if e.get('provenance'))/len(entities):.1f}%)")
print(f"  Provenance coverage (edges): {sum(1 for r in relations if r.get('provenance'))}/{len(relations)} ({100*sum(1 for r in relations if r.get('provenance'))/len(relations):.1f}%)")
print(f"{'='*60}")

elapsed = time.time() - batch_start
print(f"  Embedding time: {elapsed:.1f}s")
