"""QA retriever with evidence tracing.

Takes a user query, retrieves top-K chunks from LanceDB, and optionally
traverses Neptune graph for related entities. Returns structured response
with PDF evidence paths for every retrieved chunk.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .config import config
from .schemas import GraphContext, QAAnswerResponse, QAResponse, RetrievedChunk
from .vector_store_loader import query_vector_store

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    top_k: int = 5,
    include_graph: bool = True,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
) -> QAResponse:
    """Retrieve top-K chunks and optional graph context for a query.

    Args:
        query: Natural language query (Japanese or English).
        top_k: Number of vector-search results to return.
        include_graph: Whether to also query Neptune for related entities.
        store_path: LanceDB path override.
        collection: LanceDB collection name override.

    Returns:
        QAResponse with chunks, evidence_paths, and optional graph_context.
    """
    # ── Vector retrieval ──────────────────────────────────────────────────────
    raw_results = query_vector_store(
        query_text=query,
        top_k=top_k,
        store_path=store_path,
        collection=collection,
    )

    chunks: list[RetrievedChunk] = []
    evidence_paths: list[str] = []

    for row in raw_results:
        # LanceDB returns _distance (L2) — convert to score (lower = better)
        distance = row.get("_distance", 0.0)
        score = max(0.0, 1.0 - distance)  # approximate cosine-like score

        pdf_path = row.get("source_pdf_s3_path", "")
        chunk = RetrievedChunk(
            chunk_id=row.get("id", ""),
            content=row.get("text", ""),
            chunk_type=row.get("chunk_type", ""),
            sheet_index=row.get("sheet_index", 0),
            sheet_name=row.get("sheet_name", ""),
            score=round(score, 4),
            source_pdf_s3_path=pdf_path,
            source_excel_s3_path=row.get("source_excel_s3_path", ""),
        )
        chunks.append(chunk)

        if pdf_path and pdf_path not in evidence_paths:
            evidence_paths.append(pdf_path)

    # ── Graph context (optional) ──────────────────────────────────────────────
    graph_context: Optional[GraphContext] = None
    if include_graph and chunks:
        graph_context = _fetch_graph_context(chunks, query=query)

    return QAResponse(
        query=query,
        chunks=chunks,
        evidence_paths=evidence_paths,
        graph_context=graph_context,
    )


_SYSTEM_KEYWORDS = [
    "SAP", "S4/HANA", "S4HANA", "S/4HANA",
    "DataSpider", "ANDPAD",
    "中間F", "中間ファイル", "NTT DATA", "NTTDATA",
]
_API_PATTERN = re.compile(r"(GET|POST|PUT|DELETE|PATCH)\s+/\S+", re.IGNORECASE)


def _extract_entity_names(texts: list[str]) -> list[str]:
    """Extract system names and API paths from free text.

    Uses case-insensitive substring matching (not word-boundary regex)
    because Japanese text adjacent to Latin keywords breaks \\b anchors.
    """
    found: set[str] = set()
    combined = " ".join(texts)
    combined_lower = combined.lower()
    for kw in _SYSTEM_KEYWORDS:
        if kw.lower() in combined_lower:
            found.add(kw)
    for m in _API_PATTERN.finditer(combined):
        found.add(m.group(0).strip())
    return list(found)


def _node_from_row(node_data: dict) -> dict:
    """Normalise a Neptune node dict into our storage format.

    Neptune Analytics returns nodes as:
        {"~id": ..., "~labels": [...], "~properties": {...}}
    The properties dict contains name, node_id, sheet_index, etc.
    """
    nid = node_data.get("~id", node_data.get("node_id", ""))
    labels = node_data.get("~labels", [])
    label = labels[0] if labels else ""
    # Neptune nests properties under ~properties
    props = node_data.get("~properties", {})
    if not props:
        # Fallback: older format might have top-level keys
        props = {k: v for k, v in node_data.items() if not k.startswith("~")}
    return {"id": nid, "label": label, "properties": props}


def _fetch_graph_context(chunks: list[RetrievedChunk], query: str = "") -> Optional[GraphContext]:
    """Multi-strategy Neptune traversal to build rich graph context.

    Strategy A: Sheet-level expansion for retrieved sheet indices.
    Strategy B: Entity-name search from chunk text + query.
    Strategy C: Data-flow paths between systems mentioned in the query.
    """
    try:
        from hermes_bedrock_agent.clients.neptune_client import NeptuneClient

        client = NeptuneClient()
        if not client.is_configured:
            return None

        seen_nodes: set[str] = set()
        seen_edges: set[tuple] = set()
        nodes: list[dict] = []
        edges: list[dict] = []

        def _add_node(nd: dict) -> None:
            nid = nd["id"]
            if nid and nid not in seen_nodes:
                seen_nodes.add(nid)
                nodes.append(nd)

        def _add_edge(from_id: str, to_id: str, rel: str) -> None:
            key = (from_id, to_id, rel)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"from": from_id, "to": to_id, "relationship": rel})

        # ── Strategy A: Sheet-level neighbourhood ─────────────────────────────
        sheet_indices = list({c.sheet_index for c in chunks if c.sheet_index > 0})[:5]
        if sheet_indices:
            idx_list = ", ".join(str(i) for i in sheet_indices)
            cypher_a = (
                f"MATCH (s:Sheet)-[r]-(n) "
                f"WHERE s.sheet_index IN [{idx_list}] "
                f"RETURN s, type(r) AS rel, n "
                f"LIMIT 80"
            )
            rows_a = client.execute_query(cypher_a).get("results", [])
            for row in rows_a:
                s_nd = _node_from_row(row.get("s", {}))
                n_nd = _node_from_row(row.get("n", {}))
                rel  = row.get("rel", "")
                _add_node(s_nd)
                _add_node(n_nd)
                if s_nd["id"] and n_nd["id"]:
                    _add_edge(s_nd["id"], n_nd["id"], rel)

        # ── Strategy B: Entity-name search ────────────────────────────────────
        chunk_texts = [c.content for c in chunks]
        if query:
            chunk_texts.append(query)
        entity_names = _extract_entity_names(chunk_texts)

        for name in entity_names[:8]:  # cap to avoid too many round-trips
            safe = name.replace("'", "\\'")
            cypher_b = (
                f"MATCH (n) WHERE toLower(n.name) CONTAINS toLower('{safe}') "
                f"WITH n LIMIT 5 "
                f"MATCH (n)-[r]-(m) "
                f"RETURN n, type(r) AS rel, m "
                f"LIMIT 30"
            )
            try:
                rows_b = client.execute_query(cypher_b).get("results", [])
            except Exception:
                continue
            for row in rows_b:
                n_nd = _node_from_row(row.get("n", {}))
                m_nd = _node_from_row(row.get("m", {}))
                rel  = row.get("rel", "")
                _add_node(n_nd)
                _add_node(m_nd)
                if n_nd["id"] and m_nd["id"]:
                    _add_edge(n_nd["id"], m_nd["id"], rel)

        # ── Strategy C: System-level data flow paths ──────────────────────────
        cypher_c = (
            "MATCH (a:System)-[r:FLOWS_TO]->(b:System) "
            "RETURN a, type(r) AS rel, b "
            "LIMIT 20"
        )
        try:
            rows_c = client.execute_query(cypher_c).get("results", [])
        except Exception:
            rows_c = []
        for row in rows_c:
            a_nd = _node_from_row(row.get("a", {}))
            b_nd = _node_from_row(row.get("b", {}))
            rel  = row.get("rel", "")
            _add_node(a_nd)
            _add_node(b_nd)
            if a_nd["id"] and b_nd["id"]:
                _add_edge(a_nd["id"], b_nd["id"], rel)

        # ── Cap total size ────────────────────────────────────────────────────
        if len(nodes) > 100:
            nodes = nodes[:100]
        if len(edges) > 150:
            edges = edges[:150]

        return GraphContext(nodes=nodes, edges=edges)

    except Exception as exc:
        logger.warning("Graph context fetch failed: %s", exc)
        return None


def answer(
    query: str,
    top_k: int = 5,
    include_graph: bool = True,
    include_evidence_images: bool = True,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
) -> QAAnswerResponse:
    """Retrieve chunks and generate a multimodal answer via Bedrock Converse.

    Args:
        query: Natural language query (Japanese or English).
        top_k: Number of vector-search results to retrieve.
        include_graph: Whether to include Neptune graph context.
        include_evidence_images: Whether to load and send PDF evidence images.
        store_path: LanceDB path override.
        collection: LanceDB collection name override.

    Returns:
        QAAnswerResponse with generated answer text and token usage.
    """
    from .answer_generator import generate_answer, load_evidence_images

    qa_resp = retrieve(
        query=query,
        top_k=top_k,
        include_graph=include_graph,
        store_path=store_path,
        collection=collection,
    )

    evidence_images: list = []
    if include_evidence_images and qa_resp.chunks:
        evidence_images = load_evidence_images(qa_resp.chunks)
        logger.info("Loaded %d evidence image(s)", len(evidence_images))

    return generate_answer(
        query=query,
        retrieved_chunks=qa_resp.chunks,
        evidence_images=evidence_images,
        graph_context=qa_resp.graph_context,
    )


def format_response(response: QAResponse, verbose: bool = False) -> str:
    """Format a QAResponse for human-readable terminal output."""
    lines: list[str] = []
    lines.append(f"\n── Query: {response.query}")
    lines.append(f"── Retrieved {len(response.chunks)} chunk(s)\n")

    for i, chunk in enumerate(response.chunks, 1):
        lines.append(f"[{i}] {chunk.sheet_name} (sheet {chunk.sheet_index}) — {chunk.chunk_type}")
        lines.append(f"    Score: {chunk.score:.4f}")
        lines.append(f"    Evidence PDF: {chunk.source_pdf_s3_path}")
        if verbose:
            preview = chunk.content[:300].replace("\n", " ")
            lines.append(f"    Content: {preview}...")
        lines.append("")

    if response.evidence_paths:
        lines.append("── Evidence PDFs:")
        for path in response.evidence_paths:
            lines.append(f"    {path}")
        lines.append("")

    if response.graph_context:
        lines.append(
            f"── Graph context: {len(response.graph_context.nodes)} nodes, "
            f"{len(response.graph_context.edges)} edges"
        )

    if isinstance(response, QAAnswerResponse):
        lines.append("")
        lines.append("── Generated Answer:")
        lines.append(response.answer)
        lines.append("")
        if response.evidence_images_used:
            lines.append("── Evidence images sent to model:")
            for p in response.evidence_images_used:
                lines.append(f"    {p}")
        lines.append(
            f"── Tokens: {response.input_tokens} in / {response.output_tokens} out"
            f"  |  Model: {response.model_id}"
        )

    return "\n".join(lines)


def main() -> None:
    """Interactive QA terminal for testing retrieval."""
    import argparse

    parser = argparse.ArgumentParser(description="Dual-RAG QA retriever")
    parser.add_argument("query", nargs="?", help="Query string (omit for interactive mode)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-graph", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output raw JSON")
    parser.add_argument(
        "--answer",
        action="store_true",
        help="Generate a multimodal answer using Bedrock Converse (text + PDF images)",
    )
    args = parser.parse_args()

    def _run(q: str) -> None:
        if args.answer:
            resp = answer(q, top_k=args.top_k, include_graph=not args.no_graph)
        else:
            resp = retrieve(q, top_k=args.top_k, include_graph=not args.no_graph)
        if args.as_json:
            print(resp.model_dump_json(indent=2))
        else:
            print(format_response(resp, verbose=args.verbose))

    if args.query:
        _run(args.query)
    else:
        print("Dual-RAG QA Retriever (type 'exit' to quit)")
        while True:
            try:
                q = input("\nQuery> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ("exit", "quit", "q"):
                break
            if q:
                _run(q)


if __name__ == "__main__":
    main()
