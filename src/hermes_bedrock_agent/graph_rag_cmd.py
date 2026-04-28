"""GraphRAG knowledge graph management commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.tree import Tree
from rich import box

from hermes_bedrock_agent.config import Settings
from hermes_bedrock_agent.graphrag import db as db_mod
from hermes_bedrock_agent.graphrag import s3_reader
from hermes_bedrock_agent.graphrag import extractor as ext_mod
from hermes_bedrock_agent.graphrag import embedder as emb_mod
from hermes_bedrock_agent.graphrag import graph_traversal
from hermes_bedrock_agent.graphrag import neptune as neptune_mod

console = Console()

graph_rag_app = typer.Typer(
    help="GraphRAG knowledge graph management.",
    no_args_is_help=True,
)


def _settings() -> Settings:
    """Load settings, tolerating missing KB config for graph-rag commands."""
    try:
        return Settings.from_env()
    except ValueError:
        # GraphRAG commands don't strictly need knowledge bases configured.
        import os
        from hermes_bedrock_agent.config import KBEntry
        region = os.getenv("AWS_REGION", "ap-northeast-1")
        return Settings(aws_region=region, knowledge_bases=[])


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------

@graph_rag_app.command("upload")
def upload_cmd(
    files: list[Path] = typer.Argument(..., help="Local file paths to upload."),
    prefix: str = typer.Option("graphrag/", "--prefix", help="S3 key prefix."),
    process: bool = typer.Option(True, "--process/--no-process", help="Auto-trigger extraction after upload."),
) -> None:
    """Upload one or more local files to S3 and optionally extract them."""
    settings = _settings()
    bucket = settings.graphrag_s3_bucket
    uploaded_keys: list[str] = []

    for local_path in files:
        if not local_path.exists():
            rprint(f"[red]File not found: {local_path}[/red]")
            raise typer.Exit(1)

        s3_key = prefix.rstrip("/") + "/" + local_path.name
        rprint(f"[cyan]Uploading[/cyan] {local_path} → s3://{bucket}/{s3_key}")
        try:
            s3_reader.upload_file(local_path, bucket, s3_key, region=settings.aws_region)
        except RuntimeError as exc:
            rprint(f"[red]Upload failed:[/red] {exc}")
            raise typer.Exit(1)
        rprint(f"[green]✓ Uploaded:[/green] s3://{bucket}/{s3_key}")
        uploaded_keys.append(s3_key)

    if process and uploaded_keys:
        rprint("\n[bold]Running extraction on uploaded files…[/bold]")
        _run_extract(settings, s3_keys=uploaded_keys)
        rprint("\n[bold]Running embedding on new chunks…[/bold]")
        _run_embed(settings)


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

@graph_rag_app.command("extract")
def extract_cmd(
    prefix: str = typer.Option("graphrag/", "--prefix", help="S3 prefix to scan."),
    file_keys: Optional[list[str]] = typer.Option(
        None, "--file", help="Specific S3 key(s) to extract. Repeat for multiple."
    ),
) -> None:
    """Read files from S3, extract content and relationships, store in graph DB."""
    settings = _settings()
    _run_extract(settings, prefix=prefix, s3_keys=file_keys or [])


def _run_extract(settings: Settings, prefix: str = "graphrag/", s3_keys: list[str] | None = None) -> None:
    bucket = settings.graphrag_s3_bucket
    db_path = settings.graphrag_db_path
    db_mod.init_db(db_path)

    if s3_keys:
        keys_to_process = s3_keys
    else:
        with console.status("Listing S3 objects…"):
            try:
                objects = s3_reader.list_files(bucket, prefix, region=settings.aws_region)
            except RuntimeError as exc:
                rprint(f"[red]S3 listing failed:[/red] {exc}")
                raise typer.Exit(1)
        keys_to_process = [o["key"] for o in objects if str(o["key"]).rsplit(".", 1)[-1].lower() in ext_mod.SUPPORTED_FILE_TYPES]

    if not keys_to_process:
        rprint("[yellow]No supported files found.[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        transient=False,
    ) as progress:
        task = progress.add_task("Extracting files", total=len(keys_to_process))

        for s3_key in keys_to_process:
            progress.update(task, description=f"Extracting {s3_key.split('/')[-1]}")
            try:
                content_bytes = s3_reader.download_file(bucket, s3_key, region=settings.aws_region)
            except RuntimeError as exc:
                rprint(f"[red]Download failed for {s3_key}:[/red] {exc}")
                progress.advance(task)
                continue

            file_type = ext_mod.get_file_type_from_key(s3_key)
            if file_type not in ext_mod.SUPPORTED_FILE_TYPES:
                rprint(f"[yellow]Skipping unsupported file type '{file_type}': {s3_key}[/yellow]")
                progress.advance(task)
                continue

            try:
                result = ext_mod.extract_document(s3_key, content_bytes, file_type)
            except Exception as exc:
                rprint(f"[red]Extraction failed for {s3_key}:[/red] {exc}")
                progress.advance(task)
                continue

            with db_mod.get_connection(db_path) as conn:
                db_mod.upsert_document(
                    conn,
                    doc_id=result.doc_id,
                    s3_key=result.s3_key,
                    filename=result.filename,
                    file_type=result.file_type,
                    content_hash=result.content_hash,
                    char_count=result.char_count,
                    chunk_count=len(result.chunks),
                    created_at=result.chunks[0].created_at if result.chunks else "",
                    updated_at=result.chunks[0].created_at if result.chunks else "",
                )
                for chunk in result.chunks:
                    db_mod.insert_chunk(
                        conn,
                        chunk_id=chunk.id,
                        doc_id=chunk.doc_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        created_at=chunk.created_at,
                    )
                for entity in result.entities:
                    db_mod.upsert_entity(
                        conn,
                        entity_id=entity.id,
                        name=entity.name,
                        entity_type=entity.entity_type,
                        description=entity.description,
                        mention_count=entity.mention_count,
                        created_at=entity.created_at,
                        updated_at=entity.created_at,
                    )
                for edge in result.edges:
                    db_mod.upsert_edge(
                        conn,
                        edge_id=edge.id,
                        src_id=edge.src_id,
                        src_type=edge.src_type,
                        dst_id=edge.dst_id,
                        dst_type=edge.dst_type,
                        edge_type=edge.edge_type,
                        weight=edge.weight,
                        metadata=edge.metadata,
                        created_at=edge.created_at,
                    )

            rprint(
                f"  [green]✓[/green] {s3_key.split('/')[-1]} — "
                f"{len(result.chunks)} chunks, {len(result.entities)} entities, "
                f"{len(result.edges)} edges"
            )
            progress.advance(task)


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------

@graph_rag_app.command("embed")
def embed_cmd(
    model: str = typer.Option("amazon.titan-embed-text-v2:0", "--model", help="Bedrock embedding model ID."),
) -> None:
    """Embed chunks and entities that don't yet have embeddings."""
    settings = _settings()
    _run_embed(settings, model=model)


def _run_embed(settings: Settings, model: str | None = None) -> None:
    db_path = settings.graphrag_db_path
    effective_model = model or settings.graphrag_embedding_model
    db_mod.init_db(db_path)

    with db_mod.get_connection(db_path) as conn:
        pending_chunks = db_mod.get_chunks_without_embedding(conn)
        pending_entities = db_mod.get_entities_without_embedding(conn)

    total = len(pending_chunks) + len(pending_entities)
    if total == 0:
        rprint("[green]All items already embedded.[/green]")
        return

    rprint(f"Embedding [cyan]{len(pending_chunks)}[/cyan] chunks and [cyan]{len(pending_entities)}[/cyan] entities…")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        transient=False,
    ) as progress:
        task = progress.add_task("Embedding", total=total)

        for row in pending_chunks:
            try:
                vec = emb_mod.embed_text(row["text"], model=effective_model, region=settings.aws_region)
                blob = emb_mod.serialize_embedding(vec)
                with db_mod.get_connection(db_path) as conn:
                    db_mod.update_chunk_embedding(conn, row["id"], blob, effective_model)
                if neptune_mod.is_available():
                    neptune_mod.upsert_vector(
                        row["id"], vec, {"type": "chunk", "text": row["text"][:200]}, region=settings.aws_region
                    )
            except Exception as exc:
                rprint(f"[yellow]Warning: embed failed for chunk {row['id']}: {exc}[/yellow]")
            progress.advance(task)

        for row in pending_entities:
            text = row["description"] or row["name"]
            try:
                vec = emb_mod.embed_text(text, model=effective_model, region=settings.aws_region)
                blob = emb_mod.serialize_embedding(vec)
                with db_mod.get_connection(db_path) as conn:
                    db_mod.update_entity_embedding(conn, row["id"], blob, effective_model)
                if neptune_mod.is_available():
                    neptune_mod.upsert_vector(
                        row["id"], vec, {"type": "entity", "name": row["name"]}, region=settings.aws_region
                    )
            except Exception as exc:
                rprint(f"[yellow]Warning: embed failed for entity {row['name']}: {exc}[/yellow]")
            progress.advance(task)

    rprint(f"[green]Done. Embedded {total} item(s).[/green]")


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@graph_rag_app.command("query")
def query_cmd(
    question: str = typer.Argument(..., help="Natural language question to search."),
    top_k: int = typer.Option(5, "--top-k", "-k", min=1, max=50, help="Number of top chunks to retrieve."),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON."),
    expand_hops: int = typer.Option(1, "--expand-hops", help="Graph traversal hops from matched nodes."),
) -> None:
    """Semantic search + graph traversal on the knowledge graph."""
    settings = _settings()
    db_path = settings.graphrag_db_path
    db_mod.init_db(db_path)

    with console.status("Embedding question…"):
        try:
            query_vec = emb_mod.embed_text(question, model=settings.graphrag_embedding_model, region=settings.aws_region)
        except RuntimeError as exc:
            rprint(f"[red]Embedding failed:[/red] {exc}")
            raise typer.Exit(1)

    with db_mod.get_connection(db_path) as conn:
        chunk_rows = db_mod.get_all_chunks_with_embedding(conn)

    if not chunk_rows:
        rprint("[yellow]No embedded chunks found. Run 'graph-rag embed' first.[/yellow]")
        raise typer.Exit(1)

    with console.status("Searching…"):
        top_chunks = emb_mod.find_similar_chunks(query_vec, chunk_rows, top_k=top_k)

    if not top_chunks:
        rprint("[yellow]No results found.[/yellow]")
        return

    chunk_ids = [cid for cid, _ in top_chunks]
    scores = {cid: score for cid, score in top_chunks}

    context = graph_traversal.get_context_for_chunks(db_path, chunk_ids, expand_hops=expand_hops)

    if json_output:
        out = {
            "question": question,
            "top_chunks": [
                {
                    "chunk_id": cid,
                    "score": scores.get(cid, 0.0),
                    "text": next((c["text"] for c in context["chunks"] if c["id"] == cid), ""),
                    "doc_s3_key": next(
                        (context["documents"].get(c["doc_id"], {}).get("s3_key", "") for c in context["chunks"] if c["id"] == cid),
                        "",
                    ),
                }
                for cid in chunk_ids
            ],
            "entities": [
                {"id": nid, "name": n["data"].get("name"), "type": n["data"].get("entity_type")}
                for nid, n in context["entities"].items()
            ],
            "neighbour_chunks": [
                {"id": nid, "text": n["data"].get("text", "")[:200]}
                for nid, n in context["neighbour_chunks"].items()
            ],
        }
        rprint(json.dumps(out, ensure_ascii=False, indent=2))
        return

    rprint(Panel(f"[bold]{question}[/bold]", title="Query", border_style="blue"))

    # Build a doc_id → s3_key lookup
    doc_lookup = {did: d.get("s3_key", did) for did, d in context["documents"].items()}

    for rank, cid in enumerate(chunk_ids, 1):
        chunk_data = next((c for c in context["chunks"] if c["id"] == cid), None)
        if not chunk_data:
            continue
        score = scores.get(cid, 0.0)
        source = doc_lookup.get(chunk_data["doc_id"], chunk_data["doc_id"])
        rprint(
            f"[bold cyan]#{rank}[/bold cyan] score=[green]{score:.4f}[/green] "
            f"source=[yellow]{source}[/yellow] chunk_idx={chunk_data['chunk_index']}"
        )
        rprint(chunk_data["text"][:600])
        rprint()

    if context["entities"]:
        entity_names = [n["data"].get("name", nid) for nid, n in list(context["entities"].items())[:10]]
        rprint(f"[bold]Related entities:[/bold] {', '.join(entity_names)}")

    if context["neighbour_chunks"]:
        rprint(f"[dim]Expanded to {len(context['neighbour_chunks'])} neighbour chunk(s) via {expand_hops} hop(s).[/dim]")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@graph_rag_app.command("delete")
def delete_cmd(
    file_key: Optional[str] = typer.Option(None, "--file", help="S3 key of the document to delete."),
    entity_name: Optional[str] = typer.Option(None, "--entity", help="Entity name to delete."),
    all_data: bool = typer.Option(False, "--all", help="Wipe the entire graph DB."),
) -> None:
    """Remove files, chunks, entities, or the entire graph from the DB."""
    settings = _settings()
    db_path = settings.graphrag_db_path
    db_mod.init_db(db_path)

    if all_data:
        confirmed = typer.confirm("This will delete ALL graph data. Are you sure?")
        if not confirmed:
            rprint("[yellow]Aborted.[/yellow]")
            return
        with db_mod.get_connection(db_path) as conn:
            db_mod.wipe_all(conn)
        rprint("[green]All graph data deleted.[/green]")
        return

    if file_key:
        with db_mod.get_connection(db_path) as conn:
            doc_row = db_mod.get_document_by_s3_key(conn, file_key)
            if not doc_row:
                rprint(f"[red]Document not found:[/red] {file_key}")
                raise typer.Exit(1)
            db_mod.delete_document(conn, doc_row["id"])
        rprint(f"[green]Deleted document and all its graph elements:[/green] {file_key}")
        return

    if entity_name:
        with db_mod.get_connection(db_path) as conn:
            entity_row = db_mod.get_entity_by_name(conn, entity_name)
            if not entity_row:
                rprint(f"[red]Entity not found:[/red] {entity_name!r}")
                raise typer.Exit(1)
            db_mod.delete_entity(conn, entity_row["id"])
        rprint(f"[green]Deleted entity:[/green] {entity_name!r}")
        return

    rprint("[yellow]Specify --file, --entity, or --all.[/yellow]")
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# show-map
# ---------------------------------------------------------------------------

@graph_rag_app.command("show-map")
def show_map_cmd(
    fmt: str = typer.Option("text", "--format", "-f", help="Output format: text | json | mermaid"),
) -> None:
    """Visualize the knowledge graph structure and stats."""
    settings = _settings()
    db_path = settings.graphrag_db_path
    db_mod.init_db(db_path)

    with db_mod.get_connection(db_path) as conn:
        stats = db_mod.get_stats(conn)
        docs = db_mod.get_all_documents(conn)
        all_entities = db_mod.get_all_entities(conn)
        all_edges = db_mod.get_all_edges(conn)

        doc_chunks: dict[str, list] = {}
        for doc in docs:
            doc_chunks[doc["id"]] = db_mod.get_chunks_for_doc(conn, doc["id"])

        # chunk → entity mapping via MENTIONS edges
        chunk_entity_ids: dict[str, list[str]] = {}
        for edge in all_edges:
            if edge["edge_type"] == "MENTIONS":
                chunk_entity_ids.setdefault(edge["src_id"], []).append(edge["dst_id"])

        entity_by_id: dict[str, object] = {e["id"]: e for e in all_entities}

    if fmt == "json":
        nodes = []
        for doc in docs:
            nodes.append({"id": doc["id"], "type": "document", "s3_key": doc["s3_key"]})
        for doc_id, chunks in doc_chunks.items():
            for chunk in chunks:
                nodes.append({"id": chunk["id"], "type": "chunk", "doc_id": doc_id, "chunk_index": chunk["chunk_index"]})
        for entity in all_entities:
            nodes.append({"id": entity["id"], "type": "entity", "name": entity["name"], "entity_type": entity["entity_type"]})
        edges = [dict(e) for e in all_edges]
        output = {"stats": stats, "nodes": nodes, "edges": edges}
        rprint(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if fmt == "mermaid":
        lines = ["graph LR"]
        for doc in docs:
            safe_id = doc["id"][:8]
            label = doc["filename"].replace('"', "'")
            lines.append(f'  doc_{safe_id}["{label}"]')
            for chunk in doc_chunks.get(doc["id"], [])[:5]:
                cid = chunk["id"][:8]
                lines.append(f'  chunk_{cid}["chunk {chunk["chunk_index"]}"]')
                lines.append(f"  doc_{safe_id} --> chunk_{cid}")
                for eid in chunk_entity_ids.get(chunk["id"], [])[:3]:
                    entity = entity_by_id.get(eid)
                    if entity:
                        eid_short = eid[:8]
                        ename = str(entity["name"]).replace('"', "'")[:30]
                        lines.append(f'  entity_{eid_short}["{ename}"]')
                        lines.append(f"  chunk_{cid} --> entity_{eid_short}")
        print("\n".join(lines))
        return

    # Default: rich text tree
    tree = Tree("[bold blue]Knowledge Graph[/bold blue]")
    for doc in docs:
        chunks = doc_chunks.get(doc["id"], [])
        doc_node = tree.add(f"[yellow]{doc['filename']}[/yellow] ({doc['file_type']}, {len(chunks)} chunks)")
        for chunk in chunks[:3]:
            chunk_node = doc_node.add(f"[cyan]chunk {chunk['chunk_index']}[/cyan]: {chunk['text'][:60].strip()}…")
            for eid in chunk_entity_ids.get(chunk["id"], [])[:5]:
                entity = entity_by_id.get(eid)
                if entity:
                    chunk_node.add(f"[green]{entity['name']}[/green] ({entity['entity_type']})")
        if len(chunks) > 3:
            doc_node.add(f"[dim]… and {len(chunks) - 3} more chunks[/dim]")

    console.print(tree)

    table = Table(title="Graph Statistics", box=box.SIMPLE)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    for key, val in stats.items():
        label = key.replace("_", " ").title()
        table.add_row(label, str(val))
    console.print(table)


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------

@graph_rag_app.command("edit")
def edit_cmd(
    file_key: Optional[str] = typer.Option(None, "--file", help="S3 key to re-download and re-extract."),
    entity_name: Optional[str] = typer.Option(None, "--entity", help="Entity name to update."),
    description: Optional[str] = typer.Option(None, "--description", help="New description for the entity."),
) -> None:
    """Re-extract a document or manually update an entity description."""
    settings = _settings()
    db_path = settings.graphrag_db_path
    db_mod.init_db(db_path)

    if file_key:
        # Delete existing data, then re-extract
        with db_mod.get_connection(db_path) as conn:
            doc_row = db_mod.get_document_by_s3_key(conn, file_key)
            if doc_row:
                db_mod.delete_document(conn, doc_row["id"])

        rprint(f"[cyan]Re-extracting:[/cyan] {file_key}")
        _run_extract(settings, s3_keys=[file_key])
        rprint("[cyan]Re-embedding…[/cyan]")
        _run_embed(settings)
        return

    if entity_name and description is not None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with db_mod.get_connection(db_path) as conn:
            entity_row = db_mod.get_entity_by_name(conn, entity_name)
            if not entity_row:
                rprint(f"[red]Entity not found:[/red] {entity_name!r}")
                raise typer.Exit(1)
            db_mod.update_entity_description(conn, entity_row["id"], description, now)
        rprint(f"[green]Updated entity description:[/green] {entity_name!r}")
        rprint("[cyan]Re-embedding entity…[/cyan]")
        _run_embed(settings)
        return

    rprint("[yellow]Specify --file or --entity + --description.[/yellow]")
    raise typer.Exit(1)
