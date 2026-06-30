"""CLI project commands: project scanning and management."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

project_app = typer.Typer(
    name="project",
    help="Project scanning and manifest management.",
    add_completion=False,
)
console = Console()


@project_app.command("scan")
def scan(
    source: str = typer.Argument(..., help="S3 URI (s3://bucket/prefix/) or local directory path"),
    project_id: str = typer.Option("", "--project-id", "-p", help="Project ID (derived from source if omitted)"),
    display_name: str = typer.Option("", "--name", "-n", help="Display name for the project"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output manifest JSON path"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Scan a project source (S3 or local) and generate a manifest."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    from .project.scanner import scan_s3_project, scan_local_project

    # Derive project_id if not set
    if not project_id:
        if source.startswith("s3://"):
            project_id = source.rstrip("/").rsplit("/", 1)[-1]
        else:
            project_id = Path(source).name

    if source.startswith("s3://"):
        # Parse s3://bucket/prefix
        parts = source[5:].split("/", 1)
        bucket = parts[0]
        prefix = parts[1].rstrip("/") if len(parts) > 1 else ""
        manifest = scan_s3_project(bucket, prefix, project_id, display_name)
    else:
        manifest = scan_local_project(source, project_id, display_name)

    # Print summary table
    table = Table(title=f"Project: {manifest.display_name}")
    table.add_column("Type", style="cyan")
    table.add_column("Count", style="green", justify="right")

    for type_name, count in sorted(manifest.type_counts().items(), key=lambda x: -x[1]):
        table.add_row(type_name, str(count))

    table.add_row("TOTAL", str(manifest.file_count), style="bold")
    console.print(table)
    console.print(f"Total size: {manifest.total_size_bytes() / 1024 / 1024:.1f} MB")

    # Write manifest
    out_path = output or Path(f"outputs/{project_id}/manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
    console.print(f"[green]Manifest written:[/green] {out_path}")


@project_app.command("status")
def status(
    project_dir: Path = typer.Argument(..., help="Directory containing manifest.json"),
) -> None:
    """Show the status of a previously scanned project."""
    manifest_path = project_dir / "manifest.json"
    if not manifest_path.exists():
        # Try looking in outputs/
        manifest_path = Path(f"outputs/{project_dir.name}/manifest.json")

    if not manifest_path.exists():
        console.print(f"[red]No manifest found at {manifest_path}[/red]")
        raise typer.Exit(1)

    data = json.loads(manifest_path.read_text())
    console.print(f"[bold]Project:[/bold] {data.get('display_name', 'unknown')}")
    console.print(f"[bold]ID:[/bold] {data.get('project_id', 'unknown')}")
    console.print(f"[bold]Source:[/bold] {data.get('source_location', 'unknown')}")
    console.print(f"[bold]Files:[/bold] {data.get('file_count', 0)}")
    console.print(f"[bold]Scanned:[/bold] {data.get('scan_timestamp', 'unknown')}")

    if "type_counts" in data:
        console.print("\n[bold]File types:[/bold]")
        for t, c in sorted(data["type_counts"].items(), key=lambda x: -x[1]):
            console.print(f"  {t}: {c}")


def _resolve_manifest_path(manifest_or_dir: Path) -> Path:
    """Accept either a manifest.json file or a directory containing one."""
    if manifest_or_dir.is_file():
        return manifest_or_dir
    candidate = manifest_or_dir / "manifest.json"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"No manifest.json found at {manifest_or_dir}")


@project_app.command("parse")
def parse_files(
    manifest_or_dir: Path = typer.Argument(..., help="Manifest JSON file or project directory"),
    types: str = typer.Option("", "--types", help="Comma-separated SourceTypes (default: all non-image)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show cost estimate without parsing"),
    no_vlm: bool = typer.Option(False, "--no-vlm", help="Disable VLM, use text extraction for PDFs"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory for markdown files"),
    limit: int = typer.Option(0, "--limit", help="Parse at most N files (0 = no limit)"),
    force: bool = typer.Option(False, "--force", help="Re-parse even if already PARSED"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Parse project files and update manifest state (DEBUG/SINGLE-FILE).

    Intended for debugging single files or incremental re-parse testing.
    Output is flat markdown without the unified directory structure.

    For production knowledge-base parsing, use:
      dualrag parse             — Excel/S3 with unified output + frontmatter
      dualrag project parse-all — Multi-type with role inference + strategy
    """
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    from .models.document import FileState, SourceType, ProjectManifest
    from .parsing.registry import create_default_registry
    from .parsing.utils import compute_content_hash, download_s3_file

    try:
        manifest_path = _resolve_manifest_path(manifest_or_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = ProjectManifest.from_dict(data)

    out_dir = output or manifest_path.parent / "parsed"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine which SourceTypes to process
    if types.strip():
        wanted = {SourceType(t.strip()) for t in types.split(",") if t.strip()}
    else:
        wanted = {st for st in SourceType if st not in (SourceType.IMAGE, SourceType.UNKNOWN)}

    # Filter files
    candidates = [
        f for f in manifest.files
        if f.source_type in wanted
        and (force or f.state != FileState.PARSED)
    ]
    if limit > 0:
        candidates = candidates[:limit]

    registry = create_default_registry()

    n_parsed = 0
    n_skipped = len([f for f in manifest.files if f.source_type in wanted and f.state == FileState.PARSED and not force])
    n_failed = 0
    total_cost = 0.0

    if dry_run:
        console.print(f"\n[bold cyan]DRY RUN — {len(candidates)} files to parse[/bold cyan]")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)

        for pf in candidates:
            is_s3 = pf.path.startswith("s3://")

            # Resolve local path
            if is_s3:
                fname = Path(pf.relative_path).name if pf.relative_path else Path(pf.path).name
                local_path = tmp_root / fname
            else:
                local_path = Path(pf.path)

            parser = registry.get_parser(local_path, pf.source_type)
            if parser is None:
                console.print(f"[yellow]No parser for {pf.source_type.value}: {pf.relative_path}[/yellow]")
                n_skipped += 1
                continue

            if dry_run:
                cost_info = parser.estimated_cost(local_path if local_path.exists() else local_path)
                cost = cost_info.get("estimated_cost_usd", 0.0)
                total_cost += cost
                cost_str = f"  (est. ${cost:.4f})" if cost else ""
                console.print(f"  [cyan]{pf.source_type.value}[/cyan] {pf.relative_path}{cost_str}")
                continue

            # Download from S3 if needed
            if is_s3:
                try:
                    console.print(f"  Downloading {pf.relative_path}...")
                    download_s3_file(pf.path, local_path)
                except Exception as exc:
                    console.print(f"  [red]Download failed: {exc}[/red]")
                    pf.state = FileState.PARSE_FAILED
                    pf.error = f"download_failed: {exc}"
                    n_failed += 1
                    continue

            # Update state to PARSING
            pf.state = FileState.PARSING
            pf.content_hash = compute_content_hash(local_path)

            parse_cfg: dict = {
                "vlm_enabled": not no_vlm,
                "dry_run": False,
                "output_dir": out_dir / "page_images",
            }

            try:
                docs = parser.parse(
                    local_path,
                    manifest.project_id,
                    config=parse_cfg,
                    relative_path=pf.relative_path or local_path.name,
                )
            except Exception as exc:
                logging.getLogger(__name__).exception("Parse error: %s", exc)
                pf.state = FileState.PARSE_FAILED
                pf.error = str(exc)[:500]
                n_failed += 1
                console.print(f"  [red]FAILED[/red] {pf.relative_path}: {exc}")
                continue

            # Save markdown output
            for doc in docs:
                safe_name = Path(pf.relative_path or local_path.name).stem
                md_path = out_dir / f"{safe_name}.md"
                md_path.write_text(doc.content_markdown, encoding="utf-8")

            pf.state = FileState.PARSED
            pf.parsed_at = datetime.now().isoformat()
            pf.error = ""
            n_parsed += 1
            cost_meta = docs[0].metadata.get("estimated_cost_usd", 0.0) if docs else 0.0
            total_cost += cost_meta
            console.print(f"  [green]PARSED[/green] {pf.relative_path}")

    if dry_run:
        console.print(f"\n[bold]Dry run summary:[/bold] {len(candidates)} files, est. cost ${total_cost:.4f}")
        return

    # Write updated manifest
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Summary
    table = Table(title="Parse Summary")
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("[green]Parsed[/green]", str(n_parsed))
    table.add_row("[yellow]Skipped (already parsed)[/yellow]", str(n_skipped))
    table.add_row("[red]Failed[/red]", str(n_failed))
    if total_cost > 0:
        table.add_row("Est. VLM cost", f"${total_cost:.4f}")
    console.print(table)
    console.print(f"[green]Manifest updated:[/green] {manifest_path}")
    console.print(f"[green]Markdown output:[/green] {out_dir}")


@project_app.command("parse-all")
def parse_all(
    project_id: str = typer.Option(..., "--project-id", "-p", help="Project ID"),
    manifest_path: Optional[Path] = typer.Option(
        None, "--manifest", "-m", help="Manifest JSON path (default: outputs/{project_id}/manifest.json)"
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output directory (default: outputs/{project_id})"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify files only, do not parse"),
    force: bool = typer.Option(False, "--force", help="Re-parse even if output exists"),
    skip_vlm: bool = typer.Option(False, "--skip-vlm", help="Skip VLM-based parsers (PDF, image)"),
    limit: int = typer.Option(0, "--limit", help="Parse at most N files (0 = no limit)"),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Run multi-type parsing for an entire project with role inference and strategy selection.

    This command:
    1. Loads the project manifest
    2. Infers document roles (contract, spec, test_case, etc.)
    3. Selects parser strategy per file
    4. Parses all non-skip files to normalized Markdown
    5. Saves an enhanced parsing_manifest.json with results

    Excel files are marked as already-handled (existing pipeline).
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from .models.document import ProjectManifest
    from .parsing.orchestrator import run_project_parsing, save_parsing_manifest

    # Resolve paths
    mp = manifest_path or Path(f"outputs/{project_id}/manifest.json")
    out = output_dir or Path(f"outputs/{project_id}")

    if not mp.exists():
        console.print(f"[red]Manifest not found: {mp}[/red]")
        raise typer.Exit(1)

    # Load manifest
    data = json.loads(mp.read_text(encoding="utf-8"))
    manifest = ProjectManifest.from_dict(data)
    console.print(f"[bold]Project:[/bold] {manifest.display_name} ({project_id})")
    console.print(f"[bold]Files:[/bold] {manifest.file_count}")
    console.print(f"[bold]Source:[/bold] {manifest.source_location}")
    console.print()

    # Run orchestrator
    result = run_project_parsing(
        project_id=project_id,
        manifest=manifest,
        output_dir=out,
        dry_run=dry_run,
        force=force,
        skip_vlm=skip_vlm,
        limit=limit,
    )

    # Save parsing manifest
    manifest_out = save_parsing_manifest(manifest, result, out)

    # Display results
    console.print()
    if dry_run:
        console.print("[bold cyan]═══ DRY RUN RESULTS ═══[/bold cyan]")
    else:
        console.print("[bold green]═══ PARSING RESULTS ═══[/bold green]")

    # Summary table
    summary = Table(title="Parse Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Files scanned", str(result.files_scanned))
    summary.add_row("[green]Files parsed[/green]", str(result.files_parsed))
    summary.add_row("[yellow]Files skipped[/yellow]", str(result.files_skipped))
    summary.add_row("[blue]Already parsed[/blue]", str(result.files_already_parsed))
    summary.add_row("[red]Files failed[/red]", str(result.files_failed))
    summary.add_row("Duration", f"{result.duration_seconds:.1f}s")
    if result.total_vlm_cost > 0:
        summary.add_row("VLM cost (est.)", f"${result.total_vlm_cost:.4f}")
    console.print(summary)

    # By parser type
    if result.by_parser:
        parser_table = Table(title="Parsed by Parser Type")
        parser_table.add_column("Parser", style="cyan")
        parser_table.add_column("Count", justify="right")
        for p, c in sorted(result.by_parser.items(), key=lambda x: -x[1]):
            parser_table.add_row(p, str(c))
        console.print(parser_table)

    # By role
    if result.by_role:
        role_table = Table(title="Files by Document Role")
        role_table.add_column("Role", style="cyan")
        role_table.add_column("Count", justify="right")
        for r, c in sorted(result.by_role.items(), key=lambda x: -x[1]):
            role_table.add_row(r, str(c))
        console.print(role_table)

    # Skip reasons
    if result.skip_reasons:
        skip_table = Table(title="Skip Reasons")
        skip_table.add_column("Reason", style="yellow")
        skip_table.add_column("Count", justify="right")
        for reason, count in sorted(result.skip_reasons.items(), key=lambda x: -x[1]):
            skip_table.add_row(reason, str(count))
        console.print(skip_table)

    # Errors
    if result.errors:
        console.print("\n[red bold]Errors:[/red bold]")
        for err in result.errors[:20]:
            console.print(f"  [red]✗[/red] {err['file']}: {err['error'][:100]}")
        if len(result.errors) > 20:
            console.print(f"  ... and {len(result.errors) - 20} more errors")

    console.print(f"\n[green]Parsing manifest:[/green] {manifest_out}")
    console.print(f"[green]Output directory:[/green] {out / 'parsed'}")
