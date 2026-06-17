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
    """Parse Excel/PDF files from S3 or local disk → VLM markdown (PRODUCTION).

    Official production Excel/S3 parser with unified output structure.
    Generates parsed markdown with full YAML frontmatter, evidence files,
    and legacy_compat/ symlinks.

    Output: outputs/<project-id>/run_<timestamp>/
      parsed/excel/<workbook>/  — sheet_XX.md with frontmatter
      evidence/excel/<workbook>/ — PDFs, PNGs, tiles
      legacy_compat/<workbook>/ — backward-compatible symlinks
      parsing_manifest.json     — canonical parse result manifest

    For multi-document-type parsing (PDF, CSV, text, mermaid), use:
      dualrag project parse-all
    """
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
    from .parsing.excel_vlm_adapter import ExcelVlmAdapter
    from .parsing.pdf_parser import render_all_sheets
    from .parsing.vlm_client import parse_all_sheets
    from .parsing.text_parser import post_process_all

    _excel_adapter = ExcelVlmAdapter()

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

    # Unified output writer: canonical structure with legacy_compat symlinks
    from .parsing.output_writer import UnifiedOutputWriter
    writer = UnifiedOutputWriter(run_dir, effective_project_id)

    summary: list[dict] = []
    for xlsx_path, s3_excel_path in xlsx_paths:
        wb_name = xlsx_path.stem
        wb_paths = writer.setup_workbook(wb_name)

        logger.info("Processing: %s", wb_name)

        if stages in ("all", "parse", "images", "vlm"):
            logger.info("Stage 2: Excel → PDF (via system python subprocess)")
            from .parsing.models import SheetInfo, SheetPDF
            sheet_pdf_data = _excel_adapter._convert_excel_subprocess(xlsx_path, wb_paths.pdf_staging)
            sheet_pdfs = []
            for sp_data in sheet_pdf_data:
                si_data = sp_data["sheet_info"]
                si = SheetInfo(**si_data)
                sheet_pdfs.append(SheetPDF(
                    sheet_info=si,
                    pdf_path=sp_data.get("pdf_path", ""),
                    page_size=tuple(sp_data.get("page_size", (0, 0))),
                    pages=sp_data.get("pages", 0),
                    paper_label=sp_data.get("paper_label", ""),
                ))
            logger.info("  → %d sheet PDFs generated", len(sheet_pdfs))

            logger.info("Stage 3: PDF → Images")
            all_images = render_all_sheets(sheet_pdfs, str(wb_paths.image_staging))

            logger.info("Stage 4: VLM Parsing")
            parse_results = parse_all_sheets(all_images, str(wb_paths.vlm_staging), resume=True, workbook_name=wb_name)

            logger.info("Stage 5: Markdown Post-processing")
            parse_results = post_process_all(parse_results)

            # Stage 5b: Reorganize to canonical structure
            logger.info("Stage 5b: Reorganizing to canonical output structure")
            wb_result = writer.reorganize_workbook(wb_paths, s3_excel_path, parse_results)
            logger.info(
                "  → %d sheets, %d PDFs, %d images reorganized",
                wb_result.parsed_md_count, wb_result.pdf_count, wb_result.image_count,
            )

            summary.append({
                "workbook": wb_name,
                "sheets_parsed": len(parse_results),
                "output_dir": str(wb_paths.legacy_dir),
            })
            logger.info("Done: %d sheets parsed → %s", len(parse_results), wb_paths.parsed_dir)

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
        # Use intermediates for raw Mermaid parser output (not parsed/)
        mermaid_intermediate_dir = run_dir / "intermediates" / "mermaid"
        mermaid_intermediate_dir.mkdir(parents=True, exist_ok=True)
        for stem, s3f in manifest.ground_truth_files.items():
            if s3f.file_type == FileType.MERMAID and s3f.local_path:
                out = mermaid_intermediate_dir / stem
                result = parse_mermaid_file(s3f.local_path, str(out))
                mermaid_results.append((stem, s3f.key, result))
                logger.info("  Mermaid: %s → %d nodes, %d edges", stem, len(result.nodes), len(result.edges))
            elif s3f.file_type == FileType.MARKDOWN and s3f.local_path:
                blocks = detect_mermaid_in_markdown(s3f.local_path)
                if blocks:
                    logger.info("  Markdown %s: found %d mermaid blocks", stem, len(blocks))
                    for i, block in enumerate(blocks):
                        block_stem = f"{stem}_block{i}"
                        block_out = mermaid_intermediate_dir / block_stem
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

        # Write Mermaid to canonical parsed/mermaid/ structure via UnifiedOutputWriter
        mermaid_result = None
        if mermaid_results:
            mermaid_result = writer.write_mermaid_parsed(
                mermaid_results, links, source_s3_prefix=s3_prefix
            )
            logger.info(
                "  Mermaid canonical output: %s (%d nodes, %d edges, %d subgraphs)",
                mermaid_result.parsed_path,
                mermaid_result.node_count,
                mermaid_result.edge_count,
                mermaid_result.subgraph_count,
            )

        # Build mermaid_files summary for parsing_manifest
        for i, (stem, source_key, result) in enumerate(mermaid_results):
            link = links[i] if i < len(links) else None
            mermaid_summary.append({
                "stem": stem,
                "source_key": source_key,
                "nodes": len(result.nodes),
                "edges": len(result.edges),
                "subgraphs": len(result.subgraphs),
                "diagram_type": result.diagram_type,
                "parsed_path": "parsed/mermaid/mermaid_parsed.md",
                "raw_mermaid_path": f"intermediates/mermaid/{stem}/mermaid_raw.mmd",
                "structure_json_path": f"intermediates/mermaid/{stem}/mermaid_structure.json",
                "linked_to_workbook": link.excel_workbook if link else None,
                "linked_to_sheet": link.excel_sheet if link else None,
                "link_confidence": link.match_confidence if link else 0.0,
                "is_ground_truth": link.mermaid_preferred if link else True,
            })

    # parse_summary.json — LEGACY, kept for backward compatibility with older scripts.
    # The canonical manifest is parsing_manifest.json (below).
    parse_summary = {
        "_note": "LEGACY: Use parsing_manifest.json as the canonical parse result.",
        "workbooks": summary,
        "mermaid_files": mermaid_summary,
    }
    summary_path = run_dir / "parse_summary.json"
    summary_path.write_text(json.dumps(parse_summary, indent=2, ensure_ascii=False))

    # Write unified manifest and clean up staging
    manifest_path = writer.write_manifest()
    writer.cleanup_staging()

    # Write parsing_manifest.json — the canonical parse result manifest
    # (parse_summary.json is kept for backward compatibility only)
    parsing_manifest = {
        "manifest_version": "2.1",
        "project_id": effective_project_id,
        "structure": "unified_v1",
        "created_at": datetime.now().isoformat(),
        "parsing_run": {
            "timestamp": datetime.now().isoformat(),
            "result": {
                "files_parsed": sum(1 for w in summary if w.get("sheets_parsed", 0) > 0),
                "files_failed": sum(1 for w in summary if w.get("sheets_parsed", 0) == 0),
                "workbooks": summary,
                "mermaid_files": mermaid_summary,
            },
        },
        "paths": {
            "parsed": "parsed/",
            "parsed_excel": "parsed/excel/",
            "parsed_mermaid": "parsed/mermaid/",
            "evidence": "evidence/",
            "evidence_excel": "evidence/excel/",
            "evidence_mermaid": "evidence/mermaid/",
            "intermediates": "intermediates/",
            "intermediates_mermaid": "intermediates/mermaid/",
            "legacy_compat": "legacy_compat/",
        },
        "parsed_documents": [],
    }

    # Add Excel parsed documents
    for wb in summary:
        wb_name = wb.get("workbook", "")
        parsed_excel_dir = run_dir / "parsed" / "excel" / wb_name
        if parsed_excel_dir.exists():
            for md_file in sorted(parsed_excel_dir.glob("sheet_*.md")):
                parsing_manifest["parsed_documents"].append({
                    "path": f"parsed/excel/{wb_name}/{md_file.name}",
                    "source_type": "excel",
                    "parser_type": "excel_vlm",
                    "workbook": wb_name,
                })

    # Add Mermaid parsed document
    if mermaid_summary:
        mermaid_doc = {
            "path": "parsed/mermaid/mermaid_parsed.md",
            "source_type": "mermaid",
            "parser_type": "mermaid_parser",
            "source_files": [m["source_key"] for m in mermaid_summary],
            "raw_mermaid_path": "intermediates/mermaid/mermaid_raw.mmd",
            "structure_json_path": "intermediates/mermaid/mermaid_structure.json",
            "node_count": sum(m["nodes"] for m in mermaid_summary),
            "edge_count": sum(m["edges"] for m in mermaid_summary),
            "subgraph_count": sum(m["subgraphs"] for m in mermaid_summary),
        }
        if mermaid_summary[0].get("linked_to_workbook"):
            mermaid_doc["linked_excel_workbook"] = mermaid_summary[0]["linked_to_workbook"]
            mermaid_doc["linked_excel_sheet"] = mermaid_summary[0].get("linked_to_sheet")
            mermaid_doc["linkage_confidence"] = mermaid_summary[0].get("link_confidence", 0.0)
        parsing_manifest["parsed_documents"].append(mermaid_doc)

    parsing_manifest_path = run_dir / "parsing_manifest.json"
    parsing_manifest_path.write_text(
        json.dumps(parsing_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    console.print(f"[green]Parse complete.[/green] Summary: {summary_path}")
    console.print(f"[green]Parsing manifest:[/green] {parsing_manifest_path}")
    console.print(f"[green]Structure manifest:[/green] {manifest_path}")


# ─────────────────────────────────────────────────────────────────────────────
# build-kb command
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def build_kb(
    parsed_dir: Path = typer.Argument(..., help="Path to parsed/ (unified) or vlm_parsed/ (legacy) directory"),
    workbook_name: str = typer.Option("", "--workbook", "-w", help="Workbook name for metadata"),
    s3_excel_key: str = typer.Option("", "--s3-excel-key", help="S3 key for the source Excel file"),
    s3_pdf_prefix: str = typer.Option("", "--s3-pdf-prefix", help="S3 prefix for PDF evidence (defaults to outputs/<dir>/pdf)"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Output directory for chunks.jsonl"),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Project ID for multi-project isolation"),
    replace: bool = typer.Option(False, "--replace", help="Delete existing chunks for this project_id before inserting"),
    append: bool = typer.Option(False, "--append", "-a", hidden=True, help="[DEPRECATED] Now the default behavior."),
    allow_global: bool = typer.Option(False, "--allow-global", help="Allow operation without --project-id (DANGEROUS: may delete all data)"),
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

    # Safety guard: require --project-id unless --allow-global
    effective_project_id = project_id or ""
    if not effective_project_id and not allow_global:
        console.print("[red]Error:[/red] --project-id is required. "
                      "Use --allow-global to operate without project scope (DANGEROUS).")
        raise typer.Exit(1)

    # Mutual exclusivity: --append and --replace
    if append and replace:
        console.print("[red]Error:[/red] --append and --replace are mutually exclusive. "
                      "Append is the default; use --replace only when you intend to delete existing data.")
        raise typer.Exit(1)

    if append:
        import warnings
        warnings.warn("--append is deprecated and a no-op (append is now the default)", DeprecationWarning, stacklevel=2)

    from .config import config
    from .knowledge_base.chunker import build_chunks, build_chunks_from_parsed_dir
    from .knowledge_base.vector_store import load_vector_store
    from .knowledge_base.graph_loader import build_graph

    parsed_path = parsed_dir.resolve()
    if not parsed_path.exists():
        console.print(f"[red]Error:[/red] Directory not found: {parsed_path}")
        raise typer.Exit(1)

    # Detect unified parsed/ directory vs legacy vlm_parsed/ layout
    # Unified: has subdirs like excel/, mermaid/, docs/, etc. with .md files inside
    # Legacy: has sheet_NN.md files directly
    _UNIFIED_SUBDIRS = {"excel", "mermaid", "docs", "csv", "images", "code"}
    is_unified = any((parsed_path / d).is_dir() for d in _UNIFIED_SUBDIRS)

    if is_unified:
        # New unified path: parsed/ with subdirs excel/, mermaid/, etc.
        logger.info("Detected unified parsed/ directory layout")
        out_dir = output_dir or parsed_path.parent / "dual_rag"
        out_dir.mkdir(parents=True, exist_ok=True)
        chunks_jsonl = out_dir / "chunks.jsonl"

        logger.info("Step 1: Building dataset from %s (unified)", parsed_path)
        if not effective_project_id:
            console.print(_NO_PROJECT_WARNING)
        chunks = build_chunks_from_parsed_dir(
            parsed_dir=parsed_path,
            project_id=effective_project_id,
            output_path=chunks_jsonl,
        )
        console.print(f"Chunks built: [cyan]{len(chunks)}[/cyan] → {chunks_jsonl}")
    else:
        # Legacy path: vlm_parsed/ with sheet_NN.md directly
        logger.info("Detected legacy vlm_parsed/ directory layout")
        wb_name = workbook_name or parsed_path.parent.name
        out_dir = output_dir or parsed_path.parent / "dual_rag"
        out_dir.mkdir(parents=True, exist_ok=True)
        chunks_jsonl = out_dir / "chunks.jsonl"

        # Detect sheet_name_mapping.csv
        mapping_csv = parsed_path.parent / "sheet_name_mapping.csv"

        # Derive s3_pdf_prefix from directory structure if not explicitly set
        dir_name = parsed_path.parent.name
        effective_pdf_prefix = s3_pdf_prefix or f"outputs/{dir_name}/pdf"
        effective_vlm_prefix = f"outputs/{dir_name}/vlm_parsed"

        logger.info("Step 1: Building dataset from %s (legacy)", parsed_path)
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
        written = load_vector_store(chunks, project_id=effective_project_id, replace_project=replace)
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
    debug_retrieval: bool = typer.Option(False, "--debug-retrieval", "-d", help="Show full retrieval trace"),
    show_vector_trace: bool = typer.Option(False, "--show-vector-trace", help="Show vector retrieval details"),
    show_graph_trace: bool = typer.Option(False, "--show-graph-trace", help="Show graph retrieval details"),
    show_context: bool = typer.Option(False, "--show-context", help="Show assembled context before LLM call"),
    strict_project_isolation: bool = typer.Option(False, "--strict-project-isolation", help="Error on cross-project data"),
    graph_confidence_threshold: float = typer.Option(0.0, "--graph-confidence-threshold", help="Filter graph edges below confidence"),
    disable_keyword_boost: bool = typer.Option(False, "--disable-keyword-boost", help="Disable keyword score boosting"),
    vector_only: bool = typer.Option(False, "--vector-only", help="Skip graph retrieval (alias for --no-graph)"),
    log_level: str = typer.Option("WARNING", "--log-level", help="Logging level"),
) -> None:
    """Stage 3: Interactive QA terminal or one-shot query."""
    _setup_logging(log_level)

    effective_project_id = project_id or ""
    if not effective_project_id:
        console.print(
            "[yellow]⚠ WARNING:[/yellow] --project-id not set. "
            "Results may include chunks from ALL projects, leading to mixed or irrelevant answers. "
            "For accurate results, use --project-id to scope retrieval to a single project."
        )
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
        run_terminal(
            catalog_dir=catalog_dir,
            project_id=effective_project_id,
            collection=collection,
            debug_retrieval=debug_retrieval,
            show_vector_trace=show_vector_trace,
            show_graph_trace=show_graph_trace,
            show_context=show_context,
            strict_project_isolation=strict_project_isolation,
            graph_confidence_threshold=graph_confidence_threshold,
            disable_keyword_boost=disable_keyword_boost,
            vector_only=vector_only or no_graph,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# graph — New graph extraction & loading pipeline
# ═══════════════════════════════════════════════════════════════════════════════

@app.command()
def graph(
    project_dir: str = typer.Argument(..., help="Project directory containing vlm_parsed/ subdirs"),
    project_id: str = typer.Option("", "--project-id", "-p", help="Stable project ID (ASCII, e.g. sample_20260519)"),
    project_name: str = typer.Option("", "--project-name", "-n", help="Display project name (Japanese OK)"),
    graph_prompt: str = typer.Option("", "--graph-prompt", help="Graph extraction prompt version (e.g. v4.3, baseline, v4.4). Default: GRAPH_PROMPT_VERSION env or manifest default"),
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
        dualrag graph outputs/サンプル20260519 --graph-prompt v4.4 --dry-run
    """
    _setup_logging("DEBUG" if verbose else "INFO")

    if not project_id:
        console.print("[red]Error:[/red] --project-id is required for graph extraction.")
        raise typer.Exit(1)

    from .config import config  # noqa: F401 — triggers load_dotenv for NEPTUNE_GRAPH_ID
    from .graph_pipeline import run_pipeline, GraphPipelineConfig
    from .prompts.registry import get_current_version, get_version

    prompt_version = graph_prompt or get_current_version()
    pv = get_version(prompt_version)

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
    console.print(f"  graph_prompt: {pv.version} ({pv.name}, adapter={pv.adapter})")
    console.print(f"  dry_run: {cfg.dry_run}")
    console.print(f"  neptune: {cfg.neptune_graph_id or '(from .env)'}")
    console.print()

    result = run_pipeline(project_dir, cfg, prompt_version=prompt_version)

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
