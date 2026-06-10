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
    name="dualrag",
    help="DualRAG: S3 → Excel/PDF parsing → dual-RAG knowledge base → QA terminal.",
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
    """Derive project_id from S3 prefix: extract the last path component (directory name).

    Examples:
        s3://s3-hulftchina-rd/サンプル20260519/ → サンプル20260519
        s3://s3-hulftchina-rd/14_債務奉行クラウド/ → 14_債務奉行クラウド
        サンプル20260519/ → サンプル20260519
    """
    # Strip protocol and bucket if present
    cleaned = s3_prefix
    if cleaned.startswith("s3://"):
        # Remove s3://bucket/ prefix
        cleaned = cleaned[5:]
        # Remove the bucket name (everything before first /)
        _, _, cleaned = cleaned.partition("/")
    # Strip trailing and leading slashes, then take the last path component
    cleaned = cleaned.strip("/")
    # If there are still path separators, take the last component
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    return cleaned


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
            parse_results = parse_all_sheets(all_images, str(parsed_dir), resume=True, workbook_name=wb_name)

            logger.info("Stage 5: Markdown Post-processing")
            parse_results = post_process_all(parse_results)

            summary.append({
                "workbook": wb_name,
                "sheets_parsed": len(parse_results),
                "output_dir": str(wb_dir),
            })
            logger.info("Done: %d sheets parsed → %s", len(parse_results), parsed_dir)

    # ─── Stage 6: Mermaid / Ground-truth file parsing ───────────────────────
    mermaid_summary: list[dict] = []
    if s3_prefix and manifest.ground_truth_files:
        from .parsing.models import FileType
        from .parsing.mermaid_parser import parse_mermaid_file, detect_mermaid_in_markdown
        from .parsing.flowchart_linker import link_mermaid_to_excel
        from .parsing.s3_discovery import download_mermaid_files

        logger.info("Stage 6: Mermaid / Ground-truth file parsing")
        manifest = download_mermaid_files(manifest, str(run_dir / "downloads"))

        mermaid_results: list[tuple[str, str, Any]] = []  # (stem, source_key, result)
        mermaid_out_dir = run_dir / "mermaid"
        for stem, s3f in manifest.ground_truth_files.items():
            if s3f.file_type == FileType.MERMAID and s3f.local_path:
                out = mermaid_out_dir / stem
                result = parse_mermaid_file(s3f.local_path, str(out))
                mermaid_results.append((stem, s3f.key, result))
                logger.info("  Mermaid: %s → %d nodes, %d edges", stem, len(result.nodes), len(result.edges))
            elif s3f.file_type == FileType.MARKDOWN and s3f.local_path:
                blocks = detect_mermaid_in_markdown(s3f.local_path)
                if blocks:
                    logger.info("  Markdown %s: found %d mermaid blocks", stem, len(blocks))
                    for i, block in enumerate(blocks):
                        block_stem = f"{stem}_block{i}"
                        block_out = mermaid_out_dir / block_stem
                        block_out.mkdir(parents=True, exist_ok=True)
                        block_file = block_out / "extracted.mmd"
                        block_file.write_text(block, encoding="utf-8")
                        result = parse_mermaid_file(str(block_file), str(block_out))
                        mermaid_results.append((block_stem, s3f.key, result))

        # Attempt linking (results recorded regardless of confidence)
        links = []
        if mermaid_results:
            raw_results = [r for _, _, r in mermaid_results]
            links = link_mermaid_to_excel(raw_results, summary, str(run_dir))
            for link in links:
                logger.info(
                    "  Link: %s → %s (confidence=%.2f)",
                    Path(link.mermaid_source).name,
                    link.excel_workbook or "(none)",
                    link.match_confidence,
                )

        # Build mermaid_files summary
        for i, (stem, source_key, result) in enumerate(mermaid_results):
            link = links[i] if i < len(links) else None
            mermaid_summary.append({
                "stem": stem,
                "source_key": source_key,
                "nodes": len(result.nodes),
                "edges": len(result.edges),
                "subgraphs": len(result.subgraphs),
                "diagram_type": result.diagram_type,
                "output_dir": f"mermaid/{stem}/",
                "linked_to_workbook": link.excel_workbook if link else None,
                "link_confidence": link.match_confidence if link else 0.0,
                "is_ground_truth": link.mermaid_preferred if link else True,
            })

    parse_summary = {
        "workbooks": summary,
        "mermaid_files": mermaid_summary,
    }
    summary_path = run_dir / "parse_summary.json"
    summary_path.write_text(json.dumps(parse_summary, indent=2, ensure_ascii=False))
    console.print(f"[green]Parse complete.[/green] Summary: {summary_path}")


# ─────────────────────────────────────────────────────────────────────────────
# build-kb command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def build_kb(
    parsed_dir: Path = typer.Argument(..., help="Path to vlm_parsed/ directory with sheet_NN.md files"),
    workbook_name: str = typer.Option("", "--workbook", "-w", help="Workbook name for metadata"),
    s3_excel_key: str = typer.Option("", "--s3-excel-key", help="S3 key for the source Excel file"),
    s3_pdf_prefix: str = typer.Option("", "--s3-pdf-prefix", help="S3 prefix for PDF evidence (defaults to outputs/<dir>/pdf)"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Output directory for chunks.jsonl"),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Project ID for multi-project isolation"),
    append: bool = typer.Option(False, "--append", "-a", help="Append to existing project data (don't delete previous workbooks' chunks)"),
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

    # Derive s3_pdf_prefix from directory structure if not explicitly set
    # The PDF files live as siblings to vlm_parsed/ under the same parent dir
    dir_name = parsed_path.parent.name  # e.g. "reparse_wb2"
    effective_pdf_prefix = s3_pdf_prefix or f"outputs/{dir_name}/pdf"
    effective_vlm_prefix = f"outputs/{dir_name}/vlm_parsed"

    logger.info("Step 1: Building dataset from %s", parsed_path)
    effective_project_id = project_id or ""
    if not effective_project_id:
        console.print(_NO_PROJECT_WARNING)
    chunks = build_chunks(
        vlm_parsed_dir=parsed_path,
        sheet_name_mapping_csv=mapping_csv if mapping_csv.exists() else None,
        workbook_name=wb_name,
        s3_bucket=config.s3_bucket,
        s3_pdf_prefix=effective_pdf_prefix,
        s3_vlm_prefix=effective_vlm_prefix,
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
        written = load_vector_store(chunks, project_id=effective_project_id, replace_project=not append)
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
    collection: Optional[str] = typer.Option(None, "--collection", help="Override LanceDB collection (for experiment eval)"),
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
            resp = do_answer(query, top_k=top_k, include_graph=not no_graph, collection=collection, project_id=effective_project_id)
        else:
            resp = retrieve(query, top_k=top_k, include_graph=(mode == "graph"), collection=collection, project_id=effective_project_id)
        print(format_response(resp, verbose=True))
    else:
        # Interactive terminal
        from .qa.terminal import run_terminal
        run_terminal(catalog_dir=catalog_dir, project_id=effective_project_id, collection=collection)


# ═══════════════════════════════════════════════════════════════════════════════
# graph — New graph extraction & loading pipeline
# ═══════════════════════════════════════════════════════════════════════════════

@app.command()
def graph(
    project_dir: str = typer.Argument(..., help="Project directory containing vlm_parsed/ subdirs"),
    project_id: str = typer.Option("", "--project-id", "-p", help="Stable project ID (ASCII, e.g. sample_20260519)"),
    project_name: str = typer.Option("", "--project-name", "-n", help="Display project name (Japanese OK)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate output files but do not load into Neptune"),
    skip_load: bool = typer.Option(False, "--skip-load", help="Skip Neptune loading step"),
    output_dir: str = typer.Option("", "--output-dir", "-o", help="Output directory (default: <project_dir>/graph_output/)"),
    neptune_graph_id: str = typer.Option("", "--neptune-graph-id", help="Neptune graph identifier (overrides .env)"),
    delay: float = typer.Option(3.0, "--delay", help="Delay between LLM calls (seconds)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Extract graph from vlm_parsed/ markdown and load into Neptune.

    This is the primary graph pipeline command. It replaces the old
    `build-kb --use-llm-graph` flow with a dedicated, project-aware extraction.

    Example:
        dualrag graph outputs/サンプル20260519 --project-id sample_20260519 --dry-run
    """
    _setup_logging("DEBUG" if verbose else "INFO")
    from .config import config  # noqa: F401 — triggers load_dotenv for NEPTUNE_GRAPH_ID
    from .graph_pipeline import run_pipeline, GraphPipelineConfig

    cfg = GraphPipelineConfig(
        project_id=project_id,
        project_name=project_name,
        dry_run=dry_run,
        skip_load=skip_load,
        output_dir=output_dir,
        llm_delay_seconds=delay,
    )
    if neptune_graph_id:
        cfg.neptune_graph_id = neptune_graph_id

    console.print(f"[bold]Graph Pipeline[/bold] — {project_dir}")
    console.print(f"  project_id: {cfg.project_id or '(auto)'}")
    console.print(f"  dry_run: {cfg.dry_run}")
    console.print(f"  neptune: {cfg.neptune_graph_id or '(from .env)'}")
    console.print()

    result = run_pipeline(project_dir, cfg)

    console.print()
    console.print("[bold green]Pipeline complete[/bold green]")
    console.print(f"  Nodes: {len(result.nodes)}")
    console.print(f"  Edges: {len(result.edges)}")
    console.print(f"  Validation issues: {len(result.validation_errors)}")
    console.print(f"  Load stats: {result.load_stats}")
    console.print(f"  Output dir: {result.output_dir}")


# ═══════════════════════════════════════════════════════════════════════════════
# prompts — Prompt version management
# ═══════════════════════════════════════════════════════════════════════════════

prompts_app = typer.Typer(name="prompts", help="Manage graph extraction prompt versions.")


@prompts_app.command("list")
def prompts_list() -> None:
    """Show all registered prompt versions."""
    from .prompts.registry import list_versions, get_current_version

    current = get_current_version()
    versions = list_versions()

    for pv in versions:
        marker = " *active*" if pv.version == current else ""
        status = "exists" if pv.prompt_file.exists() else "MISSING"
        console.print(
            f"  [cyan]{pv.version:<10}[/cyan] {pv.name:<35} "
            f"scope={pv.scope:<10} file={status}[green]{marker}[/green]"
        )


@prompts_app.command("show")
def prompts_show(
    version_id: str = typer.Argument(..., help="Prompt version ID (e.g. v4.3, baseline, v4.4)"),
) -> None:
    """Show details of a specific prompt version."""
    from .prompts.registry import get_version, get_current_version

    try:
        pv = get_version(version_id)
    except KeyError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    current = get_current_version()
    console.print(f"[bold]Version:[/bold]     {pv.version}")
    console.print(f"[bold]Name:[/bold]        {pv.name}")
    console.print(f"[bold]Description:[/bold] {pv.description}")
    console.print(f"[bold]Scope:[/bold]       {pv.scope}")
    console.print(f"[bold]Created:[/bold]     {pv.created_at}")
    console.print(f"[bold]File:[/bold]        {pv.prompt_file}")
    console.print(f"[bold]File exists:[/bold] {pv.prompt_file.exists()}")
    console.print(f"[bold]SHA-256:[/bold]     {pv.sha256[:16]}..." if pv.sha256 else "[bold]SHA-256:[/bold]     (file missing)")
    console.print(f"[bold]Active:[/bold]      {'yes' if pv.version == current else 'no'}")


@prompts_app.command("current")
def prompts_current() -> None:
    """Show currently active prompt version."""
    from .prompts.registry import get_current_version, get_version
    from .version import get_code_version

    current = get_current_version()
    try:
        pv = get_version(current)
        console.print(f"[bold]Active prompt:[/bold] {pv.version} — {pv.name}")
        console.print(f"[bold]Scope:[/bold]         {pv.scope}")
        console.print(f"[bold]SHA-256:[/bold]       {pv.sha256[:16]}..." if pv.sha256 else "")
    except KeyError:
        console.print(f"[yellow]Configured version '{current}' not found in manifest[/yellow]")

    console.print(f"[bold]Code version:[/bold]  {get_code_version()}")


def main() -> None:
    from .cli_project import project_app
    app.add_typer(project_app)
    app.add_typer(prompts_app)
    app()


if __name__ == "__main__":
    main()
