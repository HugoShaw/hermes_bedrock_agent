"""Typer command group for the doc-analyze feature."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich import box, print as rprint
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from hermes_bedrock_agent.doc_analyze.analyzer import analyze_directory
from hermes_bedrock_agent.doc_analyze.mermaid_renderer import render_mermaid
from hermes_bedrock_agent.graphrag.s3_reader import list_files, upload_file

console = Console()

doc_analyze_app = typer.Typer(
    help="Company document relationship analysis with Mermaid visualization.",
    no_args_is_help=True,
)

_DEFAULT_PREFIX = "company-docs/"
_DEFAULT_MODEL = "anthropic.claude-sonnet-4-6"
_DEFAULT_TITLE = "Company Document Relationship Map"
_DEFAULT_REGION = "ap-northeast-1"


def _resolve_bucket(bucket: Optional[str]) -> str:
    resolved = bucket or os.getenv("GRAPHRAG_S3_BUCKET", "s3-hulftchina-rd")
    if not resolved:
        raise typer.BadParameter("S3 bucket not specified. Set --bucket or GRAPHRAG_S3_BUCKET env var.")
    return resolved


def _resolve_region() -> str:
    return os.getenv("AWS_REGION", _DEFAULT_REGION)


def _resolve_model(model: Optional[str]) -> str:
    return model or os.getenv("BEDROCK_MODEL_ID", _DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@doc_analyze_app.command("run")
def run_cmd(
    prefix: str = typer.Option(_DEFAULT_PREFIX, "--prefix", help="S3 prefix/directory to analyze."),
    bucket: Optional[str] = typer.Option(None, "--bucket", help="S3 bucket override (defaults to GRAPHRAG_S3_BUCKET env)."),
    output: Optional[Path] = typer.Option(None, "--output", help="Output .md file path. Defaults to ./doc_analysis_<timestamp>.md."),
    title: str = typer.Option(_DEFAULT_TITLE, "--title", help="Title for the diagram."),
    model: Optional[str] = typer.Option(None, "--model", help="Bedrock model ID override."),
    max_chars: int = typer.Option(8000, "--max-chars", help="Max chars per file to include in context."),
) -> None:
    """Analyze documents in an S3 prefix and generate a Mermaid relationship diagram."""
    resolved_bucket = _resolve_bucket(bucket)
    region = _resolve_region()
    resolved_model = _resolve_model(model)

    if output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path(f"./doc_analysis_{ts}.md")

    rprint(f"[bold cyan]Analyzing s3://{resolved_bucket}/{prefix}[/bold cyan]")
    rprint(f"  Region : {region}")
    rprint(f"  Model  : {resolved_model}")
    rprint(f"  Output : {output}")
    rprint()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("Listing files…", total=None)

        try:
            result = analyze_directory(
                bucket=resolved_bucket,
                prefix=prefix,
                region=region,
                model_id=resolved_model,
                max_chars_per_file=max_chars,
            )
        except RuntimeError as exc:
            progress.stop()
            rprint(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(1)

        progress.update(task, description="Rendering diagram…")

    # Handle parse errors
    if result.parse_error:
        raw_path = output.with_suffix(".raw.txt")
        raw_path.write_text(result.raw_response, encoding="utf-8")
        rprint(f"[bold yellow]Warning:[/bold yellow] {result.parse_error}")
        rprint(f"  Raw LLM response saved to: {raw_path}")
        raise typer.Exit(1)

    _, full_markdown = render_mermaid(result, title=title)

    # Build output file content
    md_content = f"# {title}\n\n**Summary:** {result.summary}\n\n{full_markdown}\n"
    output.write_text(md_content, encoding="utf-8")

    rprint(f"[bold green]Analysis complete![/bold green]")
    rprint(f"\n[bold]Summary:[/bold] {result.summary}")
    rprint(f"\n  Entities found    : {len(result.entities)}")
    rprint(f"  Relationships found: {len(result.relationships)}")
    rprint(f"\n[bold]Output written to:[/bold] {output}")


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

@doc_analyze_app.command("upload")
def upload_cmd(
    files: list[Path] = typer.Argument(..., help="Local files to upload."),
    prefix: str = typer.Option(_DEFAULT_PREFIX, "--prefix", help="S3 prefix to upload into."),
    bucket: Optional[str] = typer.Option(None, "--bucket", help="S3 bucket override."),
    analyze: bool = typer.Option(True, "--analyze/--no-analyze", help="Auto-run analysis after upload."),
) -> None:
    """Upload documents to S3, then optionally analyze the prefix."""
    resolved_bucket = _resolve_bucket(bucket)
    region = _resolve_region()

    for local_path in files:
        if not local_path.exists():
            rprint(f"[bold red]File not found:[/bold red] {local_path}")
            raise typer.Exit(1)

        s3_key = f"{prefix.rstrip('/')}/{local_path.name}"
        rprint(f"Uploading [cyan]{local_path.name}[/cyan] → s3://{resolved_bucket}/{s3_key}")
        try:
            upload_file(local_path, resolved_bucket, s3_key, region=region, show_progress=True)
        except RuntimeError as exc:
            rprint(f"[bold red]Upload failed:[/bold red] {exc}")
            raise typer.Exit(1)

    rprint(f"\n[bold green]{len(files)} file(s) uploaded to s3://{resolved_bucket}/{prefix}[/bold green]")

    if analyze:
        rprint("\nRunning analysis…")
        typer.get_current_context().invoke(
            run_cmd,
            prefix=prefix,
            bucket=resolved_bucket,
            output=None,
            title=_DEFAULT_TITLE,
            model=None,
            max_chars=8000,
        )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@doc_analyze_app.command("list")
def list_cmd(
    prefix: str = typer.Option(_DEFAULT_PREFIX, "--prefix", help="S3 prefix to list."),
    bucket: Optional[str] = typer.Option(None, "--bucket", help="S3 bucket override."),
) -> None:
    """List all documents in an S3 prefix."""
    resolved_bucket = _resolve_bucket(bucket)
    region = _resolve_region()

    try:
        objects = list_files(resolved_bucket, prefix, region)
    except RuntimeError as exc:
        rprint(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(1)

    if not objects:
        rprint(f"[yellow]No files found in s3://{resolved_bucket}/{prefix}[/yellow]")
        return

    table = Table(title=f"s3://{resolved_bucket}/{prefix}", box=box.ROUNDED)
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Last Modified", style="dim")

    for obj in objects:
        key = str(obj["key"])
        filename = key.split("/")[-1]
        if not filename:
            continue
        size_bytes = int(obj.get("size", 0))  # type: ignore[arg-type]
        size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes >= 1024 else f"{size_bytes} B"
        last_modified = str(obj.get("last_modified", ""))
        table.add_row(filename, size_str, last_modified)

    console.print(table)
    rprint(f"\n[dim]{len(objects)} object(s) total[/dim]")
