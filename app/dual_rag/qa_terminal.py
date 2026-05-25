#!/usr/bin/env python3
"""Interactive QA terminal for the dual-RAG pipeline.

Usage:
    python3 -m app.dual_rag.qa_terminal
"""
from __future__ import annotations

import csv
import os
import sys
import time
import textwrap
import shutil
import threading
from pathlib import Path
from typing import Optional

# ── ANSI codes ────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BGREEN = "\033[92m"
BYELLOW= "\033[93m"
BCYAN  = "\033[96m"
BWHITE = "\033[97m"


def _c(text: str, *codes: str) -> str:
    return f"{''.join(codes)}{text}{RESET}"


def _rl(text: str, *codes: str) -> str:
    """Readline-safe ANSI: wraps non-printing sequences in \\001...\\002."""
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


# ── Spinner ───────────────────────────────────────────────────────────────────
class _Spinner:
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str):
        self._label = label
        self._stop  = threading.Event()
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


# ── Sheet catalog ─────────────────────────────────────────────────────────────
def _load_catalog() -> list[dict]:
    from .config import config
    path = config.sheet_name_mapping_csv
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _sheet_content(sheet_1based: int) -> Optional[str]:
    """Return VLM-parsed markdown for sheet N (1-based)."""
    from .config import config
    md = config.vlm_parsed_dir / f"sheet_{sheet_1based:02d}.md"
    return md.read_text(encoding="utf-8") if md.exists() else None


# ── Session state ─────────────────────────────────────────────────────────────
class _Session:
    def __init__(self):
        self.mode: str = "retrieve"   # retrieve | answer | graph
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


# ── Header / output helpers ───────────────────────────────────────────────────
def _print_header(s: _Session) -> None:
    from .config import config
    model_id = os.getenv("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
    ev = "ON" if s.evidence else "OFF"
    header = _c(_box([
        "  Dual-RAG QA Terminal",
        f"  Model: {model_id}",
        f"  Collection: {config.vector_collection} (468 docs)",
        f"  Mode: {s.mode} | Top-K: {s.top_k} | Evidence: {ev}",
    ], width=54), BCYAN)
    print(header)


def _print_chunks(chunks, verbose: bool = False) -> None:
    print(_divider("Retrieved Chunks", "━", BCYAN))
    for i, chunk in enumerate(chunks, 1):
        hdr   = _c(f"[{i}]", BOLD + BWHITE)
        sheet = _c(f"Sheet {chunk.sheet_index} / {chunk.sheet_name}", BCYAN)
        ctype = _c(f"Type: {chunk.chunk_type}", DIM)
        bar   = _score_bar(chunk.score)
        score = _c(f"{chunk.score:.2f}", YELLOW)
        print(f"  {hdr} {sheet}")
        print(f"      {ctype} | Score: {bar} {score}")
        if chunk.source_pdf_s3_path:
            pdf = _c(chunk.source_pdf_s3_path.split("/")[-1], DIM)
            print(f"      {_c('PDF:', DIM)} {pdf}")
        if chunk.content:
            raw = chunk.content if verbose else chunk.content[:160]
            preview = raw.replace("\n", " ")
            if not verbose:
                preview = preview + "…"
            wrapped = textwrap.fill(
                preview, width=68,
                initial_indent="      ",
                subsequent_indent="      ",
            )
            print(_c(wrapped, DIM))
        print()


def _print_evidence(paths: list[str]) -> None:
    if not paths:
        return
    print(_divider("Evidence Images", "━", BCYAN))
    for p in paths:
        short = p.split("/")[-1] if "/" in p else p
        print(f"  📄 {_c(short, BWHITE)}")
    print()


def _print_graph(gc) -> None:
    print(_divider("Graph Context", "━", BYELLOW))
    if not gc or (not gc.nodes and not gc.edges):
        print(_c("  (No graph context — Neptune not configured)", DIM))
        print()
        return
    print(f"  {_c(f'Nodes: {len(gc.nodes)}', BYELLOW)}  "
          f"{_c(f'Edges: {len(gc.edges)}', YELLOW)}")
    for node in gc.nodes[:10]:
        nid   = node.get("id", "?")
        label = node.get("label", "")
        props = node.get("properties", {})
        name  = props.get("name", props.get("sheet_name", ""))
        suffix = f" — {name}" if name else ""
        print(f"  {_c('●', YELLOW)} [{label}] {nid}{suffix}")
    if len(gc.nodes) > 10:
        print(_c(f"    … {len(gc.nodes) - 10} more nodes", DIM))
    for edge in gc.edges[:10]:
        fr  = edge.get("from", "?")
        to  = edge.get("to", "?")
        rel = edge.get("relationship", "?")
        print(f"  {_c('→', CYAN)} {fr} --{rel}--> {to}")
    if len(gc.edges) > 10:
        print(_c(f"    … {len(gc.edges) - 10} more edges", DIM))
    print()


def _print_answer(ans_resp, elapsed: float) -> None:
    print(_divider("Generated Answer", "━", BGREEN))
    w = min(_tw(), 80) - 4
    for para in ans_resp.answer.split("\n"):
        if para.strip():
            for line in textwrap.wrap(para, width=w,
                                       initial_indent="  ",
                                       subsequent_indent="  "):
                print(line)
        else:
            print()
    print()
    print(_divider("Metadata", "━", DIM))
    tok = (f"Tokens: {_c(f'{ans_resp.input_tokens:,}', YELLOW)} in / "
           f"{_c(f'{ans_resp.output_tokens:,}', YELLOW)} out")
    t   = _c(f"{elapsed:.1f}s", BGREEN)
    m   = _c(ans_resp.model_id, DIM)
    print(f"  {tok} | Time: {t} | Model: {m}")
    print()


def _step(msg: str, elapsed: Optional[float] = None) -> None:
    suffix = f" ({elapsed:.1f}s)" if elapsed is not None else ""
    print(_c(f"── {msg}{suffix}", DIM))


# ── Command handlers ──────────────────────────────────────────────────────────
def _handle_command(cmd: str, s: _Session) -> bool:
    """Dispatch a /command. Returns False to quit."""
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
        _print_header(s)

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
            print(_c("  Usage: /sheet N  (1–27)", YELLOW))

    else:
        print(_c(f"  Unknown command: /{name}  (try /help)", YELLOW))

    return True


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
        ("/sheets",                       "List all 27 available sheets"),
        ("/sheet N",                      "Show content of sheet N (1–27)"),
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
    ts  = time.strftime("%H:%M:%S", time.localtime(s.last_ts)) if s.last_ts else "—"
    rows: list[tuple[str, str]] = [
        ("Queries",          str(s.query_count)),
        ("Input tokens",     f"{s.total_in_tok:,}"),
        ("Output tokens",    f"{s.total_out_tok:,}"),
        ("Avg latency",      f"{avg:.1f}s"),
        ("Last query",       ts),
        ("Mode",             s.mode),
        ("Top-K",            str(s.top_k)),
        ("Verbose",          "ON" if s.verbose else "OFF"),
        ("Evidence",         "ON" if s.evidence else "OFF"),
    ]
    for label, val in rows:
        print(f"  {_c(label.ljust(18), DIM)} {_c(val, BWHITE)}")
    print()


def _cmd_sheets(s: _Session) -> None:
    if not s.catalog:
        print(_c("  Sheet catalog not available.", YELLOW))
        return
    print(_divider("Available Sheets (27 total)", "─", CYAN))
    for row in s.catalog:
        idx  = int(row.get("sheet_index", -1)) + 1   # CSV is 0-based → display 1-based
        name = row.get("original_sheet_name", "")
        pdf  = row.get("safe_pdf_filename", "")
        print(f"  {_c(str(idx).rjust(3), BWHITE)}. {_c(name, BCYAN)}"
              f"  {_c(pdf, DIM)}")
    print()


def _cmd_sheet(idx: int, s: _Session) -> None:
    if not s.catalog or idx < 1 or idx > len(s.catalog):
        n = len(s.catalog) or 27
        print(_c(f"  Sheet {idx} out of range (valid: 1–{n})", YELLOW))
        return
    row  = s.catalog[idx - 1]
    name = row.get("original_sheet_name", "")
    print(_divider(f"Sheet {idx}: {name}", "─", CYAN))
    content = _sheet_content(idx)
    if content:
        lines = content.splitlines()
        show  = lines[:60]
        for line in show:
            print(f"  {line}")
        if len(lines) > 60:
            print(_c(f"  … ({len(lines) - 60} more lines, use /verbose for full view)", DIM))
    else:
        print(_c("  (Content not available)", DIM))
    print()


# ── Query execution ───────────────────────────────────────────────────────────
def _handle_query(query: str, s: _Session) -> bool:
    from .qa_retriever import retrieve

    s.history.append(query)
    s.last_query = query
    s.last_ts    = time.time()
    print()

    try:
        if s.mode == "retrieve":
            _run_retrieve(query, s, retrieve)
        elif s.mode == "answer":
            _run_answer(query, s, retrieve)
        elif s.mode == "graph":
            _run_graph(query, s, retrieve)
    except KeyboardInterrupt:
        print(_c("\n  (Interrupted)", YELLOW))
    except Exception as exc:
        print(_c(f"\n  Error: {exc}", RED))
        if s.verbose:
            import traceback
            traceback.print_exc()

    s.query_count += 1
    return True


def _run_retrieve(query: str, s: _Session, retrieve_fn) -> None:
    t0 = time.time()
    with _Spinner("Retrieving chunks…"):
        resp = retrieve_fn(query=query, top_k=s.top_k, include_graph=False)
    elapsed = time.time() - t0
    _step("Retrieving chunks", elapsed)
    s.total_latency += elapsed
    _print_chunks(resp.chunks, verbose=s.verbose)
    _print_evidence(resp.evidence_paths)


def _run_answer(query: str, s: _Session, retrieve_fn) -> None:
    from .answer_generator import generate_answer, load_evidence_images

    t0 = time.time()
    with _Spinner("Retrieving chunks + graph…"):
        qa = retrieve_fn(query=query, top_k=s.top_k, include_graph=True)
    t1 = time.time()
    _step("Retrieving chunks + graph", t1 - t0)
    _print_chunks(qa.chunks, verbose=s.verbose)

    if qa.graph_context:
        _print_graph(qa.graph_context)

    evidence_images: list = []
    if s.evidence and qa.chunks:
        with _Spinner("Loading evidence images…"):
            evidence_images = load_evidence_images(qa.chunks)
        t2 = time.time()
        _step(f"Loading evidence images ({len(evidence_images)} PDFs)", t2 - t1)
        _print_evidence(qa.evidence_paths)
    else:
        t2 = t1

    with _Spinner("Generating answer…"):
        ans = generate_answer(
            query=query,
            retrieved_chunks=qa.chunks,
            evidence_images=evidence_images,
            graph_context=qa.graph_context,
        )
    t3 = time.time()
    _step("Generating answer", t3 - t2)

    if ans.graph_context_text:
        n_nodes = len(qa.graph_context.nodes) if qa.graph_context else 0
        n_edges = len(qa.graph_context.edges) if qa.graph_context else 0
        print(_c(
            f"  Graph context sent to model: {n_nodes} nodes, {n_edges} edges",
            DIM,
        ))

    s.total_in_tok  += ans.input_tokens
    s.total_out_tok += ans.output_tokens
    s.total_latency += t3 - t0
    _print_answer(ans, elapsed=t3 - t0)


def _run_graph(query: str, s: _Session, retrieve_fn) -> None:
    t0 = time.time()
    with _Spinner("Retrieving chunks + graph…"):
        resp = retrieve_fn(query=query, top_k=s.top_k, include_graph=True)
    elapsed = time.time() - t0
    _step("Retrieving chunks + graph", elapsed)
    s.total_latency += elapsed
    _print_chunks(resp.chunks, verbose=s.verbose)
    _print_evidence(resp.evidence_paths)
    _print_graph(resp.graph_context)


# ── Tab completion ────────────────────────────────────────────────────────────
_TAB_COMMANDS = [
    "/mode retrieve", "/mode answer", "/mode graph",
    "/topk ",
    "/verbose", "/evidence",
    "/history", "/last", "/stats",
    "/sheets", "/sheet ",
    "/help", "/clear", "/quit", "/exit",
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
        hist = os.path.expanduser("~/.dual_rag_history")
        try:
            readline.read_history_file(hist)
        except FileNotFoundError:
            pass
        import atexit
        atexit.register(readline.write_history_file, hist)
    except ImportError:
        pass


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    _setup_readline()
    session = _Session()
    session.catalog = _load_catalog()

    os.system("clear")
    _print_header(session)
    print()
    print(_c("  Type a question to query, /help for commands, /quit to exit.", DIM))
    print()

    _MODE_COLORS = {"retrieve": GREEN, "answer": CYAN, "graph": YELLOW}

    while True:
        try:
            mode_c = _MODE_COLORS.get(session.mode, BWHITE)
            prompt = (
                f"{_rl(f'[{session.mode}]', mode_c)} "
                f"{_rl('Query', BOLD + BWHITE)}{_rl('>', DIM)} "
            )
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print(_c("\n\nGoodbye!", BCYAN))
            break

        if not raw:
            continue

        if raw.startswith("/"):
            if not _handle_command(raw, session):
                break
        else:
            _handle_query(raw, session)


if __name__ == "__main__":
    main()
