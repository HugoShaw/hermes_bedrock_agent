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
    header = _c(_box([
        "  Dual-RAG QA Terminal",
        f"  Model: {model_id}",
        f"  Collection: {collection}",
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


def _print_graph(gc, title: str = "Graph Context", color: str = BYELLOW) -> None:
    print(_divider(title, "━", color))
    if not gc or (not gc.nodes and not gc.edges):
        print(_c("  (No graph context — Neptune not configured)", DIM))
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


def _print_dual_graph(dual) -> None:
    """Print two-layer graph context."""
    if dual is None or dual.is_empty:
        _print_graph(None)
        return
    _print_graph(dual.business, "Business Semantic Graph", BYELLOW)
    _print_graph(dual.implementation, "Implementation Graph", BCYAN)


def _print_evidence_flow(chunks, dual_graph, evidence_images, elapsed: float) -> None:
    """Print evidence flow summary showing all sources used."""
    print(_divider("Evidence Flow Summary", "━", BGREEN))
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
        resp = retrieve(query=query, top_k=s.top_k, include_graph=False)
    elapsed = time.time() - t0
    _step("Retrieving chunks", elapsed)
    s.total_latency += elapsed
    _print_chunks(resp.chunks, verbose=s.verbose)


def _run_answer(query: str, s: _Session) -> None:
    from ..retrieval.answer_generator import generate_answer, load_evidence_images
    from ..retrieval.graph_retriever import fetch_dual_graph_context
    from ..retrieval.vector_retriever import retrieve_chunks
    from ..config import config

    t0 = time.time()

    # Step 1: Markdown chunk retrieval
    with _Spinner("① Retrieving Markdown chunks…"):
        chunks = retrieve_chunks(query=query, top_k=s.top_k)
    t1 = time.time()
    _step("① Markdown chunk retrieval", t1 - t0)
    _print_chunks(chunks, verbose=s.verbose)

    # Step 2: Dual-layer graph context retrieval
    dual_graph = None
    with _Spinner("②③ Retrieving graph context (business + implementation)…"):
        dual_graph = fetch_dual_graph_context(chunks, query=query) if chunks else None
    t2 = time.time()
    _step("②③ Graph context retrieval", t2 - t1)
    if dual_graph and not dual_graph.is_empty:
        _print_dual_graph(dual_graph)
    else:
        _print_graph(None)

    # Step 3: PDF/PNG evidence resolution from chunk metadata
    evidence_images: list = []
    if s.evidence and chunks:
        with _Spinner("④ Loading PDF/PNG evidence images…"):
            evidence_images = load_evidence_images(chunks, config.project_root)
        t3 = time.time()
        _step(f"④ Evidence image resolution ({len(evidence_images)} pages)", t3 - t2)
    else:
        t3 = t2

    # Print evidence flow summary
    _print_evidence_flow(chunks, dual_graph, evidence_images, t3 - t0)

    # Step 4: Multimodal VLM answer generation with full evidence pack
    with _Spinner("Generating grounded answer (VLM)…"):
        ans = generate_answer(
            query=query,
            retrieved_chunks=chunks,
            evidence_images=evidence_images,
            graph_context=dual_graph.to_merged_context() if dual_graph else None,
            business_graph=dual_graph.business if dual_graph else None,
            implementation_graph=dual_graph.implementation if dual_graph else None,
        )
    t4 = time.time()
    _step("VLM answer generation", t4 - t3)

    s.total_in_tok += ans.input_tokens
    s.total_out_tok += ans.output_tokens
    s.total_latency += t4 - t0
    _print_answer(ans, elapsed=t4 - t0)


def _run_graph(query: str, s: _Session) -> None:
    from ..retrieval.graph_retriever import fetch_dual_graph_context
    from ..retrieval.vector_retriever import retrieve_chunks

    t0 = time.time()
    with _Spinner("Retrieving chunks + dual graph…"):
        chunks = retrieve_chunks(query=query, top_k=s.top_k)
        dual_graph = fetch_dual_graph_context(chunks, query=query) if chunks else None
    elapsed = time.time() - t0
    _step("Retrieving chunks + dual graph", elapsed)
    s.total_latency += elapsed
    _print_chunks(chunks, verbose=s.verbose)
    _print_dual_graph(dual_graph)


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


def run_terminal(catalog_dir: Optional[Path] = None) -> None:
    """Launch the interactive QA terminal."""
    from ..config import config

    model_id = config.vlm_model_id
    collection = config.vector_collection

    _setup_readline()
    session = _Session()
    session.catalog_dir = catalog_dir
    session.catalog = _load_catalog(catalog_dir)

    os.system("clear")
    _print_header(session, collection, model_id)
    print()
    print(_c("  Type a question to query, /help for commands, /quit to exit.", DIM))
    print()

    _MODE_COLORS = {"retrieve": GREEN, "answer": CYAN, "graph": YELLOW}

    while True:
        try:
            mode_c = _MODE_COLORS.get(session.mode, BWHITE)
            prompt = f"{_rl(f'[{session.mode}]', mode_c)} {_rl('Query', BOLD + BWHITE)}{_rl('>', DIM)} "
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(_c("\n\nGoodbye!", BCYAN))
            break

        if not raw:
            continue

        if raw.startswith("/"):
            if not _handle_command(raw, session, model_id, collection):
                break
        else:
            _handle_query(raw, session)
