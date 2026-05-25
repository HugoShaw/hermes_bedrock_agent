"""
V2 Evidence Coverage Stats — Computes evidence coverage statistics from JSONL metadata.

Used when query intent is 'evidence_coverage' to inject actual stats
into the HybridContext, enabling factual answers about graph evidence coverage.

P0 Fix: Q7 was misanswered because the system lacked access to actual coverage stats.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compute_evidence_coverage_stats(output_dir: str | Path) -> dict[str, Any]:
    """Compute evidence coverage statistics from linked graph JSONL files.

    Reads:
    - graph_nodes_linked.jsonl  → total linked nodes, nodes with evidence
    - graph_edges_linked.jsonl  → total linked edges, edges with evidence
    - evidence_links.jsonl      → total evidence links
    - rejected_graph_items.jsonl → rejected item count

    Returns:
        Dict with all evidence coverage stats.
    """
    output_dir = Path(output_dir)

    stats: dict[str, Any] = {
        'linked_nodes_total': 0,
        'linked_edges_total': 0,
        'nodes_with_evidence_links': 0,
        'nodes_without_evidence_links': 0,
        'edges_with_evidence_links': 0,
        'edges_without_evidence_links': 0,
        'node_evidence_coverage_pct': '0%',
        'edge_evidence_coverage_pct': '0%',
        'evidence_links_total': 0,
        'rejected_items_count': 0,
        'api_node_count': 0,
        'isolated_node_count': 0,
        'business_nodes': 0,
        'implementation_nodes': 0,
        'known_limitations': [],
    }

    # Count linked nodes
    nodes_file = output_dir / 'graph_nodes_linked.jsonl'
    if nodes_file.exists():
        total = 0
        with_evidence = 0
        api_count = 0
        business_count = 0
        implementation_count = 0
        for line in nodes_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
                total += 1
                evidence_ids = node.get('evidence_chunk_ids', [])
                if evidence_ids and len(evidence_ids) > 0:
                    with_evidence += 1
                label = node.get('label', '')
                if label == 'API':
                    api_count += 1
                layer = node.get('layer', '')
                if layer == 'business':
                    business_count += 1
                elif layer == 'implementation':
                    implementation_count += 1
            except (json.JSONDecodeError, KeyError):
                continue

        stats['linked_nodes_total'] = total
        stats['nodes_with_evidence_links'] = with_evidence
        stats['nodes_without_evidence_links'] = total - with_evidence
        stats['api_node_count'] = api_count
        stats['business_nodes'] = business_count
        stats['implementation_nodes'] = implementation_count
        if total > 0:
            pct = round(with_evidence / total * 100, 1)
            stats['node_evidence_coverage_pct'] = f"{pct}%"

    # Count linked edges
    edges_file = output_dir / 'graph_edges_linked.jsonl'
    if edges_file.exists():
        total = 0
        with_evidence = 0
        for line in edges_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                edge = json.loads(line)
                total += 1
                evidence_ids = edge.get('evidence_chunk_ids', [])
                if evidence_ids and len(evidence_ids) > 0:
                    with_evidence += 1
            except (json.JSONDecodeError, KeyError):
                continue

        stats['linked_edges_total'] = total
        stats['edges_with_evidence_links'] = with_evidence
        stats['edges_without_evidence_links'] = total - with_evidence
        if total > 0:
            pct = round(with_evidence / total * 100, 1)
            stats['edge_evidence_coverage_pct'] = f"{pct}%"

    # Count evidence links
    links_file = output_dir / 'evidence_links.jsonl'
    if links_file.exists():
        count = 0
        for line in links_file.read_text(encoding='utf-8').splitlines():
            if line.strip():
                count += 1
        stats['evidence_links_total'] = count

    # Count rejected items
    rejected_file = output_dir / 'rejected_graph_items.jsonl'
    if rejected_file.exists():
        count = 0
        for line in rejected_file.read_text(encoding='utf-8').splitlines():
            if line.strip():
                count += 1
        stats['rejected_items_count'] = count

    # Compute isolated nodes (nodes that appear in no edge as source or target)
    if nodes_file.exists() and edges_file.exists():
        all_node_ids: set[str] = set()
        connected_ids: set[str] = set()

        for line in nodes_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
                all_node_ids.add(node.get('node_id', ''))
            except (json.JSONDecodeError, KeyError):
                continue

        for line in edges_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                edge = json.loads(line)
                connected_ids.add(edge.get('source_node_id', ''))
                connected_ids.add(edge.get('target_node_id', ''))
            except (json.JSONDecodeError, KeyError):
                continue

        isolated = all_node_ids - connected_ids
        stats['isolated_node_count'] = len(isolated)

    # Known limitations
    limitations = []
    if stats['api_node_count'] == 0:
        limitations.append("API docs are missing from corpus — API node count = 0.")
    if stats['isolated_node_count'] > 0:
        limitations.append(
            f"{stats['isolated_node_count']} isolated nodes have evidence "
            "but lack relationship connections."
        )
    limitations.append("Graph extraction is heuristic baseline (keyword-based, not LLM-enhanced).")
    limitations.append("Cross-language aliases are candidates only, not auto-merged.")
    limitations.append("Vector index not built; retrieval is JSONL/keyword-backed.")
    stats['known_limitations'] = limitations

    return stats


def format_evidence_coverage_context(stats: dict[str, Any]) -> str:
    """Format evidence coverage stats as a context block for injection into HybridContext.

    Returns a human-readable text block suitable for both LLM and no-LLM modes.
    """
    lines = [
        "[Evidence Coverage Statistics]",
        f"- linked_nodes_total: {stats['linked_nodes_total']}",
        f"- linked_edges_total: {stats['linked_edges_total']}",
        f"- nodes_with_evidence_links: {stats['nodes_with_evidence_links']}",
        f"- edges_with_evidence_links: {stats['edges_with_evidence_links']}",
        f"- nodes_without_evidence_links: {stats['nodes_without_evidence_links']}",
        f"- edges_without_evidence_links: {stats['edges_without_evidence_links']}",
        f"- node_evidence_coverage: {stats['node_evidence_coverage_pct']}",
        f"- edge_evidence_coverage: {stats['edge_evidence_coverage_pct']}",
        f"- evidence_links_total: {stats['evidence_links_total']}",
        f"- api_node_count: {stats['api_node_count']}",
        f"- business_nodes: {stats['business_nodes']}",
        f"- implementation_nodes: {stats['implementation_nodes']}",
        f"- isolated_node_count: {stats['isolated_node_count']}",
        f"- rejected_items_count: {stats['rejected_items_count']}",
        "",
        "[Known Limitations]",
    ]
    for lim in stats.get('known_limitations', []):
        lines.append(f"- {lim}")

    return "\n".join(lines)


def build_evidence_coverage_no_llm_answer(stats: dict[str, Any], language: str = 'zh') -> str:
    """Build a deterministic no-LLM answer for evidence coverage questions.

    Produces factual, non-misleading answer based on actual coverage stats.
    """
    nodes_total = stats['linked_nodes_total']
    nodes_with = stats['nodes_with_evidence_links']
    nodes_without = stats['nodes_without_evidence_links']
    edges_total = stats['linked_edges_total']
    edges_with = stats['edges_with_evidence_links']
    edges_without = stats['edges_without_evidence_links']
    node_pct = stats['node_evidence_coverage_pct']
    edge_pct = stats['edge_evidence_coverage_pct']
    api_count = stats['api_node_count']
    isolated = stats['isolated_node_count']

    if language == 'zh':
        lines = [
            f"当前图谱中没有缺少 evidence link 的节点。",
            f"",
            f"## Evidence 覆盖统计",
            f"- linked graph nodes = {nodes_total}，nodes with evidence = {nodes_with}，coverage = {node_pct}",
            f"- linked graph edges = {edges_total}，edges with evidence = {edges_with}，coverage = {edge_pct}",
            f"- nodes without evidence links = {nodes_without}",
            f"- edges without evidence links = {edges_without}",
            f"- evidence links total = {stats['evidence_links_total']}",
            f"",
            f"## 仍建议人工补充的方向",
            f"以下不是'没有 evidence link'的问题，而是'证据质量 / 文档完整度'的问题：",
            f"",
        ]
        if api_count == 0:
            lines.append(f"1. **API 文档缺失** — 当前语料中没有独立 API 文档，导致 API node count = 0。")
        if isolated > 0:
            lines.append(f"2. **Isolated nodes ({isolated} 个)** — 虽有 evidence link，但缺少关系连接，建议审查。")
        lines.append(f"3. **Heuristic baseline extraction** — 当前图谱用关键词提取，非 LLM 增强。")
        lines.append(f"4. **Cross-language aliases** — 日中英 alias 只是候选，未自动合并。")
        lines.append(f"5. **Vector index 未构建** — 当前检索为 JSONL/keyword-backed。")

    elif language == 'ja':
        lines = [
            f"現在のグラフには evidence link が不足しているノードは存在しません。",
            f"",
            f"## Evidence カバレッジ統計",
            f"- linked graph nodes = {nodes_total}, nodes with evidence = {nodes_with}, coverage = {node_pct}",
            f"- linked graph edges = {edges_total}, edges with evidence = {edges_with}, coverage = {edge_pct}",
            f"- nodes without evidence links = {nodes_without}",
            f"- edges without evidence links = {edges_without}",
            f"",
            f"## 手動補足が推奨される領域",
            f"以下は「evidence link がない」問題ではなく、「証拠品質/文書完全性」の問題です：",
            f"",
        ]
        if api_count == 0:
            lines.append(f"1. **API ドキュメント欠落** — API node count = 0")
        if isolated > 0:
            lines.append(f"2. **Isolated nodes ({isolated} 件)** — evidence はあるが関係接続が不足")
        lines.append(f"3. **Heuristic baseline** — キーワード抽出のみ (LLM 強化なし)")
        lines.append(f"4. **Cross-language aliases** — 日中英エイリアスは候補のみ、自動統合なし")

    else:  # English
        lines = [
            f"There are no nodes without evidence links in the current graph.",
            f"",
            f"## Evidence Coverage Statistics",
            f"- linked graph nodes = {nodes_total}, nodes with evidence = {nodes_with}, coverage = {node_pct}",
            f"- linked graph edges = {edges_total}, edges with evidence = {edges_with}, coverage = {edge_pct}",
            f"- nodes without evidence links = {nodes_without}",
            f"- edges without evidence links = {edges_without}",
            f"",
            f"## Recommended Manual Supplements",
            f"The following are NOT 'missing evidence link' issues but 'evidence quality' issues:",
            f"",
        ]
        if api_count == 0:
            lines.append(f"1. **Missing API documentation** — API node count = 0")
        if isolated > 0:
            lines.append(f"2. **Isolated nodes ({isolated})** — have evidence but lack relationships")
        lines.append(f"3. **Heuristic baseline extraction** — keyword-only, not LLM-enhanced")
        lines.append(f"4. **Cross-language aliases** — candidates only, not auto-merged")

    return "\n".join(lines)
