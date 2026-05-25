"""
Pipeline: Link Graph Evidence (Stage 08).

Orchestrates the full Stage 08 pipeline:
1. Load filtered graph nodes/edges
2. Load evidence chunks, documents, sections
3. Load entity aliases
4. Create evidence links
5. Validate links
6. Write outputs
7. Generate report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.graph_evidence_linker import GraphEvidenceLinker
from hermes_bedrock_agent.v2.graph.evidence_link_reporter import EvidenceLinkReporter


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file."""
    items = []
    if not path.exists():
        return items
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    """Write items to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def validate_links(
    linked_nodes: list[dict[str, Any]],
    linked_edges: list[dict[str, Any]],
    evidence_links: list[dict[str, Any]],
    chunk_ids: set[str],
    run_id: str,
    dataset: str,
) -> list[str]:
    """Validate evidence links. Returns list of errors (empty = valid)."""
    errors = []

    # Build indexes
    node_ids = {n["node_id"] for n in linked_nodes}
    edge_ids = {e["edge_id"] for e in linked_edges}
    all_item_ids = node_ids | edge_ids
    link_ids_seen = set()

    for link in evidence_links:
        lid = link["link_id"]

        # Unique link_id
        if lid in link_ids_seen:
            errors.append(f"Duplicate link_id: {lid}")
        link_ids_seen.add(lid)

        # Valid graph item reference
        if link["graph_item_id"] not in all_item_ids:
            errors.append(f"Link {lid}: graph_item_id '{link['graph_item_id']}' not in graph")

        # Valid evidence chunk reference
        if link["evidence_chunk_id"] not in chunk_ids:
            errors.append(f"Link {lid}: evidence_chunk_id '{link['evidence_chunk_id']}' not in chunks")

        # run_id / dataset
        if link.get("run_id") != run_id:
            errors.append(f"Link {lid}: bad run_id '{link.get('run_id')}'")
        if link.get("dataset") != dataset:
            errors.append(f"Link {lid}: bad dataset '{link.get('dataset')}'")

        # No JOURNAL_BASE dump links
        sp = (link.get("source_path") or "").lower()
        if "journal_base20180530" in sp and link.get("link_strategy") != "existing":
            errors.append(f"Link {lid}: points to JOURNAL_BASE dump via {link.get('link_strategy')}")

    # Every node has evidence
    for n in linked_nodes:
        ec = n.get("properties", {}).get("evidence_count", 0)
        if ec == 0:
            errors.append(f"Node {n['node_id']}: no evidence links")
        if n.get("run_id") != run_id:
            errors.append(f"Node {n['node_id']}: bad run_id")
        if n.get("dataset") != dataset:
            errors.append(f"Node {n['node_id']}: bad dataset")

    # Every edge has evidence
    for e in linked_edges:
        ec = e.get("properties", {}).get("evidence_count", 0)
        if ec == 0:
            errors.append(f"Edge {e['edge_id']}: no evidence links")
        if e.get("run_id") != run_id:
            errors.append(f"Edge {e['edge_id']}: bad run_id")
        if e.get("dataset") != dataset:
            errors.append(f"Edge {e['edge_id']}: bad dataset")

    return errors


def run_pipeline(
    output_dir: str | Path,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the full Stage 08 pipeline."""
    output_dir = Path(output_dir)

    # ======================================================================
    # Phase 1: Load inputs
    # ======================================================================
    print("[Stage 08] Loading inputs...")
    nodes = load_jsonl(output_dir / "filtered_graph_nodes.jsonl")
    edges = load_jsonl(output_dir / "filtered_graph_edges.jsonl")
    chunks = load_jsonl(output_dir / "evidence_chunks.jsonl")
    documents = load_jsonl(output_dir / "documents.jsonl")
    sections = load_jsonl(output_dir / "sections.jsonl")
    aliases = load_jsonl(output_dir / "entity_aliases.jsonl")

    print(f"  Filtered nodes: {len(nodes)}")
    print(f"  Filtered edges: {len(edges)}")
    print(f"  Evidence chunks: {len(chunks)}")
    print(f"  Documents: {len(documents)}")
    print(f"  Sections: {len(sections)}")
    print(f"  Aliases: {len(aliases)}")

    # ======================================================================
    # Phase 2: Evidence Linking
    # ======================================================================
    print("\n[Stage 08] Running evidence linker...")
    linker = GraphEvidenceLinker(
        nodes=nodes,
        edges=edges,
        chunks=chunks,
        documents=documents,
        sections=sections,
        aliases=aliases,
        run_id=run_id,
        dataset=dataset,
    )
    stats = linker.link()

    print(f"  Evidence links generated: {stats['evidence_link_count']}")
    print(f"  Node evidence coverage: {stats['node_evidence_ratio']:.2%}")
    print(f"  Edge evidence coverage: {stats['edge_evidence_ratio']:.2%}")
    print(f"  Avg evidence per node: {stats['avg_evidence_per_node']:.1f}")
    print(f"  Avg evidence per edge: {stats['avg_evidence_per_edge']:.1f}")
    print(f"  Link strategies: {stats['link_count_by_strategy']}")
    print(f"  JOURNAL_BASE dump links: {stats['journal_base_links']}")
    print(f"  SQL dump links: {stats['sql_dump_links']}")
    print(f"  API node count: {stats['api_node_count']}")

    if dry_run:
        print("\n[DRY-RUN] Would write outputs. Skipping final writes.")
        return {"mode": "dry_run", "stats": stats}

    # ======================================================================
    # Phase 3: Validation
    # ======================================================================
    print("\n[Stage 08] Validating evidence links...")
    chunk_ids = {c.get("chunk_id") for c in chunks}
    errors = validate_links(
        linker.linked_nodes, linker.linked_edges,
        linker.evidence_links, chunk_ids, run_id, dataset,
    )

    if errors:
        print(f"  ⚠️ Validation found {len(errors)} issues:")
        for e in errors[:10]:
            print(f"    - {e}")
    else:
        print("  ✅ All evidence links validated successfully")

    # ======================================================================
    # Phase 4: Write Outputs
    # ======================================================================
    print("\n[Stage 08] Writing outputs...")

    write_jsonl(output_dir / "graph_nodes_linked.jsonl", linker.linked_nodes)
    print(f"  → graph_nodes_linked.jsonl ({len(linker.linked_nodes)} records)")

    write_jsonl(output_dir / "graph_edges_linked.jsonl", linker.linked_edges)
    print(f"  → graph_edges_linked.jsonl ({len(linker.linked_edges)} records)")

    write_jsonl(output_dir / "evidence_links.jsonl", linker.evidence_links)
    print(f"  → evidence_links.jsonl ({len(linker.evidence_links)} records)")

    # ======================================================================
    # Phase 5: Generate Report
    # ======================================================================
    print("\n[Stage 08] Generating report...")
    reporter = EvidenceLinkReporter(
        stats=stats,
        linked_nodes=linker.linked_nodes,
        linked_edges=linker.linked_edges,
        evidence_links=linker.evidence_links,
        run_id=run_id,
        dataset=dataset,
    )
    report = reporter.generate_report()
    report_path = output_dir / "evidence_link_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  → evidence_link_report.md")

    # ======================================================================
    # Done
    # ======================================================================
    print(f"\n[Stage 08] COMPLETE")
    print(f"  Final: {len(linker.linked_nodes)} linked nodes, {len(linker.linked_edges)} linked edges")
    print(f"  Evidence links: {len(linker.evidence_links)}")
    print(f"  Coverage: nodes {stats['node_evidence_ratio']:.0%}, edges {stats['edge_evidence_ratio']:.0%}")
    if errors:
        print(f"  ⚠️ {len(errors)} validation warnings (see above)")

    return {
        "mode": "full",
        "stats": stats,
        "validation_errors": errors,
    }
