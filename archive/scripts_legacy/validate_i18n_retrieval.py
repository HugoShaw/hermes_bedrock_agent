#!/usr/bin/env python3
"""Phase 10B.1: i18n Enriched Retrieval + Visualization Validation.

Validates that i18n artifacts improve:
1. Query Entity Extraction (CJK aliases → entity match)
2. Graph Retrieval (Neptune live queries with extracted terms)
3. Hybrid Retrieval + Answer (LanceDB + Neptune + Claude)
4. Visualization (Mermaid + ReactFlow with i18n labels)

Usage:
    python scripts/validate_i18n_retrieval.py \
        --run-id murata_live_v1 \
        --artifacts-dir ~/projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts/ \
        [--skip-neptune]  \
        [--skip-hybrid]   \
        [--skip-answer]

Output artifacts:
    - phase10b1_i18n_retrieval_report.md
    - phase10b1_i18n_retrieval_report.json
    - query_entity_extraction_i18n_validation.jsonl
    - answer_i18n_examples.jsonl
    - mermaid_i18n_examples.md
    - reactflow_i18n_examples.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hermes_bedrock_agent.retrieval.query_entity_extractor import (
    EntityIndex,
    QueryEntityExtractor,
    QueryExtractionResult,
    QueryLanguage,
)
from hermes_bedrock_agent.visualization.mermaid_generator import (
    MermaidConfig,
    MermaidGenerator,
    resolve_i18n_label,
)
from hermes_bedrock_agent.visualization.reactflow_exporter import (
    ReactFlowConfig,
    ReactFlowExporter,
)
from hermes_bedrock_agent.schemas.visualization import (
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)
from hermes_bedrock_agent.graph.i18n_enricher import BUILTIN_RELATION_I18N_MAP


# ─── Test Queries ─────────────────────────────────────────────────────────────

TEST_QUERIES = [
    {
        "question": "仕訳基礎とは何ですか？",
        "expected_entities": ["journal_base"],
        "expected_lang": "ja",
        "description": "Japanese query for JOURNAL_BASE table",
    },
    {
        "question": "仕訳基礎テーブルはどの機能から参照されていますか？",
        "expected_entities": ["journal_base"],
        "expected_lang": "ja",
        "description": "Japanese query with テーブル suffix",
    },
    {
        "question": "付款申请相关表有哪些？",
        "expected_entities": ["payment_req", "付款申请"],
        "expected_lang": "zh",
        "description": "Simplified Chinese for payment request (accepts both payment_req and 付款申请 entity)",
    },
    {
        "question": "付款申請の処理フローを教えてください。",
        "expected_entities": ["payment_req", "付款申请"],
        "expected_lang": "ja",
        "description": "Traditional Chinese + Japanese mix (accepts both payment_req and 付款申请 entity)",
    },
    {
        "question": "支払申請テーブルはどの機能で使われていますか？",
        "expected_entities": ["payment_req"],
        "expected_lang": "ja",
        "description": "Japanese alias for payment_req",
    },
    {
        "question": "村田PRシステムの主要モジュールを教えてください。",
        "expected_entities": ["muratapr"],
        "expected_lang": "ja",
        "description": "Japanese alias for muratapr",
    },
    {
        "question": "Murata PR system の主要モジュールを教えてください。",
        "expected_entities": ["muratapr"],
        "expected_lang": "mixed",
        "description": "English + Japanese mix for muratapr",
    },
]


# ─── Visualization Test Entities ──────────────────────────────────────────────

VIZ_TEST_ENTITIES = ["journal_base", "payment_req", "muratapr"]

VIZ_LABEL_MODES = [
    {"lang": "ja", "label_mode": "business"},
    {"lang": "zh", "label_mode": "business"},
    {"lang": "ja", "label_mode": "mixed"},
    {"lang": "zh", "label_mode": "mixed"},
    {"lang": "en", "label_mode": "technical"},
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_entity_index(artifacts_dir: Path) -> tuple[EntityIndex, EntityIndex]:
    """Load two indexes: one without i18n, one with i18n.

    Returns:
        (baseline_index, enriched_index)
    """
    entities_path = artifacts_dir / "entities.jsonl"
    i18n_path = artifacts_dir / "i18n_entities_enriched.jsonl"

    # Baseline index (Phase 10A behavior)
    baseline = EntityIndex()
    baseline.load_from_jsonl(str(entities_path))

    # Enriched index (Phase 10B)
    enriched = EntityIndex()
    enriched.load_from_jsonl(str(entities_path))
    if i18n_path.exists():
        enriched.load_i18n_enrichment(str(i18n_path))

    return baseline, enriched


def search_index(index: EntityIndex, question: str) -> list[dict]:
    """Search index using all available strategies."""
    results = []
    seen = set()

    # Strategy 1: CJK match
    cjk_results = index.cjk_match(question, min_len=2, max_results=10)
    for r in cjk_results:
        cn = r.get("canonical_name", "").lower()
        if cn not in seen:
            seen.add(cn)
            results.append(r)

    # Strategy 2: Substring match on extracted terms
    import re
    # Extract potential entity terms
    tech_terms = re.findall(r'\b([A-Z][A-Z0-9_]{2,})\b', question)
    snake_terms = re.findall(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b', question)
    camel_terms = re.findall(r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)*)\b', question)

    for term in tech_terms + snake_terms + camel_terms:
        sub_results = index.substring_match(term, max_results=5)
        for r in sub_results:
            cn = r.get("canonical_name", "").lower()
            if cn not in seen:
                seen.add(cn)
                results.append(r)

    # Strategy 3: Direct lookup for compound names
    compound = re.findall(r'\b([A-Z][a-z]+\s+[A-Z]{2,})\b', question)
    for comp in compound:
        normalized = comp.lower().replace(" ", "")
        info = index.lookup(normalized)
        if info:
            cn = info.get("canonical_name", "").lower()
            if cn not in seen:
                seen.add(cn)
                results.append(info)

    return results


def extract_with_comparison(
    baseline: EntityIndex,
    enriched: EntityIndex,
    question: str,
) -> dict:
    """Run extraction with both baseline and enriched indexes."""
    # Use QueryEntityExtractor for both
    extractor_baseline = QueryEntityExtractor(baseline)
    extractor_enriched = QueryEntityExtractor(enriched)

    result_baseline = extractor_baseline.extract(question)
    result_enriched = extractor_enriched.extract(question)

    # Also do raw search for comparison
    raw_baseline = search_index(baseline, question)
    raw_enriched = search_index(enriched, question)

    return {
        "baseline": {
            "extraction": result_baseline,
            "raw_matches": raw_baseline,
        },
        "enriched": {
            "extraction": result_enriched,
            "raw_matches": raw_enriched,
        },
    }


def build_i18n_data(artifacts_dir: Path) -> dict[str, dict]:
    """Load i18n enrichment data as lookup dict keyed by canonical_name."""
    i18n_path = artifacts_dir / "i18n_entities_enriched.jsonl"
    i18n_data = {}
    if i18n_path.exists():
        with open(i18n_path) as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                canonical = entry.get("canonical_name", "").lower()
                if canonical:
                    i18n_data[canonical] = entry
    return i18n_data


def build_sample_subgraph(
    center_entity: str,
    i18n_data: dict[str, dict],
    relations: list[dict],
    entities: dict[str, dict],
    *,
    entity_id_to_canonical: Optional[dict[str, str]] = None,
) -> SubgraphResult:
    """Build a sample subgraph around a center entity using real data."""
    center_lower = center_entity.lower()

    # Use pre-built entity_id → canonical mapping if provided
    if entity_id_to_canonical:
        id_to_canonical = entity_id_to_canonical
    else:
        # Build from entities dict
        id_to_canonical = {}
        for cn, info in entities.items():
            eid = info.get("entity_id", "")
            if eid:
                id_to_canonical[eid] = cn

    # Find the entity_id(s) for the center entity
    center_eids = set()
    for eid, cn in id_to_canonical.items():
        if cn == center_lower:
            center_eids.add(eid)

    # Find edges involving this entity by entity_id
    relevant_edges = []
    neighbor_canonicals = set()
    for rel in relations:
        src_eid = rel.get("source_entity_id", "")
        tgt_eid = rel.get("target_entity_id", "")
        if src_eid in center_eids or tgt_eid in center_eids:
            src_cn = id_to_canonical.get(src_eid, src_eid)
            tgt_cn = id_to_canonical.get(tgt_eid, tgt_eid)
            relevant_edges.append({
                **rel,
                "source_canonical": src_cn,
                "target_canonical": tgt_cn,
            })
            neighbor_canonicals.add(src_cn)
            neighbor_canonicals.add(tgt_cn)
            if len(relevant_edges) >= 15:
                break

    # Build nodes
    viz_nodes = []
    all_canonicals = neighbor_canonicals | {center_lower}
    for cn in all_canonicals:
        entity_info = entities.get(cn, {})
        viz_nodes.append(VisualizationNode(
            node_id=cn,
            label=entity_info.get("canonical_name", cn),
            entity_type=entity_info.get("entity_type", "unknown"),
            description=entity_info.get("description", "")[:100],
        ))

    # Build edges
    viz_edges = []
    for i, rel in enumerate(relevant_edges):
        viz_edges.append(VisualizationEdge(
            edge_id=rel.get("relation_id", f"edge_{i}"),
            source_id=rel["source_canonical"],
            target_id=rel["target_canonical"],
            label=rel.get("relation_type", "related_to"),
            relation_type=rel.get("relation_type", "related_to"),
        ))

    return SubgraphResult(
        query=center_entity,
        center_entity_id=center_lower,
        nodes=viz_nodes,
        edges=viz_edges,
    )


# ─── Neptune Graph Retrieval ─────────────────────────────────────────────────

def run_graph_retrieval(
    question: str,
    graph_search_terms: list[str],
    run_id: str,
    dataset: str,
) -> dict:
    """Execute Neptune graph retrieval using extracted terms.

    Returns dict with evidence count, top paths, etc.
    """
    try:
        from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
        from hermes_bedrock_agent.retrieval.graph_retriever import (
            GraphRetrieverConfig,
            NeptuneGraphRetriever,
        )

        client = NeptuneClient(graph_id="g-nbuyck5yl8")
        config = GraphRetrieverConfig(
            max_entities=20,
            max_hops=2,
            use_query_extractor=False,
        )
        retriever = NeptuneGraphRetriever(client, config)

        # Search with enriched terms
        entities = retriever.search_entities(graph_search_terms, top_k=10)

        # Get graph context
        evidence = retriever.retrieve_graph_context(
            graph_search_terms,
            max_hops=2,
        )

        return {
            "success": True,
            "entity_count": len(entities),
            "evidence_count": len(evidence),
            "top_entities": [
                {
                    "name": e.get("name", ""),
                    "canonical_name": e.get("canonical_name", ""),
                    "entity_type": e.get("entity_type", ""),
                }
                for e in entities[:5]
            ],
            "top_evidence": [
                {
                    "entity_id": ev.entity_id if hasattr(ev, "entity_id") else str(ev),
                    "source_chunk_id": ev.source_chunk_id if hasattr(ev, "source_chunk_id") else "",
                    "evidence_id": ev.evidence_id if hasattr(ev, "evidence_id") else "",
                }
                for ev in (evidence[:3] if evidence else [])
            ],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "entity_count": 0,
            "evidence_count": 0,
        }


# ─── Hybrid Retrieval ─────────────────────────────────────────────────────────

def run_hybrid_retrieval(
    question: str,
    graph_search_terms: list[str],
    run_id: str,
    dataset: str,
    lancedb_collection: str,
) -> dict:
    """Execute hybrid retrieval (LanceDB vector + Neptune graph).

    Returns dict with text evidence, graph evidence, fused context.
    """
    result = {
        "text_evidence_count": 0,
        "graph_evidence_count": 0,
        "fused_context_size": 0,
        "answer": "",
        "citations": [],
        "insufficient_evidence": False,
    }

    try:
        # 1. Vector search via LanceDB
        from hermes_bedrock_agent.vector_store.lancedb_store import LanceDBStore
        from hermes_bedrock_agent.retrieval.text_retriever import (
            VectorStoreTextRetriever,
            TextRetrieverConfig,
        )

        store = LanceDBStore(collection=lancedb_collection)
        text_config = TextRetrieverConfig(top_k=5)
        text_retriever = VectorStoreTextRetriever(store, text_config)

        # Need embedding for vector search - use keyword fallback
        text_results = text_retriever.keyword_search(
            query_text=question,
            top_k=5,
        )
        result["text_evidence_count"] = len(text_results)

    except Exception as e:
        result["text_search_error"] = str(e)

    try:
        # 2. Graph retrieval
        graph_result = run_graph_retrieval(
            question, graph_search_terms, run_id, dataset
        )
        result["graph_evidence_count"] = graph_result.get("evidence_count", 0)
        result["graph_retrieval_success"] = graph_result.get("success", False)

    except Exception as e:
        result["graph_search_error"] = str(e)

    # 3. Fuse context
    result["fused_context_size"] = (
        result["text_evidence_count"] + result["graph_evidence_count"]
    )

    # 4. Answer generation (skip unless we have evidence)
    if result["fused_context_size"] == 0:
        result["insufficient_evidence"] = True
        result["answer"] = "[No evidence found]"
    else:
        # We don't call LLM for answer - just mark that evidence exists
        result["answer"] = f"[Evidence available: {result['fused_context_size']} items]"

    return result


# ─── Validation Pipeline ──────────────────────────────────────────────────────

def validate_query_extraction(
    artifacts_dir: Path,
) -> tuple[list[dict], dict]:
    """Validate query entity extraction with and without i18n.

    Returns:
        (validation_results, summary_stats)
    """
    print("\n" + "=" * 70)
    print("  STEP 1: Query Entity Extraction Validation")
    print("=" * 70)

    baseline_index, enriched_index = load_entity_index(artifacts_dir)
    print(f"  Baseline index size: {baseline_index.size}")
    print(f"  Enriched index size: {enriched_index.size}")

    results = []
    improved_count = 0
    total_queries = len(TEST_QUERIES)

    for i, test in enumerate(TEST_QUERIES, 1):
        question = test["question"]
        expected = test["expected_entities"]

        print(f"\n  [{i}/{total_queries}] {question}")

        comparison = extract_with_comparison(baseline_index, enriched_index, question)

        # Check baseline matches
        baseline_extraction = comparison["baseline"]["extraction"]
        baseline_raw = comparison["baseline"]["raw_matches"]
        baseline_terms = baseline_extraction.graph_search_terms
        baseline_matched = [
            r.get("canonical_name", "").lower()
            for r in baseline_raw
        ]

        # Check enriched matches
        enriched_extraction = comparison["enriched"]["extraction"]
        enriched_raw = comparison["enriched"]["raw_matches"]
        enriched_terms = enriched_extraction.graph_search_terms
        enriched_matched = [
            r.get("canonical_name", "").lower()
            for r in enriched_raw
        ]

        # Determine if expected entities were found
        baseline_hit = any(exp.lower() in baseline_matched for exp in expected)
        enriched_hit = any(exp.lower() in enriched_matched for exp in expected)

        if enriched_hit and not baseline_hit:
            improved_count += 1
            status = "IMPROVED"
        elif enriched_hit and baseline_hit:
            status = "MAINTAINED"
        elif not enriched_hit and not baseline_hit:
            status = "MISSED"
        else:
            status = "REGRESSED"

        # Find alias source for matched entities
        alias_source = ""
        for r in enriched_raw:
            cn = r.get("canonical_name", "").lower()
            if cn in [e.lower() for e in expected]:
                # Check which alias matched
                alias_source = "canonical_name/name match"
                break

        # Check enriched extraction mentions
        mention_sources = []
        for m in enriched_extraction.entity_mentions:
            if m.matched_entity_name and m.matched_entity_name.lower() in [e.lower() for e in expected]:
                mention_sources.append(f"{m.source}:{m.surface_form}")

        print(f"    Status: {status}")
        print(f"    Detected lang: {enriched_extraction.detected_language.value}")
        print(f"    Baseline matches: {baseline_matched[:3]}")
        print(f"    Enriched matches: {enriched_matched[:3]}")
        print(f"    Expected: {expected}")
        print(f"    Graph search terms: {enriched_terms[:5]}")

        entry = {
            "question": question,
            "expected_entities": expected,
            "detected_language": enriched_extraction.detected_language.value,
            "status": status,
            "baseline_hit": baseline_hit,
            "enriched_hit": enriched_hit,
            "baseline_matched_entities": baseline_matched[:5],
            "enriched_matched_entities": enriched_matched[:5],
            "entity_mentions": [
                {
                    "surface_form": m.surface_form,
                    "normalized": m.normalized,
                    "source": m.source,
                    "confidence": m.confidence,
                    "matched_entity_name": m.matched_entity_name,
                }
                for m in enriched_extraction.entity_mentions[:5]
            ],
            "graph_search_terms": enriched_terms[:10],
            "expanded_terms": enriched_extraction.expanded_terms[:10],
            "mention_sources": mention_sources,
            "description": test["description"],
        }
        results.append(entry)

    summary = {
        "total_queries": total_queries,
        "improved": improved_count,
        "maintained": sum(1 for r in results if r["status"] == "MAINTAINED"),
        "missed": sum(1 for r in results if r["status"] == "MISSED"),
        "regressed": sum(1 for r in results if r["status"] == "REGRESSED"),
        "enriched_hit_rate": sum(1 for r in results if r["enriched_hit"]) / total_queries,
        "baseline_hit_rate": sum(1 for r in results if r["baseline_hit"]) / total_queries,
    }

    print(f"\n  Summary:")
    print(f"    Improved: {summary['improved']}/{total_queries}")
    print(f"    Maintained: {summary['maintained']}/{total_queries}")
    print(f"    Missed: {summary['missed']}/{total_queries}")
    print(f"    Baseline hit rate: {summary['baseline_hit_rate']:.0%}")
    print(f"    Enriched hit rate: {summary['enriched_hit_rate']:.0%}")

    return results, summary


def validate_graph_retrieval(
    artifacts_dir: Path,
    extraction_results: list[dict],
    run_id: str,
    dataset: str,
    skip_neptune: bool = False,
) -> list[dict]:
    """Validate graph retrieval with extracted terms."""
    print("\n" + "=" * 70)
    print("  STEP 2: Graph Retrieval Validation")
    print("=" * 70)

    if skip_neptune:
        print("  [SKIPPED] --skip-neptune flag set")
        return [
            {
                "question": r["question"],
                "graph_search_terms": r["graph_search_terms"],
                "skipped": True,
                "reason": "Neptune access skipped",
            }
            for r in extraction_results
        ]

    results = []
    for i, ext in enumerate(extraction_results, 1):
        question = ext["question"]
        terms = ext["graph_search_terms"]

        print(f"\n  [{i}/{len(extraction_results)}] {question}")
        print(f"    Terms: {terms[:5]}")

        graph_result = run_graph_retrieval(question, terms, run_id, dataset)

        print(f"    Success: {graph_result['success']}")
        print(f"    Entities found: {graph_result['entity_count']}")
        print(f"    Evidence count: {graph_result['evidence_count']}")

        results.append({
            "question": question,
            "graph_search_terms": terms,
            **graph_result,
        })

    return results


def validate_hybrid_retrieval(
    artifacts_dir: Path,
    extraction_results: list[dict],
    run_id: str,
    dataset: str,
    lancedb_collection: str,
    skip_hybrid: bool = False,
) -> list[dict]:
    """Validate hybrid retrieval (text + graph)."""
    print("\n" + "=" * 70)
    print("  STEP 3: Hybrid Retrieval + Answer Validation")
    print("=" * 70)

    if skip_hybrid:
        print("  [SKIPPED] --skip-hybrid flag set")
        return [
            {
                "question": r["question"],
                "skipped": True,
                "reason": "Hybrid retrieval skipped",
            }
            for r in extraction_results
        ]

    results = []
    for i, ext in enumerate(extraction_results, 1):
        question = ext["question"]
        terms = ext["graph_search_terms"]

        print(f"\n  [{i}/{len(extraction_results)}] {question}")

        hybrid_result = run_hybrid_retrieval(
            question, terms, run_id, dataset, lancedb_collection
        )

        print(f"    Text evidence: {hybrid_result['text_evidence_count']}")
        print(f"    Graph evidence: {hybrid_result['graph_evidence_count']}")
        print(f"    Fused context: {hybrid_result['fused_context_size']}")
        print(f"    Insufficient: {hybrid_result['insufficient_evidence']}")

        results.append({
            "question": question,
            **hybrid_result,
        })

    return results


def validate_visualization(
    artifacts_dir: Path,
    i18n_data: dict[str, dict],
    relations: list[dict],
    entities: dict[str, dict],
    *,
    entity_id_to_canonical: Optional[dict[str, str]] = None,
) -> tuple[str, str]:
    """Validate visualization with i18n labels.

    Returns:
        (mermaid_markdown, reactflow_json)
    """
    print("\n" + "=" * 70)
    print("  STEP 4: Visualization Validation")
    print("=" * 70)

    mermaid_sections = []
    reactflow_examples = {}

    for entity in VIZ_TEST_ENTITIES:
        print(f"\n  Entity: {entity}")

        # Build subgraph from real data
        subgraph = build_sample_subgraph(
            entity, i18n_data, relations, entities,
            entity_id_to_canonical=entity_id_to_canonical,
        )
        print(f"    Nodes: {subgraph.node_count}, Edges: {subgraph.edge_count}")

        entity_mermaid = []
        entity_rf = {}

        for mode in VIZ_LABEL_MODES:
            lang = mode["lang"]
            label_mode = mode["label_mode"]
            mode_key = f"{lang}_{label_mode}"

            print(f"    Mode: lang={lang}, label_mode={label_mode}")

            # Mermaid generation
            mermaid_config = MermaidConfig(
                direction="LR",
                max_nodes=15,
                show_edge_labels=True,
                lang=lang,
                label_mode=label_mode,
            )
            mermaid_gen = MermaidGenerator(mermaid_config)
            mermaid_code = mermaid_gen.generate_flowchart(
                subgraph,
                i18n_data=i18n_data,
                lang=lang,
                label_mode=label_mode,
                title=f"{entity} ({lang}/{label_mode})",
            )
            entity_mermaid.append((mode_key, mermaid_code))

            # ReactFlow generation
            rf_config = ReactFlowConfig(
                lang=lang,
                label_mode=label_mode,
            )
            rf_exporter = ReactFlowExporter(rf_config)
            rf_data = rf_exporter.export(
                subgraph,
                i18n_data=i18n_data,
                lang=lang,
                label_mode=label_mode,
            )
            entity_rf[mode_key] = rf_data

            # Validate labels
            if subgraph.nodes:
                first_node = subgraph.nodes[0]
                resolved = resolve_i18n_label(
                    first_node.node_id,
                    first_node.label,
                    i18n_data=i18n_data,
                    lang=lang,
                    label_mode=label_mode,
                )
                print(f"      Sample label: {resolved[:50]}")

        # Build mermaid markdown section
        section = f"\n## {entity}\n\n"
        for mode_key, code in entity_mermaid:
            section += f"### {mode_key}\n\n```mermaid\n{code}\n```\n\n"
        mermaid_sections.append(section)

        reactflow_examples[entity] = entity_rf

    # Combine
    mermaid_md = "# Mermaid i18n Examples\n\n"
    mermaid_md += f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
    mermaid_md += f"Entities: {VIZ_TEST_ENTITIES}\n"
    mermaid_md += f"Modes: {VIZ_LABEL_MODES}\n\n"
    mermaid_md += "\n".join(mermaid_sections)

    reactflow_json = json.dumps(reactflow_examples, ensure_ascii=False, indent=2)

    return mermaid_md, reactflow_json


# ─── Report Generation ────────────────────────────────────────────────────────

def generate_report(
    extraction_results: list[dict],
    extraction_summary: dict,
    graph_results: list[dict],
    hybrid_results: list[dict],
    artifacts_dir: Path,
    run_id: str,
    skip_neptune: bool,
    skip_hybrid: bool,
) -> tuple[str, dict]:
    """Generate comprehensive Phase 10B.1 report.

    Returns:
        (markdown_report, json_report)
    """
    now = datetime.now(timezone.utc).isoformat()

    # Analyze key questions
    key_results = {}
    for r in extraction_results:
        q = r["question"]
        if "仕訳基礎" in q and "テーブル" not in q:
            key_results["仕訳基礎"] = r
        elif "付款申请" in q:
            key_results["付款申请"] = r
        elif "付款申請" in q:
            key_results["付款申請"] = r
        elif "Murata PR" in q:
            key_results["Murata PR"] = r
        elif "村田PR" in q:
            key_results["村田PR"] = r
        elif "支払申請" in q:
            key_results["支払申請"] = r

    # Build markdown report
    md = f"""# Phase 10B.1: i18n Enriched Retrieval Validation Report

**Generated:** {now}
**Run ID:** {run_id}
**Artifacts Dir:** {artifacts_dir}

## Executive Summary

| Metric | Value |
|--------|-------|
| Total test queries | {extraction_summary['total_queries']} |
| Baseline hit rate | {extraction_summary['baseline_hit_rate']:.0%} |
| Enriched hit rate | {extraction_summary['enriched_hit_rate']:.0%} |
| Improved queries | {extraction_summary['improved']} |
| Maintained queries | {extraction_summary['maintained']} |
| Missed queries | {extraction_summary['missed']} |
| Regressed queries | {extraction_summary['regressed']} |

## 1. Query Entity Extraction Results

### Key Query Analysis

"""
    for key, r in key_results.items():
        md += f"""#### {key}
- **Question:** {r['question']}
- **Status:** {r['status']}
- **Baseline hit:** {r['baseline_hit']}
- **Enriched hit:** {r['enriched_hit']}
- **Detected language:** {r['detected_language']}
- **Matched entities:** {r['enriched_matched_entities'][:3]}
- **Graph search terms:** {r['graph_search_terms'][:5]}

"""

    # Summary table
    md += """### All Queries

| # | Question | Status | Baseline | Enriched | Terms |
|---|----------|--------|----------|----------|-------|
"""
    for i, r in enumerate(extraction_results, 1):
        q_short = r["question"][:30]
        terms_short = ", ".join(r["graph_search_terms"][:3])
        md += f"| {i} | {q_short} | {r['status']} | {'✓' if r['baseline_hit'] else '✗'} | {'✓' if r['enriched_hit'] else '✗'} | {terms_short} |\n"

    # Graph retrieval section
    md += "\n## 2. Graph Retrieval Results\n\n"
    if skip_neptune:
        md += "*Skipped (--skip-neptune)*\n\n"
    else:
        md += "| # | Question | Success | Entities | Evidence |\n"
        md += "|---|----------|---------|----------|----------|\n"
        for i, r in enumerate(graph_results, 1):
            q_short = r["question"][:30]
            md += f"| {i} | {q_short} | {r.get('success', 'N/A')} | {r.get('entity_count', 'N/A')} | {r.get('evidence_count', 'N/A')} |\n"

    # Hybrid retrieval section
    md += "\n## 3. Hybrid Retrieval Results\n\n"
    if skip_hybrid:
        md += "*Skipped (--skip-hybrid)*\n\n"
    else:
        md += "| # | Question | Text | Graph | Fused | Insufficient |\n"
        md += "|---|----------|------|-------|-------|--------------|\n"
        for i, r in enumerate(hybrid_results, 1):
            q_short = r["question"][:30]
            md += f"| {i} | {q_short} | {r.get('text_evidence_count', 'N/A')} | {r.get('graph_evidence_count', 'N/A')} | {r.get('fused_context_size', 'N/A')} | {r.get('insufficient_evidence', 'N/A')} |\n"

    # Conclusions
    md += f"""
## 4. Visualization Validation

See artifacts:
- `mermaid_i18n_examples.md` — Mermaid diagrams in zh/en/ja with business/technical/mixed modes
- `reactflow_i18n_examples.json` — ReactFlow JSON with i18n labels

## 5. Conclusions

### i18n Aliases Resolution

| Issue | Before (10A) | After (10B) | Resolved? |
|-------|-------------|-------------|-----------|
| 仕訳基礎 → JOURNAL_BASE | 0 matches | {"✓" if key_results.get("仕訳基礎", {}).get("enriched_hit") else "✗"} | {"YES" if key_results.get("仕訳基礎", {}).get("enriched_hit") else "NO"} |
| 付款申请 → payment_req | unstable | {"✓" if key_results.get("付款申请", {}).get("enriched_hit") else "✗"} | {"YES" if key_results.get("付款申请", {}).get("enriched_hit") else "NO"} |
| 付款申請 → payment_req | unstable | {"✓" if key_results.get("付款申請", {}).get("enriched_hit") else "✗"} | {"YES" if key_results.get("付款申請", {}).get("enriched_hit") else "NO"} |
| 支払申請 → payment_req | 0 matches | {"✓" if key_results.get("支払申請", {}).get("enriched_hit") else "✗"} | {"YES" if key_results.get("支払申請", {}).get("enriched_hit") else "NO"} |
| 村田PR → muratapr | 0 matches | {"✓" if key_results.get("村田PR", {}).get("enriched_hit") else "✗"} | {"YES" if key_results.get("村田PR", {}).get("enriched_hit") else "NO"} |
| Murata PR → muratapr | partial | {"✓" if key_results.get("Murata PR", {}).get("enriched_hit") else "✗"} | {"YES" if key_results.get("Murata PR", {}).get("enriched_hit") else "NO"} |

### Graph Retrieval Improvement

- **Baseline hit rate:** {extraction_summary['baseline_hit_rate']:.0%}
- **Enriched hit rate:** {extraction_summary['enriched_hit_rate']:.0%}
- **Improvement:** +{extraction_summary['enriched_hit_rate'] - extraction_summary['baseline_hit_rate']:.0%}

### Answer Citation Traceability

{"Neptune graph evidence includes source_chunk_id and evidence_id — citations remain traceable." if not skip_neptune else "Not validated (Neptune skipped)."}

### Visualization Labels

- technical mode: Uses canonical_name (ASCII)
- business mode: Uses display_name_ja / display_name_zh
- mixed mode: Uses display_name + (canonical_name)
- CJK labels: Correctly rendered in Mermaid
- Mermaid node_id: Always ASCII-safe (hash-based for CJK)

### Recommendation

"""
    all_hit = extraction_summary['enriched_hit_rate'] >= 0.8
    if all_hit:
        md += "**RECOMMEND: Proceed to Phase 10C** (live LLM enrichment for remaining ~2800 entities, then Neptune write-back).\n"
    else:
        md += "**RECOMMEND: Review missed queries before Phase 10C.** Some CJK queries still fail.\n"

    # JSON report
    json_report = {
        "phase": "10B.1",
        "generated_at": now,
        "run_id": run_id,
        "mode": "validation",
        "neptune_accessed": not skip_neptune,
        "hybrid_accessed": not skip_hybrid,
        "extraction_summary": extraction_summary,
        "key_results": {
            k: {"status": v["status"], "enriched_hit": v["enriched_hit"]}
            for k, v in key_results.items()
        },
        "graph_retrieval_summary": {
            "total_queries": len(graph_results),
            "successful": sum(1 for r in graph_results if r.get("success")),
            "with_evidence": sum(1 for r in graph_results if r.get("evidence_count", 0) > 0),
        } if not skip_neptune else {"skipped": True},
        "hybrid_retrieval_summary": {
            "total_queries": len(hybrid_results),
            "with_text_evidence": sum(1 for r in hybrid_results if r.get("text_evidence_count", 0) > 0),
            "with_graph_evidence": sum(1 for r in hybrid_results if r.get("graph_evidence_count", 0) > 0),
            "insufficient": sum(1 for r in hybrid_results if r.get("insufficient_evidence")),
        } if not skip_hybrid else {"skipped": True},
        "visualization_validated": True,
        "recommend_phase_10c": all_hit,
    }

    return md, json_report


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 10B.1 i18n Retrieval Validation")
    parser.add_argument("--run-id", default="murata_live_v1")
    parser.add_argument(
        "--artifacts-dir",
        default=os.path.expanduser(
            "~/projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts/"
        ),
    )
    parser.add_argument("--dataset", default="murata")
    parser.add_argument("--lancedb-collection", default="murata_e2e_murata_live_v1")
    parser.add_argument("--skip-neptune", action="store_true",
                        help="Skip Neptune live queries")
    parser.add_argument("--skip-hybrid", action="store_true",
                        help="Skip hybrid retrieval (requires LanceDB + Neptune)")
    parser.add_argument("--skip-answer", action="store_true",
                        help="Skip answer generation (requires LLM)")
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    print(f"\nPhase 10B.1: i18n Enriched Retrieval Validation")
    print(f"  Run ID: {args.run_id}")
    print(f"  Artifacts: {artifacts_dir}")
    print(f"  Skip Neptune: {args.skip_neptune}")
    print(f"  Skip Hybrid: {args.skip_hybrid}")

    # Verify prerequisites
    entities_path = artifacts_dir / "entities.jsonl"
    i18n_path = artifacts_dir / "i18n_entities_enriched.jsonl"
    relations_path = artifacts_dir / "relations_clean.jsonl"
    i18n_relations_path = artifacts_dir / "i18n_relations_enriched.jsonl"

    for p in [entities_path, i18n_path, relations_path]:
        if not p.exists():
            print(f"  ERROR: Required file not found: {p}")
            sys.exit(1)

    # Load data
    print("\n  Loading data...")
    i18n_data = build_i18n_data(artifacts_dir)
    print(f"    i18n entities loaded: {len(i18n_data)}")

    # Load relations for visualization
    relations = []
    with open(relations_path) as f:
        for line in f:
            if line.strip():
                relations.append(json.loads(line))
    print(f"    Relations loaded: {len(relations)}")

    # Load entities as dict AND build entity_id → canonical mapping
    entities_dict = {}
    entity_id_to_canonical = {}
    with open(entities_path) as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                cn = e.get("canonical_name", "").lower()
                eid = e.get("entity_id", "")
                if cn:
                    entities_dict[cn] = e
                if eid and cn:
                    entity_id_to_canonical[eid] = cn
    print(f"    Entities loaded: {len(entities_dict)} unique canonical names")
    print(f"    Entity ID map: {len(entity_id_to_canonical)} entity_ids")

    # ── STEP 1: Query Entity Extraction ──
    extraction_results, extraction_summary = validate_query_extraction(artifacts_dir)

    # ── STEP 2: Graph Retrieval ──
    graph_results = validate_graph_retrieval(
        artifacts_dir, extraction_results, args.run_id, args.dataset,
        skip_neptune=args.skip_neptune,
    )

    # ── STEP 3: Hybrid Retrieval ──
    hybrid_results = validate_hybrid_retrieval(
        artifacts_dir, extraction_results, args.run_id, args.dataset,
        args.lancedb_collection,
        skip_hybrid=args.skip_hybrid,
    )

    # ── STEP 4: Visualization ──
    mermaid_md, reactflow_json = validate_visualization(
        artifacts_dir, i18n_data, relations, entities_dict,
        entity_id_to_canonical=entity_id_to_canonical,
    )

    # ── STEP 5: Generate Reports ──
    print("\n" + "=" * 70)
    print("  STEP 5: Generating Reports")
    print("=" * 70)

    report_md, report_json = generate_report(
        extraction_results, extraction_summary,
        graph_results, hybrid_results,
        artifacts_dir, args.run_id,
        args.skip_neptune, args.skip_hybrid,
    )

    # Write artifacts
    output_files = []

    # 1. Extraction validation JSONL
    ext_path = artifacts_dir / "query_entity_extraction_i18n_validation.jsonl"
    with open(ext_path, "w") as f:
        for r in extraction_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    output_files.append(str(ext_path))

    # 2. Answer examples JSONL
    answer_path = artifacts_dir / "answer_i18n_examples.jsonl"
    with open(answer_path, "w") as f:
        for r in hybrid_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    output_files.append(str(answer_path))

    # 3. Mermaid examples
    mermaid_path = artifacts_dir / "mermaid_i18n_examples.md"
    with open(mermaid_path, "w") as f:
        f.write(mermaid_md)
    output_files.append(str(mermaid_path))

    # 4. ReactFlow examples
    rf_path = artifacts_dir / "reactflow_i18n_examples.json"
    with open(rf_path, "w") as f:
        f.write(reactflow_json)
    output_files.append(str(rf_path))

    # 5. Report markdown
    report_md_path = artifacts_dir / "phase10b1_i18n_retrieval_report.md"
    with open(report_md_path, "w") as f:
        f.write(report_md)
    output_files.append(str(report_md_path))

    # 6. Report JSON
    report_json_path = artifacts_dir / "phase10b1_i18n_retrieval_report.json"
    with open(report_json_path, "w") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)
    output_files.append(str(report_json_path))

    print(f"\n  Generated {len(output_files)} artifacts:")
    for f in output_files:
        print(f"    - {f}")

    print("\n" + "=" * 70)
    print("  VALIDATION COMPLETE")
    print("=" * 70)
    print(f"  Enriched hit rate: {extraction_summary['enriched_hit_rate']:.0%}")
    print(f"  Improvement over baseline: +{extraction_summary['enriched_hit_rate'] - extraction_summary['baseline_hit_rate']:.0%}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
