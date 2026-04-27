from __future__ import annotations

import json
from typing import Any

import typer
from rich import box
from rich import print as rprint
from rich.table import Table

from hermes_bedrock_agent.config import Settings
from hermes_bedrock_agent.kb_client import KBResult, MultiKBClient

app = typer.Typer(
    help="Bedrock Knowledge Base CLI — supports single and multiple KBs.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _results_to_rows(results: list[KBResult]) -> list[dict[str, Any]]:
    return [
        {
            "text": r.text,
            "score": r.score,
            "metadata": r.metadata,
            "location": r.location,
            "kb_id": r.kb_id,
            "kb_label": r.kb_label,
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("ask")
def ask_cmd(
    query: str = typer.Argument(..., help="Question to send to the Knowledge Base(s)."),
    top_k: int = typer.Option(5, "--top-k", "-k", min=1, max=20, help="Chunks to retrieve per KB."),
    json_output: bool = typer.Option(False, "--json", help="Return structured JSON output."),
    kb_ids: list[str] | None = typer.Option(
        None,
        "--kb",
        help=(
            "KB ID(s) to query.  Repeat to query several: --kb KB001 --kb KB002.  "
            "Defaults to all KBs configured via BEDROCK_KNOWLEDGE_BASES / BEDROCK_KNOWLEDGE_BASE_ID."
        ),
    ),
    merge: str = typer.Option(
        "score",
        "--merge",
        help="Merge strategy when multiple KBs are queried: score | round_robin | kb_order",
    ),
    no_dedup: bool = typer.Option(False, "--no-dedup", help="Disable deduplication of identical chunks."),
) -> None:
    """Query one or more Bedrock Knowledge Bases and display results."""
    settings = Settings.from_env()
    multi = MultiKBClient(settings, kb_ids=kb_ids or None)
    results = multi.retrieve(
        query,
        number_of_results=top_k,
        merge_strategy=merge,
        deduplicate=not no_dedup,
    )

    if json_output:
        rprint(json.dumps({"query": query, "results": _results_to_rows(results)}, ensure_ascii=False, indent=2))
        return

    rprint(f"[bold green]Retrieved {len(results)} result(s) for:[/bold green] {query!r}\n")
    for i, r in enumerate(results, 1):
        rprint(f"[bold cyan]#{i}  score={r.score:.4f}  source=[{r.display_source}][/bold cyan]")
        if r.metadata:
            rprint(f"[yellow]  metadata:[/yellow] {r.metadata}")
        if r.location:
            rprint(f"[yellow]  location:[/yellow] {r.location}")
        rprint(r.text[:1000])
        rprint()


@app.command("list-kbs")
def list_kbs_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all configured knowledge bases."""
    settings = Settings.from_env()
    kbs = settings.knowledge_bases

    if json_output:
        rprint(json.dumps([{"kb_id": kb.kb_id, "label": kb.label} for kb in kbs], ensure_ascii=False, indent=2))
        return

    table = Table(title="Configured Knowledge Bases", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("ID", style="cyan")
    table.add_column("Label", style="green")

    for i, kb in enumerate(kbs, 1):
        table.add_row(str(i), kb.kb_id, kb.label or "(none)")

    rprint(table)


@app.command("compare")
def compare_cmd(
    query: str = typer.Argument(..., help="Question to send to all KBs separately."),
    top_k: int = typer.Option(3, "--top-k", "-k", min=1, max=20, help="Chunks to retrieve per KB."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Query each KB independently and show results side-by-side for comparison."""
    settings = Settings.from_env()
    multi = MultiKBClient(settings)

    per_kb: dict[str, list[KBResult]] = {}
    for kb in settings.knowledge_bases:
        per_kb[kb.kb_id] = multi.retrieve_from(kb.kb_id, query, number_of_results=top_k)

    if json_output:
        out = {
            "query": query,
            "per_kb": {
                kb_id: _results_to_rows(results)
                for kb_id, results in per_kb.items()
            },
        }
        rprint(json.dumps(out, ensure_ascii=False, indent=2))
        return

    for kb in settings.knowledge_bases:
        results = per_kb[kb.kb_id]
        rprint(f"\n[bold magenta]=== {kb.display_name} ({kb.kb_id}) — {len(results)} result(s) ===[/bold magenta]")
        for i, r in enumerate(results, 1):
            rprint(f"  [bold cyan]#{i} score={r.score:.4f}[/bold cyan]")
            rprint(f"  {r.text[:500]}")
            rprint()


if __name__ == "__main__":
    app()
