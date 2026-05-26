"""
V2 QA Prompts — Structured prompt templates for answer generation.

Assembles business graph context, implementation graph context, evidence context,
and reasoning constraints into a prompt suitable for LLM answer generation.
"""

from __future__ import annotations

from typing import Any

from hermes_bedrock_agent.v2.schemas.retrieval_schema import HybridContext


# System prompt for the QA answer generator
SYSTEM_PROMPT = """\
You are an enterprise knowledge graph QA assistant for the Murata MDW project.

Your knowledge is structured into three layers:
1. Business Semantic Graph — business domains, processes, steps, rules, terms, functions, screens, roles
2. Implementation Graph — systems, modules, services, tables, columns, SQL, files, classes, methods, configs
3. Vector Evidence Store — original document evidence chunks with source citations

Rules:
- Answer ONLY using the provided context. Do not invent information.
- If API documentation is not available, say so explicitly.
- If evidence is insufficient, clearly state what is missing.
- Mention source references (source_path, chunk_id) to support claims.
- For business process questions, prioritize Business Graph Context.
- For technical/code/SQL questions, prioritize Implementation Graph Context.
- Structure your answer clearly with headings or bullet points when appropriate.
- Match the query language: Japanese query → Japanese answer, Chinese → Chinese, English → English.
- If the answer relies on heuristic graph extraction, note the confidence limitation.

Evidence Coverage Rules:
- If the question asks about nodes/edges without evidence, evidence coverage, or missing evidence:
  1. First report the actual evidence coverage statistics from [Known Limitations] or constraints.
  2. Do NOT say that nodes lack evidence if the stats show 0 nodes without evidence links.
  3. Clearly distinguish between:
     (a) missing evidence LINKS (structural gap in graph-to-chunk references)
     (b) weak evidence quality (evidence exists but is shallow)
     (c) missing source documents (e.g. no API docs in corpus)
     (d) isolated nodes (have evidence but few relationships)
  4. If nodes_without_evidence_links = 0, say explicitly:
     "当前图谱中没有缺少 evidence link 的节点。" (or equivalent in query language)
  5. Then explain what needs manual supplement: missing docs, quality gaps, alias review.
"""


def build_qa_prompt(context: HybridContext) -> str:
    """Build a complete QA prompt from HybridContext.

    Returns a structured prompt string ready for LLM consumption.
    """
    sections: list[str] = []

    # Question
    sections.append(f"[Question]\n{context.query}")

    # Intent
    intent = context.metadata.get('intent', 'unknown')
    sections.append(f"[Query Intent]\n{intent}")

    # Business Graph Context
    biz_items = context.business_context
    if biz_items:
        biz_lines = _format_business_context(biz_items)
        sections.append(f"[Business Graph Context]\n{biz_lines}")
    else:
        sections.append("[Business Graph Context]\nNo matching business graph nodes found.")

    # Implementation Graph Context
    impl_items = context.implementation_context
    if impl_items:
        impl_lines = _format_implementation_context(impl_items)
        sections.append(f"[Implementation Graph Context]\n{impl_lines}")
    else:
        sections.append("[Implementation Graph Context]\nNo matching implementation graph nodes found.")

    # Evidence Context
    evi_items = context.evidence_context
    if evi_items:
        evi_lines = _format_evidence_context(evi_items)
        sections.append(f"[Evidence Context]\n{evi_lines}")
    else:
        sections.append("[Evidence Context]\nNo evidence chunks retrieved.")

    # Known Limitations
    constraints = context.reasoning_constraints
    if constraints:
        limitations = "\n".join(f"- {c}" for c in constraints)
        sections.append(f"[Known Limitations]\n{limitations}")

    # Answer instructions
    sections.append(
        "[Answer Instructions]\n"
        "- Answer using the context above.\n"
        "- Cite source_path or chunk_id when referencing evidence.\n"
        "- If information is missing, state what is needed.\n"
        "- Match the language of the question."
    )

    return "\n\n".join(sections)


def _format_business_context(items: list[dict[str, Any]]) -> str:
    """Format business context items into readable text."""
    lines: list[str] = []
    nodes_seen: set[str] = set()
    edges: list[dict[str, Any]] = []

    for item in items:
        itype = item.get('type', '')
        if itype == 'business_node':
            nid = item.get('node_id', '')
            if nid in nodes_seen:
                continue
            nodes_seen.add(nid)
            label = item.get('label', '')
            name = item.get('display_name') or item.get('name', '')
            aliases = item.get('aliases', [])
            rel_ctx = item.get('relation_context', '')
            line = f"  [{label}] {name}"
            if aliases:
                line += f" (aliases: {', '.join(str(a) for a in aliases[:3])})"
            if rel_ctx:
                line += f" — via {rel_ctx}"
            lines.append(line)
        elif itype == 'business_edge':
            edges.append(item)

    if edges:
        lines.append("")
        lines.append("  Relationships:")
        for edge in edges[:10]:
            rel = edge.get('relation_type', '')
            src = edge.get('source_node_id', '')
            tgt = edge.get('target_node_id', '')
            lines.append(f"    {src} --[{rel}]--> {tgt}")

    return "\n".join(lines) if lines else "No business nodes matched."


def _format_implementation_context(items: list[dict[str, Any]]) -> str:
    """Format implementation context items into readable text."""
    lines: list[str] = []
    nodes_seen: set[str] = set()
    edges: list[dict[str, Any]] = []

    for item in items:
        itype = item.get('type', '')
        if itype == 'implementation_node':
            nid = item.get('node_id', '')
            if nid in nodes_seen:
                continue
            nodes_seen.add(nid)
            label = item.get('label', '')
            name = item.get('display_name') or item.get('name', '')
            aliases = item.get('aliases', [])
            rel_ctx = item.get('relation_context', '')
            line = f"  [{label}] {name}"
            if aliases:
                line += f" (aliases: {', '.join(str(a) for a in aliases[:3])})"
            if rel_ctx:
                line += f" — via {rel_ctx}"
            lines.append(line)
        elif itype == 'implementation_edge':
            edges.append(item)

    if edges:
        lines.append("")
        lines.append("  Relationships:")
        for edge in edges[:10]:
            rel = edge.get('relation_type', '')
            src = edge.get('source_node_id', '')
            tgt = edge.get('target_node_id', '')
            lines.append(f"    {src} --[{rel}]--> {tgt}")

    return "\n".join(lines) if lines else "No implementation nodes matched."


def _format_evidence_context(items: list[dict[str, Any]]) -> str:
    """Format evidence context items into readable text."""
    lines: list[str] = []

    for item in items:
        if item.get('type') != 'evidence_chunk':
            continue
        chunk_id = item.get('chunk_id', '')
        chunk_type = item.get('chunk_type', '')
        title = item.get('title', '')
        source_path = item.get('source_path', '')
        text = item.get('text', '')

        header = f"  [{chunk_type}] {title}"
        if source_path:
            header += f" (source: {source_path})"
        if chunk_id:
            header += f" [id: {chunk_id[:20]}...]"
        lines.append(header)
        if text:
            # Truncate evidence text for readability
            preview = text[:600].replace('\n', ' ').strip()
            lines.append(f"    {preview}")
        lines.append("")

    return "\n".join(lines) if lines else "No evidence chunks retrieved."


def build_no_llm_answer(context: HybridContext) -> str:
    """Build a deterministic answer preview without calling an LLM.

    Summarizes what the retriever found — useful for dry-run testing.
    For evidence_coverage intent, produces a factual stats-based answer.
    """
    intent = context.metadata.get('intent', 'unknown')

    # P0 fix: evidence_coverage intent gets a dedicated deterministic answer
    if intent == 'evidence_coverage':
        return _build_evidence_coverage_no_llm_answer(context)

    sections: list[str] = []

    intent = context.metadata.get('intent', 'unknown')
    sections.append(f"[Answer Mode: no_llm — deterministic preview]")
    sections.append(f"[Detected Intent: {intent}]")

    # Business context summary
    biz_nodes = [i for i in context.business_context if i.get('type') == 'business_node']
    biz_edges = [i for i in context.business_context if i.get('type') == 'business_edge']
    sections.append(
        f"\n[Business Graph Summary]\n"
        f"  Nodes: {len(biz_nodes)}\n"
        f"  Edges: {len(biz_edges)}"
    )
    for node in biz_nodes[:5]:
        sections.append(f"    - [{node.get('label', '')}] {node.get('display_name') or node.get('name', '')}")

    # Implementation context summary
    impl_nodes = [i for i in context.implementation_context if i.get('type') == 'implementation_node']
    impl_edges = [i for i in context.implementation_context if i.get('type') == 'implementation_edge']
    sections.append(
        f"\n[Implementation Graph Summary]\n"
        f"  Nodes: {len(impl_nodes)}\n"
        f"  Edges: {len(impl_edges)}"
    )
    for node in impl_nodes[:5]:
        sections.append(f"    - [{node.get('label', '')}] {node.get('display_name') or node.get('name', '')}")

    # Evidence summary
    evi_items = [i for i in context.evidence_context if i.get('type') == 'evidence_chunk']
    sections.append(
        f"\n[Evidence Summary]\n"
        f"  Chunks: {len(evi_items)}"
    )
    for chunk in evi_items[:3]:
        title = chunk.get('title', '')
        ctype = chunk.get('chunk_type', '')
        sections.append(f"    - [{ctype}] {title}")

    # Constraints
    if context.reasoning_constraints:
        sections.append("\n[Reasoning Constraints]")
        for c in context.reasoning_constraints:
            sections.append(f"  - {c}")

    return "\n".join(sections)


def _build_evidence_coverage_no_llm_answer(context: HybridContext) -> str:
    """Build deterministic no-LLM answer for evidence coverage questions (P0 fix).

    Uses actual stats from the HybridContext metadata to produce a factual answer.
    """
    from hermes_bedrock_agent.v2.retrieval.evidence_coverage_stats import (
        build_evidence_coverage_no_llm_answer,
    )

    stats = context.metadata.get('evidence_coverage_stats', {})
    if not stats:
        # Fallback: stats not available, provide a generic message
        return (
            "[Answer Mode: no_llm — evidence_coverage]\n"
            "Evidence coverage statistics are not available. "
            "Please ensure graph_nodes_linked.jsonl and graph_edges_linked.jsonl exist."
        )

    # Detect language from query
    query = context.query
    language = 'zh'  # default
    # Simple heuristic: check for Japanese-specific characters
    import re
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', query):
        language = 'ja'
    elif not re.search(r'[\u4e00-\u9fff]', query):
        language = 'en'

    answer = build_evidence_coverage_no_llm_answer(stats, language)
    return f"[Answer Mode: no_llm — evidence_coverage]\n[Detected Intent: evidence_coverage]\n\n{answer}"

