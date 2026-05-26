"""CLI entry point: parse, build-kb, qa commands."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(
    name="hermes",
    help="Hermes: S3 → Excel/PDF parsing → dual-RAG knowledge base → QA terminal.",
    add_completion=False,
)
console = Console()

_NO_PROJECT_WARNING = (
    "[yellow]⚠ WARNING:[/yellow] --project-id not set. "
    "Operations may affect or search across ALL projects in the knowledge base. "
    "Use --project-id to scope to a single project."
)


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    for noisy in ("boto3", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────
# parse command
# ─────────────────────────────────────────────────────────────────────────────

def _derive_project_id(s3_prefix: str) -> str:
    """Derive project_id from S3 prefix: strip trailing slash, use prefix as-is."""
    return s3_prefix.strip("/")


@app.command()
def parse(
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Local Excel/PDF file to parse"),
    s3_prefix: Optional[str] = typer.Option(None, "--s3-prefix", help="S3 prefix to scan for Excel files"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Output base directory"),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Project ID (derived from --s3-prefix if omitted)"),
    stages: str = typer.Option("all", "--stages", help="Stages: all|parse|ingest|images|vlm"),
    mode: str = typer.Option("append", "--mode", help="LanceDB write mode: append|replace|rebuild"),
    skip_graph: bool = typer.Option(False, "--skip-graph", help="Skip Neptune graph stage"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Stage 1: Parse Excel/PDF files from local disk or S3 → VLM markdown."""
    _setup_logging(log_level)
    logger = logging.getLogger("hermes.parse")

    if not file and not s3_prefix:
        console.print("[red]Error:[/red] Provide --file or --s3-prefix")
        raise typer.Exit(1)

    # Derive project_id if not provided
    effective_project_id = project_id or ""
    if not effective_project_id and s3_prefix:
        effective_project_id = _derive_project_id(s3_prefix)
    if not effective_project_id:
        console.print(_NO_PROJECT_WARNING)

    from .config import config
    from .parsing.excel_parser import convert_excel_to_pdfs
    from .parsing.pdf_parser import render_all_sheets
    from .parsing.vlm_client import parse_all_sheets
    from .parsing.text_parser import post_process_all

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if effective_project_id and not output_dir:
        run_dir = Path(f"outputs/{effective_project_id}/run_{ts}")
    else:
        run_dir = output_dir or Path(f"outputs/run_{ts}")
    run_dir.mkdir(parents=True, exist_ok=True)

    xlsx_paths: list[tuple[Path, str]] = []

    if file:
        xlsx_paths.append((file, f"s3://{config.s3_bucket}/{file.name}"))
    elif s3_prefix:
        from .parsing.s3_discovery import discover, download_excel_files
        logger.info("Stage 1: S3 Discovery")
        manifest = discover(s3_prefix)
        dl_dir = run_dir / "downloads"
        manifest = download_excel_files(manifest, str(dl_dir))
        for sf in manifest.excel_files:
            if sf.local_path:
                xlsx_paths.append((Path(sf.local_path), f"s3://{config.s3_bucket}/{sf.key}"))

    summary: list[dict] = []
    for xlsx_path, s3_excel_path in xlsx_paths:
        wb_name = xlsx_path.stem
        wb_dir = run_dir / wb_name
        pdf_dir = wb_dir / "pdf"
        image_dir = wb_dir / "images"
        parsed_dir = wb_dir / "vlm_parsed"

        logger.info("Processing: %s", wb_name)

        if stages in ("all", "parse", "images", "vlm"):
            logger.info("Stage 2: Excel → PDF")
            sheet_pdfs = convert_excel_to_pdfs(str(xlsx_path), str(pdf_dir))

            logger.info("Stage 3: PDF → Images")
            all_images = render_all_sheets(sheet_pdfs, str(image_dir))

            logger.info("Stage 4: VLM Parsing")
            parse_results = parse_all_sheets(all_images, str(parsed_dir), resume=True)

            logger.info("Stage 5: Markdown Post-processing")
            parse_results = post_process_all(parse_results)

            summary.append({
                "workbook": wb_name,
                "sheets_parsed": len(parse_results),
                "output_dir": str(wb_dir),
            })
            logger.info("Done: %d sheets parsed → %s", len(parse_results), parsed_dir)

    summary_path = run_dir / "parse_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    console.print(f"[green]Parse complete.[/green] Summary: {summary_path}")


# ─────────────────────────────────────────────────────────────────────────────
# build-kb command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def build_kb(
    parsed_dir: Path = typer.Argument(..., help="Path to vlm_parsed/ directory with sheet_NN.md files"),
    workbook_name: str = typer.Option("", "--workbook", "-w", help="Workbook name for metadata"),
    s3_excel_key: str = typer.Option("", "--s3-excel-key", help="S3 key for the source Excel file"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Output directory for chunks.jsonl"),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Project ID for multi-project isolation"),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip LanceDB embedding"),
    skip_graph: bool = typer.Option(False, "--skip-graph", help="Skip Neptune graph loading"),
    dry_run_graph: bool = typer.Option(False, "--dry-run-graph", help="Extract graph but don't write to Neptune"),
    use_llm_graph: bool = typer.Option(False, "--use-llm-graph", help="Use Claude Sonnet LLM for graph extraction (higher quality, costs tokens)"),
    graph_delay: float = typer.Option(3.0, "--graph-delay", help="Delay seconds between LLM calls for graph extraction"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Stage 2: Parsed markdown → LanceDB vector store + Neptune graph."""
    _setup_logging(log_level)
    logger = logging.getLogger("hermes.build-kb")

    from .config import config
    from .knowledge_base.chunker import build_chunks
    from .knowledge_base.vector_store import load_vector_store
    from .knowledge_base.graph_loader import build_graph

    parsed_path = parsed_dir.resolve()
    if not parsed_path.exists():
        console.print(f"[red]Error:[/red] Directory not found: {parsed_path}")
        raise typer.Exit(1)

    wb_name = workbook_name or parsed_path.parent.name
    out_dir = output_dir or parsed_path.parent / "dual_rag"
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_jsonl = out_dir / "chunks.jsonl"

    # Detect sheet_name_mapping.csv
    mapping_csv = parsed_path.parent / "sheet_name_mapping.csv"

    logger.info("Step 1: Building dataset from %s", parsed_path)
    effective_project_id = project_id or ""
    if not effective_project_id:
        console.print(_NO_PROJECT_WARNING)
    chunks = build_chunks(
        vlm_parsed_dir=parsed_path,
        sheet_name_mapping_csv=mapping_csv if mapping_csv.exists() else None,
        workbook_name=wb_name,
        s3_bucket=config.s3_bucket,
        s3_pdf_prefix=f"outputs/{wb_name}/pdf",
        s3_vlm_prefix=f"outputs/{wb_name}/vlm_parsed",
        s3_excel_key=s3_excel_key,
        output_path=chunks_jsonl,
        project_id=effective_project_id,
    )
    console.print(f"Chunks built: [cyan]{len(chunks)}[/cyan] → {chunks_jsonl}")

    if len(chunks) == 0:
        console.print("[red]No chunks produced — aborting[/red]")
        raise typer.Exit(1)

    results: dict = {"chunk_count": len(chunks)}

    if not skip_vector:
        logger.info("Step 2: Loading vector store")
        written = load_vector_store(chunks, project_id=effective_project_id)
        results["vector_written"] = written
        console.print(f"LanceDB: [cyan]{written}[/cyan] records written")
    else:
        console.print("[dim]Skipped vector store[/dim]")

    if not skip_graph:
        logger.info("Step 3: Building knowledge graph")
        graph_stats = build_graph(chunks, dry_run=dry_run_graph, use_llm=use_llm_graph, delay_seconds=graph_delay, project_id=effective_project_id)
        results["graph"] = graph_stats
        mode_str = "LLM" if use_llm_graph else "keyword"
        console.print(
            f"Neptune ({mode_str}): [cyan]{graph_stats['node_count']}[/cyan] nodes, "
            f"[cyan]{graph_stats['edge_count']}[/cyan] edges "
            f"(errors: {graph_stats['error_count']})"
        )
        if use_llm_graph and "business_nodes" in graph_stats:
            console.print(
                f"  Business: {graph_stats['business_nodes']} nodes, {graph_stats['business_edges']} edges | "
                f"  Implementation: {graph_stats['implementation_nodes']} nodes, {graph_stats['implementation_edges']} edges"
            )
    else:
        console.print("[dim]Skipped graph build[/dim]")

    summary_path = out_dir / "kb_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    console.print(f"[green]build-kb complete.[/green] Summary: {summary_path}")


# ─────────────────────────────────────────────────────────────────────────────
# qa command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def qa(
    query: Optional[str] = typer.Argument(None, help="One-shot query (omit for interactive mode)"),
    catalog_dir: Optional[Path] = typer.Option(None, "--catalog-dir", help="Dir with sheet_name_mapping.csv + vlm_parsed/"),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Project ID to scope retrieval (required for multi-project)"),
    mode: str = typer.Option("answer", "--mode", "-m", help="Mode: retrieve|answer|graph"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of chunks to retrieve"),
    no_graph: bool = typer.Option(False, "--no-graph", help="Skip Neptune graph context"),
    log_level: str = typer.Option("WARNING", "--log-level", help="Logging level"),
) -> None:
    """Stage 3: Interactive QA terminal or one-shot query."""
    _setup_logging(log_level)

    effective_project_id = project_id or ""
    if not effective_project_id:
        console.print(_NO_PROJECT_WARNING)
    if query:
        # One-shot mode
        from .retrieval.query_router import answer as do_answer, retrieve, format_response
        if mode == "answer":
            resp = do_answer(query, top_k=top_k, include_graph=not no_graph, project_id=effective_project_id)
        else:
            resp = retrieve(query, top_k=top_k, include_graph=(mode == "graph"), project_id=effective_project_id)
        print(format_response(resp, verbose=True))
    else:
        # Interactive terminal
        from .qa.terminal import run_terminal
        run_terminal(catalog_dir=catalog_dir, project_id=effective_project_id)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
