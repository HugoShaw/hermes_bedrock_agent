"""Interactive QA terminal for the dual-RAG pipeline."""

from __future__ import annotations

import csv
import os
import sys
import textwrap
import threading
import time
import shutil
from pathlib import Path
from typing import Optional

# ── ANSI codes ─────────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
CYAN    = "\033[36m"
BGREEN  = "\033[92m"
BYELLOW = "\033[93m"
BCYAN   = "\033[96m"
BWHITE  = "\033[97m"


def _c(text: str, *codes: str) -> str:
    return f"{''.join(codes)}{text}{RESET}"


def _rl(text: str, *codes: str) -> str:
    prefix = "".join(codes)
    return f"\001{prefix}\002{text}\001{RESET}\002"


def _tw() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def _divider(title: str = "", char: str = "─", color: str = DIM) -> str:
    w = min(_tw(), 80)
    if title:
        inner = f" {title} "
        side = max(0, (w - len(inner)) // 2)
        line = char * side + inner + char * max(0, w - side - len(inner))
    else:
        line = char * w
    return _c(line, color)


def _box(lines: list[str], width: int = 54) -> str:
    inner = width - 2
    rows = [f"╔{'═' * inner}╗"]
    for line in lines:
        if len(line) > inner:
            line = line[:inner - 1] + "…"
        rows.append(f"║{line.ljust(inner)}║")
    rows.append(f"╚{'═' * inner}╝")
    return "\n".join(rows)


def _score_bar(score: float, width: int = 10) -> str:
    filled = int(score * width)
    bar = "█" * filled + "░" * (width - filled)
    color = BGREEN if score >= 0.7 else (BYELLOW if score >= 0.5 else DIM)
    return _c(bar, color)


def _clear_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


class _Spinner:
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str):
        self._label = label
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()
        _clear_line()

    def _run(self):
        i = 0
        while not self._stop.wait(0.1):
            frame = self._FRAMES[i % len(self._FRAMES)]
            sys.stdout.write(f"\r{_c(frame, CYAN)} {self._label}  ")
            sys.stdout.flush()
            i += 1


class _Session:
    def __init__(self):
        self.mode: str = "retrieve"
        self.top_k: int = 5
        self.verbose: bool = False
        self.evidence: bool = True
        self.query_count: int = 0
        self.total_in_tok: int = 0
        self.total_out_tok: int = 0
        self.total_latency: float = 0.0
        self.history: list[str] = []
        self.last_query: Optional[str] = None
        self.last_ts: Optional[float] = None
        self.catalog: list[dict] = []
        self.catalog_dir: Optional[Path] = None
        self.project_id: str = ""
        # Debug/trace flags
        self.debug_retrieval: bool = False
        self.show_vector_trace: bool = False
        self.show_graph_trace: bool = False
        self.show_context: bool = False
        self.strict_isolation: bool = False
        self.graph_confidence_threshold: float = 0.0
        self.disable_keyword_boost: bool = False
        self.vector_only: bool = False
        self.last_trace: Optional["RetrievalTrace"] = None


def _load_catalog(catalog_dir: Optional[Path]) -> list[dict]:
    if catalog_dir is None:
        return []
    csv_path = catalog_dir / "sheet_name_mapping.csv"
    if not csv_path.exists():
        return []
    try:
        with open(csv_path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _sheet_content(catalog_dir: Path, sheet_1based: int) -> Optional[str]:
    vlm_dir = catalog_dir / "vlm_parsed"
    md = vlm_dir / f"sheet_{sheet_1based:02d}.md"
    return md.read_text(encoding="utf-8") if md.exists() else None


def _print_header(s: _Session, collection: str, model_id: str) -> None:
    ev = "ON" if s.evidence else "OFF"
    project_line = f"  Project: {s.project_id}" if s.project_id else "  Project: (all)"
    header = _c(_box([
        "  Dual-RAG QA Terminal",
        f"  Model: {model_id}",
        f"  Collection: {collection}",
        project_line,
        f"  Mode: {s.mode} | Top-K: {s.top_k} | Evidence: {ev}",
    ], width=54), BCYAN)
    print(header)


def _print_chunks(chunks, verbose: bool = False) -> None:
    print(_divider("Retrieved Chunks", "━", BCYAN))
    for i, chunk in enumerate(chunks, 1):
        hdr = _c(f"[{i}]", BOLD + BWHITE)
        sheet = _c(f"Sheet {chunk.sheet_index} / {chunk.sheet_name}", BCYAN)
        ctype = _c(f"Type: {chunk.chunk_type}", DIM)
        bar = _score_bar(chunk.score)
        score = _c(f"{chunk.score:.2f}", YELLOW)
        print(f"  {hdr} {sheet}")
        print(f"      {ctype} | Score: {bar} {score}")
        if chunk.source_pdf_s3_path:
            pdf = _c(chunk.source_pdf_s3_path.split("/")[-1], DIM)
            print(f"      {_c('PDF:', DIM)} {pdf}")
        if chunk.content:
            raw = chunk.content if verbose else chunk.content[:160]
            preview = (raw + "…" if not verbose else raw).replace("\n", " ")
            wrapped = textwrap.fill(preview, width=68, initial_indent="      ", subsequent_indent="      ")
            print(_c(wrapped, DIM))
        print()


def _print_graph(gc, title: str = "Graph Context", color: str = BYELLOW, neptune_available: bool = True) -> None:
    print(_divider(title, "━", color))
    if gc is None:
        if not neptune_available:
            print(_c("  (Neptune not available or not configured)", DIM))
        else:
            print(_c("  (No matching nodes found for this project)", DIM))
        print()
        return
    if not gc.nodes and not gc.edges:
        print(_c("  (No matching nodes found for this project)", DIM))
        print()
        return
    print(f"  {_c(f'Nodes: {len(gc.nodes)}', BYELLOW)}  {_c(f'Edges: {len(gc.edges)}', YELLOW)}")
    for node in gc.nodes[:10]:
        props = node.get("properties", {})
        name = props.get("name", props.get("sheet_name", ""))
        suffix = f" — {name}" if name else ""
        print(f"  {_c('●', YELLOW)} [{node.get('label', '')}] {node.get('id', '?')}{suffix}")
    if len(gc.nodes) > 10:
        print(_c(f"    … {len(gc.nodes) - 10} more nodes", DIM))
    for edge in gc.edges[:10]:
        print(f"  {_c('→', CYAN)} {edge.get('from', '?')} --{edge.get('relationship', '?')}--> {edge.get('to', '?')}")
    if len(gc.edges) > 10:
        print(_c(f"    … {len(gc.edges) - 10} more edges", DIM))
    print()


def _print_dual_graph(dual, neptune_available: bool = True) -> None:
    """Print two-layer graph context."""
    if dual is None:
        _print_graph(None, neptune_available=neptune_available)
        return
    if dual.is_empty:
        _print_graph(None, "Business Semantic Graph", BYELLOW, neptune_available=True)
        _print_graph(None, "Implementation Graph", BCYAN, neptune_available=True)
        return
    _print_graph(dual.business, "Business Semantic Graph", BYELLOW)
    _print_graph(dual.implementation, "Implementation Graph", BCYAN)


def _print_evidence_flow(chunks, dual_graph, evidence_images, elapsed: float, project_id: str = "") -> None:
    """Print evidence flow summary showing all sources used."""
    print(_divider("Evidence Flow Summary", "━", BGREEN))
    # Project scope
    if project_id:
        print(f"  {_c('Project scope:', BWHITE)} {_c(project_id, BCYAN)}")
    else:
        print(f"  {_c('Project scope:', BWHITE)} {_c('(ALL projects — no filter)', YELLOW)}")
    # Markdown chunks
    sheet_set = sorted({c.sheet_index for c in chunks if c.sheet_index > 0})
    print(f"  {_c('① Markdown chunks:', BWHITE)} {len(chunks)} chunks from sheets {sheet_set}")
    # Graph context
    if dual_graph and not dual_graph.is_empty:
        print(f"  {_c('② Business Graph:', BWHITE)} {len(dual_graph.business.nodes)} nodes, {len(dual_graph.business.edges)} edges")
        print(f"  {_c('③ Implementation Graph:', BWHITE)} {len(dual_graph.implementation.nodes)} nodes, {len(dual_graph.implementation.edges)} edges")
    else:
        print(f"  {_c('②③ Graph context:', BWHITE)} (not available)")
    # Evidence images
    if evidence_images:
        print(f"  {_c('④ Visual evidence:', BWHITE)} {len(evidence_images)} PDF/PNG page(s)")
        for label, _, path in evidence_images:
            print(f"     └─ {_c(label, DIM)}")
    else:
        print(f"  {_c('④ Visual evidence:', BWHITE)} (none loaded)")
    print(f"  {_c('Total retrieval time:', DIM)} {elapsed:.1f}s")
    print()


def _filter_graph_by_confidence(dual_graph, threshold: float):
    """Filter graph edges below confidence threshold.

    Status confidence mapping (higher = more confident):
        CONFIRMED = 1.0, CANDIDATE = 0.6, POSSIBLY_RELATED = 0.3, NEEDS_REVIEW = 0.1
    Edges without status are treated as 0.5 (pass at default thresholds).
    """
    _STATUS_SCORES = {
        "CONFIRMED": 1.0,
        "CANDIDATE": 0.6,
        "POSSIBLY_RELATED": 0.3,
        "NEEDS_REVIEW": 0.1,
    }

    def _passes(edge: dict) -> bool:
        status = (edge.get("properties") or {}).get("status", "")
        score = _STATUS_SCORES.get(status.upper(), 0.5)
        return score >= threshold

    # Filter both layers in-place (create new GraphContext objects)
    from ..knowledge_base.schemas import GraphContext

    biz = dual_graph.business
    impl = dual_graph.implementation

    filtered_biz_edges = [e for e in biz.edges if _passes(e)]
    filtered_impl_edges = [e for e in impl.edges if _passes(e)]

    removed = (len(biz.edges) - len(filtered_biz_edges)) + (len(impl.edges) - len(filtered_impl_edges))
    if removed > 0:
        print(f"  {_c(f'⚠ Filtered {removed} low-confidence edge(s) (threshold={threshold})', BYELLOW)}")

    dual_graph.business = GraphContext(nodes=biz.nodes, edges=filtered_biz_edges)
    dual_graph.implementation = GraphContext(nodes=impl.nodes, edges=filtered_impl_edges)
    return dual_graph


def _print_vector_trace(trace) -> None:
    """Print vector retrieval trace details."""
    print(_divider("Vector Trace", "─", CYAN))
    print(f"  {_c('Collection:', DIM)} {trace.collection}")
    print(f"  {_c('Project filter:', DIM)} {trace.project_filter or '(none)'}")
    if trace.sheet_filter:
        print(f"  {_c('Sheet filter:', DIM)} {trace.sheet_filter}")
    print(f"  {_c('Embedding model:', DIM)} {trace.embedding_model}")
    print(f"  {_c('Embedding latency:', DIM)} {trace.embedding_latency_ms:.1f}ms")
    print(f"  {_c('Search latency:', DIM)} {trace.search_latency_ms:.1f}ms")
    print(f"  {_c('Raw results:', DIM)} {trace.raw_results_count}")
    print(f"  {_c('Final chunks:', DIM)} {trace.final_chunks_count}")
    if trace.raw_results:
        print(f"  {_c('Top results (id / distance):', DIM)}")
        for r in trace.raw_results[:5]:
            dist = r.get("_distance", 0.0)
            rid = r.get("id", "?")[:40]
            ctype = r.get("chunk_type", "")
            print(f"    {_c(rid, BWHITE)}  dist={dist:.4f}  type={ctype}")
    if trace.keyword_boost_skipped:
        print(f"  {_c('Keyword boost:', BYELLOW)} DISABLED (--disable-keyword-boost)")
    elif trace.keyword_boost_applied:
        print(f"  {_c('Keyword boost applied:', DIM)} {len(trace.keyword_boost_applied)} chunk(s)")
        for b in trace.keyword_boost_applied[:5]:
            cid = b.get("chunk_id", "?")[:30]
            boost_val = b.get("boost", 0)
            kws = ", ".join(b.get("keywords_matched", [])[:3])
            print(f"    {_c(cid, DIM)} +{boost_val:.4f} [{kws}]")
    print()


def _print_graph_trace(trace) -> None:
    """Print graph retrieval trace details."""
    print(_divider("Graph Trace", "─", YELLOW))
    if trace.query_terms:
        terms_str = ", ".join(trace.query_terms[:8])
        print(f"  {_c('Query terms:', DIM)} {terms_str}")
    print(f"  {_c('Hint quality:', DIM)} {_c(trace.hint_quality.upper(), BGREEN if trace.hint_quality == 'strong' else BYELLOW if trace.hint_quality == 'weak' else DIM)}")
    if trace.hint_quality_reason:
        print(f"  {_c('Reason:', DIM)} {trace.hint_quality_reason}")
    if trace.sheet_expansion:
        print(f"  {_c('Sheet expansion:', DIM)} {trace.sheet_expansion}")
    if trace.system_expansion:
        print(f"  {_c('System expansion:', DIM)} {', '.join(trace.system_expansion)}")
    print(f"  {_c('Business layer:', DIM)} {trace.business_nodes} nodes, {trace.business_edges} edges")
    print(f"  {_c('Implementation layer:', DIM)} {trace.implementation_nodes} nodes, {trace.implementation_edges} edges")
    print(f"  {_c('Graph latency:', DIM)} {trace.graph_latency_ms:.1f}ms")
    if trace.edge_confidence_summary:
        print(f"  {_c('Edge confidence:', DIM)}")
        for status, count in trace.edge_confidence_summary.items():
            if count > 0:
                color = BGREEN if status == "confirmed" else (YELLOW if status == "no_status" else RED)
                print(f"    {_c(status, color)}: {count}")
    if trace.low_confidence_edges:
        print(f"  {_c('Low-confidence edges:', YELLOW)} {len(trace.low_confidence_edges)}")
        for e in trace.low_confidence_edges[:5]:
            rel = e.get("relationship", "?")
            src = e.get("from", "?")[:20]
            tgt = e.get("to", "?")[:20]
            props = e.get("properties", {})
            status = props.get("status", props.get("confidence_status", "?"))
            print(f"    {_c(src, DIM)} --{rel}--> {_c(tgt, DIM)} [{status}]")
    print()


def _print_timing_trace(trace) -> None:
    """Print per-stage timing breakdown."""
    print(_divider("Timing Breakdown", "─", BGREEN))
    stages = [
        ("Graph exploration", trace.graph_exploration_ms),
        ("Graph context build", trace.graph_context_build_ms),
        ("Vector embedding", trace.vector_embedding_ms),
        ("Vector search", trace.vector_search_ms),
        ("Merge + boost", trace.merge_boost_ms),
        ("Evidence images", trace.evidence_images_ms),
        ("Answer generation", trace.answer_generation_ms),
    ]
    for label, ms in stages:
        if ms > 0:
            bar_len = min(30, int(ms / 100))
            bar = "█" * max(1, bar_len)
            print(f"  {_c(label.ljust(22), DIM)} {_c(bar, CYAN)} {ms:.0f}ms")
    print(f"  {_c('Total'.ljust(22), BWHITE)} {trace.total_ms:.0f}ms")
    print()


def _print_isolation_status(trace, strict: bool) -> None:
    """Print project isolation check results."""
    print(_divider("Project Isolation", "─", BYELLOW if trace.violations_count else BGREEN))
    print(f"  {_c('Project:', DIM)} {trace.project_id or '(none)'}")
    if not trace.project_id:
        print(f"  {_c('No project filter — isolation check skipped', DIM)}")
        print()
        return
    no_pid_count = len(trace.graph_nodes_without_project_id)
    if no_pid_count:
        print(f"  {_c('Nodes without project_id:', YELLOW)} {no_pid_count}")
        for n in trace.graph_nodes_without_project_id[:5]:
            print(f"    {_c(n.get('label', '?'), DIM)} {n.get('id', '?')[:30]}")
    if trace.cross_project_nodes:
        label = "VIOLATION" if strict else "WARNING"
        color = RED if strict else YELLOW
        print(f"  {_c(f'Cross-project nodes ({label}):', color)} {len(trace.cross_project_nodes)}")
        for n in trace.cross_project_nodes[:5]:
            node_pid = n.get("project_id", "?")
            print(f"    {_c(n.get('label', '?'), DIM)} {n.get('id', '?')[:30]} (project: {node_pid})")
    if trace.violations_count == 0 and no_pid_count == 0:
        print(f"  {_c('All nodes properly isolated', BGREEN)}")
    print()


def _print_context_summary(chunks, dual_graph, trace) -> None:
    """Print assembled context overview before LLM call."""
    print(_divider("Context Assembly", "━", BCYAN))
    total_chars = sum(len(c.content) for c in chunks)
    print(f"  {_c('Chunks:', BWHITE)} {len(chunks)} ({total_chars:,} chars)")
    sheet_set = sorted({c.sheet_index for c in chunks if c.sheet_index > 0})
    if sheet_set:
        print(f"  {_c('Sheets covered:', DIM)} {sheet_set}")
    type_counts: dict = {}
    for c in chunks:
        type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1
    if type_counts:
        types_str = ", ".join(f"{k}:{v}" for k, v in sorted(type_counts.items()))
        print(f"  {_c('Chunk types:', DIM)} {types_str}")
    if dual_graph and not dual_graph.is_empty:
        total_nodes = len(dual_graph.business.nodes) + len(dual_graph.implementation.nodes)
        total_edges = len(dual_graph.business.edges) + len(dual_graph.implementation.edges)
        print(f"  {_c('Graph context:', BWHITE)} {total_nodes} nodes, {total_edges} edges")
    else:
        print(f"  {_c('Graph context:', DIM)} (none)")
    if trace and trace.graph.edge_confidence_summary:
        summary = trace.graph.edge_confidence_summary
        confirmed = summary.get("confirmed", 0)
        total_edges_count = sum(summary.values())
        if total_edges_count > 0:
            pct = confirmed / total_edges_count * 100
            print(f"  {_c('Edge confidence:', DIM)} {confirmed}/{total_edges_count} confirmed ({pct:.0f}%)")
    print()


def _print_answer(ans_resp, elapsed: float) -> None:
    print(_divider("Generated Answer", "━", BGREEN))
    w = min(_tw(), 80) - 4
    for para in ans_resp.answer.split("\n"):
        if para.strip():
            for line in textwrap.wrap(para, width=w, initial_indent="  ", subsequent_indent="  "):
                print(line)
        else:
            print()
    print()
    print(_divider("Metadata", "━", DIM))
    tok = (f"Tokens: {_c(f'{ans_resp.input_tokens:,}', YELLOW)} in / "
           f"{_c(f'{ans_resp.output_tokens:,}', YELLOW)} out")
    print(f"  {tok} | Time: {_c(f'{elapsed:.1f}s', BGREEN)} | Model: {_c(ans_resp.model_id, DIM)}")
    print()


def _step(msg: str, elapsed: Optional[float] = None) -> None:
    suffix = f" ({elapsed:.1f}s)" if elapsed is not None else ""
    print(_c(f"── {msg}{suffix}", DIM))


def _cmd_help() -> None:
    print(_divider("Commands", "─", CYAN))
    cmds = [
        ("/mode [retrieve|answer|graph]", "Switch query mode"),
        ("/topk N",                       "Set top-K results (1–20, default 5)"),
        ("/verbose",                      "Toggle full chunk content display"),
        ("/evidence",                     "Toggle evidence image loading"),
        ("/trace",                        "Toggle full retrieval trace"),
        ("/vector-only",                  "Toggle vector-only mode (skip graph)"),
        ("/isolation",                    "Show last isolation check status"),
        ("/history",                      "Show recent query history"),
        ("/last",                         "Repeat the last query"),
        ("/stats",                        "Show session statistics"),
        ("/sheets",                       "List available sheets"),
        ("/sheet N",                      "Show content of sheet N"),
        ("/help",                         "Show this help"),
        ("/clear",                        "Clear the screen"),
        ("/quit  or  /exit",              "Exit the terminal"),
    ]
    for cmd, desc in cmds:
        print(f"  {_c(cmd.ljust(32), BCYAN)} {_c(desc, DIM)}")
    print()
    print(_c("  Any text without / is treated as a QA query in the current mode.", DIM))
    print()


def _cmd_stats(s: _Session) -> None:
    print(_divider("Session Statistics", "─", CYAN))
    avg = s.total_latency / s.query_count if s.query_count else 0.0
    ts = time.strftime("%H:%M:%S", time.localtime(s.last_ts)) if s.last_ts else "—"
    rows = [
        ("Queries", str(s.query_count)),
        ("Input tokens", f"{s.total_in_tok:,}"),
        ("Output tokens", f"{s.total_out_tok:,}"),
        ("Avg latency", f"{avg:.1f}s"),
        ("Last query", ts),
        ("Mode", s.mode),
        ("Top-K", str(s.top_k)),
        ("Project", s.project_id or "(all)"),
        ("Verbose", "ON" if s.verbose else "OFF"),
        ("Evidence", "ON" if s.evidence else "OFF"),
    ]
    for label, val in rows:
        print(f"  {_c(label.ljust(18), DIM)} {_c(val, BWHITE)}")
    print()


def _cmd_sheets(s: _Session) -> None:
    if not s.catalog:
        print(_c("  Sheet catalog not available.", YELLOW))
        return
    print(_divider("Available Sheets", "─", CYAN))
    for row in s.catalog:
        idx = int(row.get("sheet_index", -1)) + 1
        name = row.get("original_sheet_name", "")
        pdf = row.get("safe_pdf_filename", "")
        print(f"  {_c(str(idx).rjust(3), BWHITE)}. {_c(name, BCYAN)}  {_c(pdf, DIM)}")
    print()


def _cmd_sheet(idx: int, s: _Session) -> None:
    if not s.catalog or idx < 1 or idx > len(s.catalog):
        n = len(s.catalog) or 27
        print(_c(f"  Sheet {idx} out of range (valid: 1–{n})", YELLOW))
        return
    row = s.catalog[idx - 1]
    name = row.get("original_sheet_name", "")
    print(_divider(f"Sheet {idx}: {name}", "─", CYAN))
    content = _sheet_content(s.catalog_dir, idx) if s.catalog_dir else None
    if content:
        lines = content.splitlines()
        for line in lines[:60]:
            print(f"  {line}")
        if len(lines) > 60:
            print(_c(f"  … ({len(lines) - 60} more lines)", DIM))
    else:
        print(_c("  (Content not available)", DIM))
    print()


def _run_retrieve(query: str, s: _Session) -> None:
    from ..retrieval.query_router import retrieve

    t0 = time.time()
    with _Spinner("Retrieving chunks…"):
        resp = retrieve(query=query, top_k=s.top_k, include_graph=False, project_id=s.project_id)
    elapsed = time.time() - t0
    _step("Retrieving chunks", elapsed)
    s.total_latency += elapsed
    _print_chunks(resp.chunks, verbose=s.verbose)

    if s.debug_retrieval or s.show_vector_trace or s.show_graph_trace:
        print(_c("  Note: --debug-retrieval traces are available in 'answer' mode only.", DIM))
        print(_c("  Use 'mode answer' for full retrieval tracing.", DIM))


def _run_answer(query: str, s: _Session) -> None:
    from ..retrieval.answer_generator import generate_answer, load_evidence_images
    from ..retrieval.graph_guided_retrieval import retrieve_with_graph_guidance
    from ..retrieval.trace import RetrievalTrace
    from ..config import config

    trace = None
    debug_active = s.debug_retrieval or s.show_vector_trace or s.show_graph_trace or s.show_context
    if debug_active:
        trace = RetrievalTrace(enabled=True)

    t0 = time.time()

    # Step 1: Graph-guided retrieval (graph exploration → guided vector search → merge)
    if s.vector_only:
        from ..retrieval.vector_retriever import retrieve_chunks as _vec_retrieve
        with _Spinner("① Vector retrieval (graph skipped)…"):
            chunks = _vec_retrieve(
                query=query, top_k=s.top_k, project_id=s.project_id,
                trace=trace.vector if trace else None,
            )
        dual_graph = None
        guidance_status = "none"
    else:
        with _Spinner("①② Graph-guided retrieval (graph exploration + vector search)…"):
            chunks, dual_graph, guidance_status = retrieve_with_graph_guidance(
                query=query, top_k=s.top_k, project_id=s.project_id,
                trace=trace,
                disable_keyword_boost=s.disable_keyword_boost,
            )
    t1 = time.time()

    # Show guidance status
    _guidance_labels = {
        "strong": _c("ACTIVE", BGREEN) + _c(" (focused sheet filter applied)", DIM),
        "weak": _c("WEAK", BYELLOW) + _c(" (over-broad hints, context only — no vector filter)", DIM),
        "none": _c("NONE", DIM) + _c(" (no graph match, pure vector retrieval)", DIM),
        "error": _c("ERROR", RED) + _c(" (Neptune failed, fell back to vector)", DIM),
    }
    status_label = _guidance_labels.get(guidance_status, guidance_status)
    if s.vector_only:
        _step("① Vector-only retrieval (graph skipped)", t1 - t0)
    else:
        _step(f"①② Graph-guided retrieval — {status_label}", t1 - t0)

    # Print debug traces if active
    if trace and (s.debug_retrieval or s.show_vector_trace):
        _print_vector_trace(trace.vector)
    if trace and (s.debug_retrieval or s.show_graph_trace):
        _print_graph_trace(trace.graph)

    _print_chunks(chunks, verbose=s.verbose)

    # Show graph context
    if dual_graph and not dual_graph.is_empty:
        _print_dual_graph(dual_graph)
    elif dual_graph is not None:
        _print_dual_graph(dual_graph, neptune_available=True)
    else:
        neptune_ok = guidance_status != "error"
        _print_dual_graph(None, neptune_available=neptune_ok)

    # Print context summary if requested
    if trace and (s.debug_retrieval or s.show_context):
        _print_context_summary(chunks, dual_graph, trace)

    # Isolation check
    if trace and trace.isolation.project_id:
        if s.strict_isolation and trace.isolation.violations_count > 0:
            _print_isolation_status(trace.isolation, strict=True)
            print(_c("  ERROR: Strict isolation violated — aborting answer generation.", RED))
            s.last_trace = trace
            return
        elif s.debug_retrieval and (trace.isolation.violations_count > 0
                                    or trace.isolation.graph_nodes_without_project_id):
            _print_isolation_status(trace.isolation, strict=False)

    # Apply graph confidence threshold — filter low-confidence edges before answer
    if dual_graph and s.graph_confidence_threshold > 0.0:
        dual_graph = _filter_graph_by_confidence(dual_graph, s.graph_confidence_threshold)

    # Step 2: PDF/PNG evidence resolution from chunk metadata
    evidence_images: list = []
    if s.evidence and chunks:
        with _Spinner("③ Loading PDF/PNG evidence images…"):
            evidence_images = load_evidence_images(chunks, config.project_root)
        t2 = time.time()
        _step(f"③ Evidence image resolution ({len(evidence_images)} pages)", t2 - t1)
        if trace:
            trace.timing.evidence_images_ms = (t2 - t1) * 1000
    else:
        t2 = t1

    # Print evidence flow summary
    _print_evidence_flow(chunks, dual_graph, evidence_images, t2 - t0, project_id=s.project_id)

    # Step 3: Multimodal VLM answer generation with full evidence pack
    with _Spinner("④ Generating grounded answer (VLM)…"):
        ans = generate_answer(
            query=query,
            retrieved_chunks=chunks,
            evidence_images=evidence_images,
            graph_context=dual_graph.to_merged_context() if dual_graph else None,
            business_graph=dual_graph.business if dual_graph else None,
            implementation_graph=dual_graph.implementation if dual_graph else None,
        )
    t3 = time.time()
    _step("④ VLM answer generation", t3 - t2)

    if trace:
        trace.timing.answer_generation_ms = (t3 - t2) * 1000
        trace.timing.total_ms = (t3 - t0) * 1000

    s.total_in_tok += ans.input_tokens
    s.total_out_tok += ans.output_tokens
    s.total_latency += t3 - t0
    _print_answer(ans, elapsed=t3 - t0)

    # Print timing trace at end if debug active
    if trace and s.debug_retrieval:
        _print_timing_trace(trace.timing)

    if trace:
        s.last_trace = trace


def _run_graph(query: str, s: _Session) -> None:
    from ..retrieval.graph_retriever import fetch_dual_graph_context
    from ..retrieval.vector_retriever import retrieve_chunks
    from ..retrieval.trace import RetrievalTrace

    trace = None
    debug_active = s.debug_retrieval or s.show_vector_trace or s.show_graph_trace
    if debug_active:
        trace = RetrievalTrace(enabled=True)

    t0 = time.time()
    with _Spinner("Retrieving chunks + dual graph…"):
        chunks = retrieve_chunks(
            query=query, top_k=s.top_k, project_id=s.project_id,
            trace=trace.vector if trace else None,
        )
        dual_graph = fetch_dual_graph_context(
            chunks, query=query, project_id=s.project_id,
            trace=trace.graph if trace else None,
            isolation_trace=trace.isolation if trace else None,
        ) if chunks else None
    elapsed = time.time() - t0
    _step("Retrieving chunks + dual graph", elapsed)
    s.total_latency += elapsed

    if trace and (s.debug_retrieval or s.show_vector_trace):
        _print_vector_trace(trace.vector)
    if trace and (s.debug_retrieval or s.show_graph_trace):
        _print_graph_trace(trace.graph)

    _print_chunks(chunks, verbose=s.verbose)
    _print_dual_graph(dual_graph)

    if trace and trace.isolation.project_id and s.debug_retrieval:
        _print_isolation_status(trace.isolation, strict=s.strict_isolation)

    if trace:
        trace.timing.total_ms = elapsed * 1000
        s.last_trace = trace


def _handle_query(query: str, s: _Session) -> bool:
    s.history.append(query)
    s.last_query = query
    s.last_ts = time.time()
    print()
    try:
        if s.mode == "retrieve":
            _run_retrieve(query, s)
        elif s.mode == "answer":
            _run_answer(query, s)
        elif s.mode == "graph":
            _run_graph(query, s)
    except KeyboardInterrupt:
        print(_c("\n  (Interrupted)", YELLOW))
    except Exception as exc:
        print(_c(f"\n  Error: {exc}", RED))
        if s.verbose:
            import traceback
            traceback.print_exc()
    s.query_count += 1
    return True


def _handle_command(cmd: str, s: _Session, model_id: str, collection: str) -> bool:
    parts = cmd.lstrip("/").split()
    if not parts:
        return True
    name, args = parts[0].lower(), parts[1:]

    if name in ("quit", "exit", "q"):
        print(_c("\nGoodbye!", BCYAN))
        return False
    elif name == "help":
        _cmd_help()
    elif name == "clear":
        os.system("clear")
        _print_header(s, collection, model_id)
    elif name == "mode":
        if args and args[0] in ("retrieve", "answer", "graph"):
            s.mode = args[0]
            print(_c(f"  Mode → {s.mode}", BGREEN))
        else:
            print(_c("  Usage: /mode [retrieve|answer|graph]", YELLOW))
    elif name == "topk":
        if args and args[0].isdigit():
            s.top_k = max(1, min(20, int(args[0])))
            print(_c(f"  Top-K → {s.top_k}", BGREEN))
        else:
            print(_c("  Usage: /topk N  (1–20)", YELLOW))
    elif name == "verbose":
        s.verbose = not s.verbose
        print(_c(f"  Verbose → {'ON' if s.verbose else 'OFF'}", BGREEN))
    elif name == "evidence":
        s.evidence = not s.evidence
        print(_c(f"  Evidence images → {'ON' if s.evidence else 'OFF'}", BGREEN))
    elif name == "trace":
        s.debug_retrieval = not s.debug_retrieval
        print(_c(f"  Debug retrieval trace → {'ON' if s.debug_retrieval else 'OFF'}", BGREEN))
    elif name in ("vector-only", "vectoronly"):
        s.vector_only = not s.vector_only
        print(_c(f"  Vector-only mode → {'ON' if s.vector_only else 'OFF'}", BGREEN))
    elif name == "isolation":
        if s.last_trace and s.last_trace.isolation.project_id:
            _print_isolation_status(s.last_trace.isolation, strict=s.strict_isolation)
        else:
            print(_c("  No isolation data yet — run a query first.", DIM))
    elif name == "history":
        if not s.history:
            print(_c("  No queries yet.", DIM))
        else:
            print(_divider("Query History", "─", DIM))
            for i, q in enumerate(s.history[-20:], 1):
                print(f"  {_c(str(i).rjust(3), DIM)}. {q}")
    elif name == "last":
        if s.last_query:
            return _handle_query(s.last_query, s)
        print(_c("  No previous query.", DIM))
    elif name == "stats":
        _cmd_stats(s)
    elif name == "sheets":
        _cmd_sheets(s)
    elif name == "sheet":
        if args and args[0].isdigit():
            _cmd_sheet(int(args[0]), s)
        else:
            print(_c("  Usage: /sheet N", YELLOW))
    else:
        print(_c(f"  Unknown command: /{name}  (try /help)", YELLOW))
    return True


_TAB_COMMANDS = [
    "/mode retrieve", "/mode answer", "/mode graph",
    "/topk ", "/verbose", "/evidence",
    "/trace", "/vector-only", "/isolation",
    "/history", "/last", "/stats",
    "/sheets", "/sheet ", "/help", "/clear", "/quit", "/exit",
]


def _completer(text: str, state: int):
    matches = [cmd for cmd in _TAB_COMMANDS if cmd.startswith(text)]
    return matches[state] if state < len(matches) else None


def _setup_readline() -> None:
    try:
        import readline
        readline.set_completer(_completer)
        readline.parse_and_bind("tab: complete")
        readline.set_history_length(500)
        hist = os.path.expanduser("~/.hermes_rag_history")
        try:
            readline.read_history_file(hist)
        except FileNotFoundError:
            pass
        import atexit
        atexit.register(readline.write_history_file, hist)
    except ImportError:
        pass


def run_terminal(
    catalog_dir: Optional[Path] = None,
    project_id: str = "",
    collection: Optional[str] = None,
    debug_retrieval: bool = False,
    show_vector_trace: bool = False,
    show_graph_trace: bool = False,
    show_context: bool = False,
    strict_project_isolation: bool = False,
    graph_confidence_threshold: float = 0.0,
    disable_keyword_boost: bool = False,
    vector_only: bool = False,
) -> None:
    """Launch the interactive QA terminal."""
    from ..config import config

    model_id = config.vlm_model_id
    if collection:
        config.vector_collection = collection
    collection = config.vector_collection

    _setup_readline()
    session = _Session()
    session.catalog_dir = catalog_dir
    session.catalog = _load_catalog(catalog_dir)
    session.project_id = project_id
    session.debug_retrieval = debug_retrieval
    session.show_vector_trace = show_vector_trace
    session.show_graph_trace = show_graph_trace
    session.show_context = show_context
    session.strict_isolation = strict_project_isolation
    session.graph_confidence_threshold = graph_confidence_threshold
    session.disable_keyword_boost = disable_keyword_boost
    session.vector_only = vector_only

    os.system("clear")
    _print_header(session, collection, model_id)
    print()
    if not project_id:
        print(_c("  ⚠ WARNING: No --project-id set. Retrieval will search across ALL projects.", YELLOW))
        print(_c("    Use @project <id> to scope to a specific project.", YELLOW))
        print()
    print(_c("  Type a question to query, /help for commands, /quit to exit.", DIM))
    print()

    _MODE_COLORS = {"retrieve": GREEN, "answer": CYAN, "graph": YELLOW}

    while True:
        try:
            mode_c = _MODE_COLORS.get(session.mode, BWHITE)
            proj_str = f" {_rl(f'@{session.project_id}', DIM)}" if session.project_id else ""
            prompt = f"{_rl(f'[{session.mode}]', mode_c)}{proj_str} {_rl('Query', BOLD + BWHITE)}{_rl('>', DIM)} "
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(_c("\n\nGoodbye!", BCYAN))
            break

        if not raw:
            continue

        if raw.startswith("/"):
            if not _handle_command(raw, session, model_id, collection):
                break
        elif raw.startswith("@project "):
            # Quick project switch: @project <project_id>
            new_pid = raw[len("@project "):].strip()
            session.project_id = new_pid
            print(_c(f"  Project → {new_pid or '(all)'}", BGREEN))
        else:
            _handle_query(raw, session)


run_qa_terminal = run_terminal
