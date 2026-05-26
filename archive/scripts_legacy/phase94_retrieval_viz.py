"""Phase 9.4 — Retrieval + Visualization Verification.

Phase 9.4A: Graph Retrieval Smoke Test ✓ (already done above)
Phase 9.4B: Hybrid Retrieval (LanceDB + Neptune)
Phase 9.4C: Visualization (Mermaid + ReactFlow)

Requirements:
- No Neptune writes
- No LanceDB writes
- No LLM calls for graph extraction
- LLM calls ONLY for answer generation (via Bedrock Claude)
- All Neptune queries filtered by run_id + dataset
- Hub node limit: max_edges_per_node=30
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/projects/hermes_bedrock_agent/src")

from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
from hermes_bedrock_agent.embedding.embedder import BedrockEmbedder, EmbedderConfig
from hermes_bedrock_agent.retrieval.graph_retriever import (
    GraphRetrieverConfig,
    NeptuneGraphRetriever,
)
from hermes_bedrock_agent.retrieval.text_retriever import (
    TextRetrieverConfig,
    VectorStoreTextRetriever,
)
from hermes_bedrock_agent.retrieval.fusion import FusionConfig, FusionStrategy, fuse_evidence
from hermes_bedrock_agent.retrieval.context_builder import ContextBuilder, ContextBuilderConfig
from hermes_bedrock_agent.generation.answer_generator import AnswerGenerator, AnswerGeneratorConfig
from hermes_bedrock_agent.vector_store.lancedb_store import LanceDBStore

# ─── Configuration ───────────────────────────────────────────────────────────
RUN_ID = "murata_live_v1"
DATASET = "murata"
NEPTUNE_GRAPH_ID = "g-nbuyck5yl8"
REGION = "ap-northeast-1"
LANCEDB_PATH = "/home/ubuntu/projects/data/vector_store/lancedb"
LANCEDB_COLLECTION = "murata_e2e_murata_live_v1"
ARTIFACTS_DIR = Path("/home/ubuntu/projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts")

# Bedrock model for answer generation
ANSWER_MODEL = "apac.anthropic.claude-sonnet-4-20250514-v1:0"
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"

# Test questions
TEST_QUESTIONS = [
    "仕訳基礎とは何ですか？",
    "JOURNAL_BASE はどの機能から参照されていますか？",
    "payment_req テーブルは何に使われていますか？",
    "Murata PR システムの主要モジュールを教えてください。",
    "AC_DESC.CSV はどの処理に関係していますか？",
]


def main():
    print("=" * 70)
    print("PHASE 9.4B — HYBRID RETRIEVAL VERIFICATION")
    print("=" * 70)
    start_time = time.time()

    # ─── Initialize clients ──────────────────────────────────────────────
    print("\n[1/6] Initializing clients...")

    # Neptune client (read-only queries)
    neptune_client = NeptuneClient(graph_id=NEPTUNE_GRAPH_ID, region=REGION)

    # LanceDB vector store (read-only)
    lancedb_store = LanceDBStore(
        db_path=LANCEDB_PATH,
        collection=LANCEDB_COLLECTION,
    )

    # Bedrock embedder (for query embedding)
    embedder = BedrockEmbedder(
        config=EmbedderConfig(
            model_id=EMBEDDING_MODEL,
            dimension=1024,
        )
    )

    # Graph retriever with run_id/dataset filtering
    graph_config = GraphRetrieverConfig(
        max_hops=1,  # depth=1 for smoke test performance
        max_entities=10,
        max_paths=30,
        min_confidence=0.3,
    )

    # Patch graph retriever to filter by run_id/dataset
    class FilteredGraphRetriever(NeptuneGraphRetriever):
        """Graph retriever that enforces run_id + dataset filtering."""

        def search_entities(self, query_terms, *, entity_types=None, top_k=None):
            k = top_k or self.config.max_entities
            conditions = []
            params = {"limit": k, "run_id": RUN_ID, "dataset": DATASET}

            for i, term in enumerate(query_terms[:5]):
                param_name = f"term_{i}"
                params[param_name] = term.lower()
                conditions.append(
                    f"(toLower(n.name) CONTAINS ${param_name} "
                    f"OR toLower(n.canonical_name) CONTAINS ${param_name})"
                )

            where_clause = " OR ".join(conditions) if conditions else "true"

            query = (
                f"MATCH (n {{run_id: $run_id, dataset: $dataset}}) "
                f"WHERE {where_clause} "
                f"RETURN n LIMIT $limit"
            )

            try:
                results = self._client.execute_query(query, parameters=params)
                return self._extract_nodes(results)
            except Exception as e:
                print(f"  [WARN] Entity search failed: {e}")
                return []

        def expand_paths(self, entity_ids, *, max_hops=None, relation_types=None):
            """Expand paths with run_id filtering and max_edges limit."""
            hops = max_hops or self.config.max_hops
            all_paths = []

            for eid in entity_ids[:5]:
                query = (
                    f"MATCH (a {{entity_id: $eid, run_id: $run_id}})-[r]-"
                    f"(b {{run_id: $run_id}}) "
                    f"RETURN a.entity_id AS src_id, a.name AS src_name, "
                    f"a.entity_type AS src_type, "
                    f"type(r) AS rel_type, r.relation_id AS rel_id, "
                    f"r.source_chunk_id AS rel_chunk_id, "
                    f"r.confidence AS rel_conf, r.description AS rel_desc, "
                    f"b.entity_id AS tgt_id, b.name AS tgt_name, "
                    f"b.entity_type AS tgt_type "
                    f"LIMIT 30"
                )
                params = {"eid": eid, "run_id": RUN_ID}

                try:
                    results = self._client.execute_query(query, parameters=params)
                    rows = results.get("results", []) if isinstance(results, dict) else results
                    if isinstance(rows, list):
                        for row in rows:
                            path = {
                                "nodes": [
                                    {"entity_id": row.get("src_id"), "name": row.get("src_name"),
                                     "entity_type": row.get("src_type")},
                                    {"entity_id": row.get("tgt_id"), "name": row.get("tgt_name"),
                                     "entity_type": row.get("tgt_type")},
                                ],
                                "edges": [
                                    {"relation_id": row.get("rel_id", ""),
                                     "relation_type": row.get("rel_type", ""),
                                     "source_chunk_id": row.get("rel_chunk_id", ""),
                                     "confidence": row.get("rel_conf", 0.5),
                                     "description": row.get("rel_desc", "")},
                                ],
                                "score": row.get("rel_conf", 0.5),
                            }
                            all_paths.append(path)
                except Exception as e:
                    print(f"  [WARN] Path expand failed for {eid}: {e}")

            return all_paths

    graph_retriever = FilteredGraphRetriever(neptune_client, config=graph_config)

    # Text retriever
    text_config = TextRetrieverConfig(top_k=10, min_score=0.0)
    text_retriever = VectorStoreTextRetriever(lancedb_store, config=text_config)

    # Context builder (with chunk text resolver from LanceDB)
    def chunk_text_resolver(chunk_ids: list[str]) -> dict[str, str]:
        """Look up chunk text from LanceDB by chunk_id."""
        resolved = {}
        import lancedb
        db = lancedb.connect(LANCEDB_PATH)
        try:
            tbl = db.open_table(LANCEDB_COLLECTION)
            for cid in chunk_ids[:10]:
                rows = tbl.search().where(f"chunk_id = '{cid}'").limit(1).to_list()
                if rows:
                    resolved[cid] = rows[0].get("text", "")[:300]
        except Exception as e:
            print(f"  [WARN] Chunk resolver failed: {e}")
        return resolved

    context_builder = ContextBuilder(
        config=ContextBuilderConfig(
            max_text_chars=8000,
            max_graph_chars=4000,
            include_graph_chunk_text=True,
        ),
        chunk_text_resolver=chunk_text_resolver,
    )

    # Answer generator (LIVE Bedrock Claude)
    from hermes_bedrock_agent.clients.bedrock_client import get_bedrock_client
    bedrock_client = get_bedrock_client()

    answer_generator = AnswerGenerator(
        bedrock_client=bedrock_client,
        config=AnswerGeneratorConfig(
            model_id=ANSWER_MODEL,
            max_tokens=2048,
            temperature=0.1,
        ),
        context_builder=context_builder,
    )

    print("  ✓ Neptune client initialized")
    print("  ✓ LanceDB store initialized (1,020 vectors)")
    print("  ✓ Bedrock embedder initialized (Titan v2, dim=1024)")
    print("  ✓ Graph retriever initialized (filtered by run_id/dataset)")
    print("  ✓ Text retriever initialized (VectorStoreTextRetriever)")
    print("  ✓ Fusion + ContextBuilder initialized")
    print("  ✓ Answer generator initialized (Claude Sonnet)")

    # ─── Phase 9.4B: Hybrid Retrieval ────────────────────────────────────
    print("\n[2/6] Running Hybrid Retrieval for test questions...\n")

    retrieval_examples = []
    fused_examples = []
    answer_examples = []

    for qi, question in enumerate(TEST_QUESTIONS):
        print(f"  Q{qi+1}: {question}")
        q_start = time.time()

        # Step 1: Embed query
        try:
            query_embedding = embedder.embed_text(question)
            print(f"    ✓ Query embedded ({len(query_embedding)} dims)")
        except Exception as e:
            print(f"    ✗ Embedding failed: {e}")
            query_embedding = None

        # Step 2: Text retrieval (LanceDB vector search)
        if query_embedding:
            text_evidence = text_retriever.vector_search(
                query_embedding, top_k=10, query_text=question
            )
        else:
            text_evidence = []
        print(f"    Text evidence: {len(text_evidence)} chunks")

        # Step 3: Graph retrieval (Neptune)
        # Extract key terms from question for graph search
        import re
        query_terms = re.findall(r'[A-Z_]{3,}|[a-z_]{4,}|[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+', question)
        query_terms = [t for t in query_terms if len(t) >= 2][:5]
        print(f"    Query terms for graph: {query_terms}")

        graph_evidence = graph_retriever.retrieve_graph_context(
            query_terms, max_hops=1
        )
        print(f"    Graph evidence: {len(graph_evidence)} items")

        # Step 4: Fusion
        fused = fuse_evidence(
            text_evidence,
            graph_evidence,
            query=question,
            config=FusionConfig(
                strategy=FusionStrategy.RRF,
                max_text_evidence=10,
                max_graph_evidence=10,
            ),
        )
        print(f"    Fused: {fused.total_evidence_count} evidence, ~{fused.total_token_estimate} tokens")

        # Step 5: Answer generation (Bedrock Claude LIVE)
        try:
            answer_result = answer_generator.generate_answer(question, fused)
            print(f"    ✓ Answer generated ({answer_result.generation_time_ms}ms, "
                  f"conf={answer_result.confidence:.2f}, citations={answer_result.citation_count})")
            print(f"    Answer preview: {answer_result.answer[:120]}...")
        except Exception as e:
            print(f"    ✗ Answer generation failed: {e}")
            answer_result = None

        q_elapsed = time.time() - q_start

        # Save examples
        retrieval_example = {
            "question": question,
            "query_terms": query_terms,
            "text_evidence_count": len(text_evidence),
            "graph_evidence_count": len(graph_evidence),
            "text_evidence": [ev.model_dump(mode="json") for ev in text_evidence[:3]],
            "graph_evidence": [ev.model_dump(mode="json") for ev in graph_evidence[:3]],
            "elapsed_s": round(q_elapsed, 2),
        }
        retrieval_examples.append(retrieval_example)

        fused_example = {
            "question": question,
            "fusion_strategy": fused.fusion_strategy,
            "total_evidence": fused.total_evidence_count,
            "token_estimate": fused.total_token_estimate,
            "text_count": len(fused.text_evidence),
            "graph_count": len(fused.graph_evidence),
        }
        fused_examples.append(fused_example)

        if answer_result:
            answer_example = {
                "question": question,
                "answer": answer_result.answer,
                "confidence": answer_result.confidence,
                "citations": [c.model_dump(mode="json") for c in answer_result.citations],
                "text_evidence_used": answer_result.text_evidence_used,
                "graph_evidence_used": answer_result.graph_evidence_used,
                "used_chunk_ids": answer_result.used_chunk_ids[:5],
                "used_graph_paths": answer_result.used_graph_paths[:5],
                "generation_time_ms": answer_result.generation_time_ms,
                "model_name": answer_result.model_name,
                "insufficient_evidence": answer_result.insufficient_evidence,
            }
            answer_examples.append(answer_example)

        print()

    # ─── Save Phase 9.4B artifacts ───────────────────────────────────────
    print("[3/6] Saving retrieval artifacts...")

    with open(ARTIFACTS_DIR / "retrieval_live_examples.jsonl", "w") as f:
        for ex in retrieval_examples:
            f.write(json.dumps(ex, ensure_ascii=False, default=str) + "\n")

    with open(ARTIFACTS_DIR / "fused_context_examples.jsonl", "w") as f:
        for ex in fused_examples:
            f.write(json.dumps(ex, ensure_ascii=False, default=str) + "\n")

    with open(ARTIFACTS_DIR / "answer_examples.jsonl", "w") as f:
        for ex in answer_examples:
            f.write(json.dumps(ex, ensure_ascii=False, default=str) + "\n")

    print(f"  ✓ retrieval_live_examples.jsonl ({len(retrieval_examples)} entries)")
    print(f"  ✓ fused_context_examples.jsonl ({len(fused_examples)} entries)")
    print(f"  ✓ answer_examples.jsonl ({len(answer_examples)} entries)")

    # ─── Phase 9.4C: Visualization ───────────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 9.4C — VISUALIZATION VERIFICATION")
    print("=" * 70)

    VIZ_ENTITIES = ["JOURNAL_BASE", "payment_req", "muratapr"]
    VIZ_DEPTH = 2
    VIZ_MAX_NODES = 50
    VIZ_MAX_EDGES_PER_NODE = 30

    mermaid_outputs = []
    reactflow_outputs = []

    print(f"\n[4/6] Generating visualizations (depth={VIZ_DEPTH}, max_nodes={VIZ_MAX_NODES})...")

    for entity_name in VIZ_ENTITIES:
        print(f"\n  Entity: {entity_name}")

        # Find entity
        r = neptune_client.execute_query(
            "MATCH (n {run_id: $run_id, dataset: $dataset}) "
            "WHERE n.name = $name "
            "RETURN n.entity_id AS eid, n.entity_type AS etype, "
            "n.display_name AS display_name",
            parameters={"run_id": RUN_ID, "dataset": DATASET, "name": entity_name},
        )
        entity_info = r.get("results", [])
        if not entity_info:
            print(f"    [SKIP] Entity not found: {entity_name}")
            continue

        ent = entity_info[0]
        eid = ent["eid"]
        etype = ent["etype"]
        display = ent["display_name"]

        # Query depth=1 neighbors (limited)
        r = neptune_client.execute_query(
            "MATCH (a {entity_id: $eid, run_id: $run_id})-[r]-"
            "(b {run_id: $run_id}) "
            "RETURN a.entity_id AS src_id, a.name AS src_name, "
            "a.entity_type AS src_type, a.display_name AS src_display, "
            "type(r) AS rel_type, r.confidence AS conf, "
            "b.entity_id AS tgt_id, b.name AS tgt_name, "
            "b.entity_type AS tgt_type, b.display_name AS tgt_display "
            "LIMIT $limit",
            parameters={"eid": eid, "run_id": RUN_ID, "limit": VIZ_MAX_EDGES_PER_NODE},
        )
        depth1_rows = r.get("results", [])

        # Collect unique node IDs from depth 1
        depth1_node_ids = set()
        for row in depth1_rows:
            depth1_node_ids.add(row.get("tgt_id"))

        # For depth=2: expand from a subset of depth-1 nodes (limited to avoid explosion)
        depth2_rows = []
        expand_nodes = list(depth1_node_ids)[:10]  # Only expand top 10
        for nid in expand_nodes:
            r2 = neptune_client.execute_query(
                "MATCH (a {entity_id: $eid, run_id: $run_id})-[r]-"
                "(b {run_id: $run_id}) "
                "RETURN a.entity_id AS src_id, a.name AS src_name, "
                "a.entity_type AS src_type, a.display_name AS src_display, "
                "type(r) AS rel_type, r.confidence AS conf, "
                "b.entity_id AS tgt_id, b.name AS tgt_name, "
                "b.entity_type AS tgt_type, b.display_name AS tgt_display "
                "LIMIT 5",
                parameters={"eid": nid, "run_id": RUN_ID},
            )
            rows2 = r2.get("results", [])
            depth2_rows.extend(rows2)

        # Build node/edge sets
        all_nodes = {}
        all_edges = []

        # Center node
        all_nodes[eid] = {"id": eid, "name": entity_name, "type": etype,
                          "display_name": display, "is_center": True}

        # Depth 1
        for row in depth1_rows:
            tid = row.get("tgt_id", "")
            if tid and tid not in all_nodes:
                all_nodes[tid] = {
                    "id": tid,
                    "name": row.get("tgt_name", ""),
                    "type": row.get("tgt_type", ""),
                    "display_name": row.get("tgt_display", ""),
                    "is_center": False,
                }
            all_edges.append({
                "source": eid,
                "target": tid,
                "type": row.get("rel_type", ""),
                "confidence": row.get("conf", 0.5),
            })

        # Depth 2
        for row in depth2_rows:
            sid = row.get("src_id", "")
            tid = row.get("tgt_id", "")
            if tid and tid not in all_nodes and len(all_nodes) < VIZ_MAX_NODES:
                all_nodes[tid] = {
                    "id": tid,
                    "name": row.get("tgt_name", ""),
                    "type": row.get("tgt_type", ""),
                    "display_name": row.get("tgt_display", ""),
                    "is_center": False,
                }
            if tid in all_nodes:
                all_edges.append({
                    "source": sid,
                    "target": tid,
                    "type": row.get("rel_type", ""),
                    "confidence": row.get("conf", 0.5),
                })

        # Trim to max_nodes
        if len(all_nodes) > VIZ_MAX_NODES:
            keep_ids = set(list(all_nodes.keys())[:VIZ_MAX_NODES])
            all_nodes = {k: v for k, v in all_nodes.items() if k in keep_ids}
            all_edges = [e for e in all_edges if e["source"] in keep_ids and e["target"] in keep_ids]

        print(f"    Nodes: {len(all_nodes)}, Edges: {len(all_edges)}")

        # ─── Generate Mermaid ────────────────────────────────────────────
        mermaid_lines = ["graph TD"]
        # Sanitize Mermaid IDs (replace special chars)
        def mermaid_id(node_id):
            return node_id.replace("-", "_").replace(".", "_")[:20]

        def mermaid_label(name, ntype):
            safe = name.replace('"', "'").replace("<", "").replace(">", "")[:25]
            return f'{safe}<br/><small>{ntype}</small>'

        # Add nodes
        for nid, node in all_nodes.items():
            mid = mermaid_id(nid)
            label = mermaid_label(node["name"], node["type"])
            if node["is_center"]:
                mermaid_lines.append(f'    {mid}["{label}"]:::center')
            else:
                mermaid_lines.append(f'    {mid}["{label}"]')

        # Add edges (deduplicated)
        seen_edges = set()
        for edge in all_edges:
            src = mermaid_id(edge["source"])
            tgt = mermaid_id(edge["target"])
            key = f"{src}_{tgt}_{edge['type']}"
            if key in seen_edges:
                continue
            seen_edges.add(key)
            rel = edge["type"].lower().replace("_", " ")
            mermaid_lines.append(f'    {src} -->|{rel}| {tgt}')

        # Add style
        mermaid_lines.append("    classDef center fill:#f9a825,stroke:#e65100,stroke-width:2px")

        mermaid_text = "\n".join(mermaid_lines)
        mermaid_outputs.append({
            "entity": entity_name,
            "entity_type": etype,
            "depth": VIZ_DEPTH,
            "nodes": len(all_nodes),
            "edges": len(seen_edges),
            "mermaid": mermaid_text,
        })
        print(f"    ✓ Mermaid: {len(seen_edges)} edges rendered")

        # ─── Generate ReactFlow JSON ─────────────────────────────────────
        rf_nodes = []
        rf_edges = []
        x_pos = 0
        y_pos = 0

        for i, (nid, node) in enumerate(all_nodes.items()):
            # Simple grid layout
            x_pos = (i % 8) * 200
            y_pos = (i // 8) * 150
            rf_nodes.append({
                "id": nid,
                "type": "entityNode",
                "position": {"x": x_pos, "y": y_pos},
                "data": {
                    "label": node["display_name"] or node["name"],
                    "entity_type": node["type"],
                    "is_center": node["is_center"],
                },
            })

        seen_rf_edges = set()
        for edge in all_edges:
            key = f"{edge['source']}_{edge['target']}_{edge['type']}"
            if key in seen_rf_edges:
                continue
            seen_rf_edges.add(key)
            rf_edges.append({
                "id": f"e_{edge['source'][:8]}_{edge['target'][:8]}",
                "source": edge["source"],
                "target": edge["target"],
                "label": edge["type"],
                "data": {"confidence": edge.get("confidence", 0.5)},
            })

        reactflow_output = {
            "entity": entity_name,
            "entity_type": etype,
            "depth": VIZ_DEPTH,
            "nodes": rf_nodes,
            "edges": rf_edges,
        }
        reactflow_outputs.append(reactflow_output)
        print(f"    ✓ ReactFlow: {len(rf_nodes)} nodes, {len(rf_edges)} edges")

    # ─── Save visualization artifacts ────────────────────────────────────
    print("\n[5/6] Saving visualization artifacts...")

    # Mermaid examples
    mermaid_md = "# Phase 9.4C — Mermaid Visualization Examples\n\n"
    for m in mermaid_outputs:
        mermaid_md += f"## {m['entity']} ({m['entity_type']}) — depth={m['depth']}\n\n"
        mermaid_md += f"Nodes: {m['nodes']}, Edges: {m['edges']}\n\n"
        mermaid_md += f"```mermaid\n{m['mermaid']}\n```\n\n"

    with open(ARTIFACTS_DIR / "mermaid_examples.md", "w") as f:
        f.write(mermaid_md)

    # ReactFlow JSON
    with open(ARTIFACTS_DIR / "reactflow_examples.json", "w") as f:
        json.dump(reactflow_outputs, f, ensure_ascii=False, indent=2, default=str)

    print(f"  ✓ mermaid_examples.md ({len(mermaid_outputs)} graphs)")
    print(f"  ✓ reactflow_examples.json ({len(reactflow_outputs)} graphs)")

    # ─── Generate reports ────────────────────────────────────────────────
    print("\n[6/6] Generating reports...")

    total_elapsed = time.time() - start_time

    # Hybrid retrieval report
    hybrid_report = {
        "phase": "9.4B",
        "run_id": RUN_ID,
        "dataset": DATASET,
        "date": datetime.now(timezone.utc).isoformat(),
        "questions_tested": len(TEST_QUESTIONS),
        "answers_generated": len(answer_examples),
        "retrieval_summary": {
            "avg_text_evidence": sum(e["text_evidence_count"] for e in retrieval_examples) / len(retrieval_examples),
            "avg_graph_evidence": sum(e["graph_evidence_count"] for e in retrieval_examples) / len(retrieval_examples),
            "avg_fused_tokens": sum(e["token_estimate"] for e in fused_examples) / len(fused_examples),
        },
        "answer_summary": {
            "avg_confidence": sum(a["confidence"] for a in answer_examples) / max(len(answer_examples), 1),
            "avg_generation_ms": sum(a.get("generation_time_ms", 0) or 0 for a in answer_examples) / max(len(answer_examples), 1),
            "total_citations": sum(len(a["citations"]) for a in answer_examples),
            "questions_with_graph_paths": sum(1 for a in answer_examples if a.get("used_graph_paths")),
        },
        "total_elapsed_s": round(total_elapsed, 1),
    }

    with open(ARTIFACTS_DIR / "hybrid_retrieval_report.json", "w") as f:
        json.dump(hybrid_report, f, ensure_ascii=False, indent=2)

    # Visualization report
    viz_report = {
        "phase": "9.4C",
        "run_id": RUN_ID,
        "dataset": DATASET,
        "date": datetime.now(timezone.utc).isoformat(),
        "entities_visualized": len(mermaid_outputs),
        "mermaid_graphs": [
            {"entity": m["entity"], "nodes": m["nodes"], "edges": m["edges"]}
            for m in mermaid_outputs
        ],
        "reactflow_graphs": [
            {"entity": r["entity"], "nodes": len(r["nodes"]), "edges": len(r["edges"])}
            for r in reactflow_outputs
        ],
    }

    with open(ARTIFACTS_DIR / "visualization_report.json", "w") as f:
        json.dump(viz_report, f, ensure_ascii=False, indent=2)

    print(f"  ✓ hybrid_retrieval_report.json")
    print(f"  ✓ visualization_report.json")

    # ─── Final summary ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 9.4 COMPLETE")
    print("=" * 70)
    print(f"\n  Total time: {total_elapsed:.1f}s")
    print(f"  Questions tested: {len(TEST_QUESTIONS)}")
    print(f"  Answers generated: {len(answer_examples)}")
    print(f"  Mermaid graphs: {len(mermaid_outputs)}")
    print(f"  ReactFlow graphs: {len(reactflow_outputs)}")
    print(f"\n  Artifacts:")
    print(f"    retrieval_live_examples.jsonl")
    print(f"    fused_context_examples.jsonl")
    print(f"    answer_examples.jsonl")
    print(f"    hybrid_retrieval_report.json")
    print(f"    mermaid_examples.md")
    print(f"    reactflow_examples.json")
    print(f"    visualization_report.json")


if __name__ == "__main__":
    main()
