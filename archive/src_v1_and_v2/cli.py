"""CLI entry point for hermes_bedrock_agent."""
from __future__ import annotations

import typer

app = typer.Typer(name="hermes_bedrock_agent", help="Enterprise AI: KB Query, S3 ETL, Neptune GraphRAG")


@app.command()
def ingest(
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Dry-run mode"),
    prefix: str = typer.Option(None, help="S3 prefix to scan"),
    max_files: int = typer.Option(None, help="Max files to process"),
) -> None:
    """Run S3 Graph ETL ingestion pipeline."""
    from hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion import run_ingestion
    result = run_ingestion(dry_run=dry_run, prefix=prefix, max_files=max_files)
    typer.echo(f"Result: {result}")


@app.command()
def query(
    text: str = typer.Argument(..., help="Query text"),
    top_k: int = typer.Option(5, help="Number of results"),
) -> None:
    """Query Bedrock Knowledge Bases."""
    from hermes_bedrock_agent.kb.kb_query import query_all_kbs
    results = query_all_kbs(text, top_k=top_k)
    for i, r in enumerate(results, 1):
        typer.echo(f"  [{i}] (score={r.score:.3f}, kb={r.display_source})")
        typer.echo(f"      {r.text[:150]}...")


@app.command()
def neptune(
    cypher: str = typer.Argument(..., help="openCypher query"),
) -> None:
    """Run openCypher query against Neptune Analytics."""
    import json
    from hermes_bedrock_agent.graph.neptune_client import NeptuneClient
    client = NeptuneClient()
    result = client.execute_query(cypher)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
