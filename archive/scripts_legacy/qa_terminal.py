#!/usr/bin/env python3
"""Interactive Terminal QA Console for Enterprise GraphRAG.

Phase 11A.1: Rich terminal debug console with dual-path retrieval.
Supports LanceDB vector + Neptune graph, fusion, context building,
and optional Bedrock Claude answer generation with rich formatting.

Usage:
    python scripts/qa_terminal.py --mock-answer          # mock mode
    python scripts/qa_terminal.py                        # live mode
    python scripts/qa_terminal.py --view simple          # minimal output
    python scripts/qa_terminal.py --no-color             # plain text

Safety:
    - READ-ONLY: never writes to LanceDB, Neptune, or artifacts
    - --mock-answer skips all LLM calls for answer generation
    - All Neptune queries are scoped to run_id + dataset
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Lazy .env loading — only called from main() to avoid test contamination
_project_root = Path(__file__).resolve().parent.parent


def _load_env():
    """Load .env file if present. Only call from main()."""
    env_file = _project_root / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env_file, override=False)
        except ImportError:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key not in os.environ:
                            os.environ[key] = val

sys.path.insert(0, str(_project_root / "src"))

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Rich imports
# ---------------------------------------------------------------------------
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXAMPLE_QUESTIONS = [
    "仕訳基礎とは何ですか？",
    "JOURNAL_BASE はどの機能から参照されていますか？",
    "payment_req テーブルは何に使われていますか？",
    "付款申请相关表有哪些？",
    "付款申請の処理フローを教えてください。",
    "村田PRシステムの主要モジュールを教えてください。",
    "AC_DESC.CSV はどの処理に関係していますか？",
]

HELP_TEXT = """[bold]GraphRAG QA Terminal — Commands:[/bold]
  :quit / :exit    Exit the console
  :help            Show this help message
  :examples        Show example questions
  :mode <m>        Switch view (simple|debug|full)
  :lang <l>        Switch language (zh|ja|en|auto)
  :label <l>       Switch label mode (technical|business|mixed)
  :clear           Clear screen
"""

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_HIRAGANA = re.compile(r"[\u3040-\u309F]")
_KATAKANA = re.compile(r"[\u30A0-\u30FF]")
_CJK = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF]")


def detect_language(text: str) -> str:
    """Auto-detect query language: ja, zh, or en."""
    if _HIRAGANA.search(text) or _KATAKANA.search(text):
        return "ja"
    if _CJK.search(text):
        return "zh"
    return "en"


def shorten_uri(uri: str, max_len: int = 50) -> str:
    """Shorten s3://bucket/long/path/file.ext → s3://.../file.ext"""
    if not uri:
        return ""
    if len(uri) <= max_len:
        return uri
    # Keep scheme and filename
    parts = uri.split("/")
    filename = parts[-1] if parts else uri
    scheme = parts[0] + "//" if len(parts) > 2 else ""
    return f"{scheme}.../{ filename}"


def clean_preview(text: str, max_chars: int = 300) -> str:
    """Clean text for terminal display: compress whitespace, truncate."""
    if not text:
        return ""
    # Compress multiple newlines/spaces
    cleaned = re.sub(r"\n+", " ", text)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "…"
    return cleaned


def extract_graph_id_from_endpoint(endpoint: str) -> str:
    """Extract graph_id from Neptune endpoint URL.

    g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com → g-nbuyck5yl8
    """
    if not endpoint:
        return ""
    # Pattern: <graph-id>.<region>.neptune-graph.amazonaws.com
    match = re.match(r"^(g-[a-z0-9]+)\.", endpoint)
    if match:
        return match.group(1)
    return ""


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for qa_terminal."""
    parser = argparse.ArgumentParser(
        description="GraphRAG QA Terminal — interactive hybrid retrieval debug console"
    )

    # Data sources
    parser.add_argument("--run-id", default="murata_live_v1")
    parser.add_argument("--dataset", default="murata")
    parser.add_argument(
        "--vector-store-backend", default="lancedb",
        choices=["lancedb", "opensearch"],
    )
    parser.add_argument(
        "--local-vector-store-path",
        default=os.path.expanduser("~/projects/data/vector_store/lancedb"),
    )
    parser.add_argument("--local-vector-collection", default="murata_e2e_murata_live_v1")
    parser.add_argument(
        "--artifacts-dir",
        default=os.path.expanduser(
            "~/projects/data/enterprise_graphrag/runs/murata_live_v1/artifacts/"
        ),
    )
    parser.add_argument(
        "--neptune-endpoint",
        default="g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com",
    )
    parser.add_argument("--neptune-graph-id", default=None,
                        help="Neptune graph ID (e.g. g-nbuyck5yl8). Auto-inferred from endpoint if not set.")

    # Retrieval params
    parser.add_argument("--top-k-text", type=int, default=10)
    parser.add_argument("--top-k-graph", type=int, default=10)
    parser.add_argument("--fusion-top-k", type=int, default=20)
    parser.add_argument("--graph-depth", type=int, default=2)
    parser.add_argument("--max-edges-per-node", type=int, default=30)

    # Display
    parser.add_argument("--lang", default="auto", choices=["zh", "ja", "en", "auto"])
    parser.add_argument(
        "--label-mode", default="mixed",
        choices=["technical", "business", "mixed"],
    )
    parser.add_argument("--view", default="debug", choices=["simple", "debug", "full"])
    parser.add_argument("--show-prompt", action="store_true")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable rich color output")

    # Enrichment
    parser.add_argument("--use-enrichment", action="store_true")
    parser.add_argument("--i18n-entities-file", default=None)
    parser.add_argument("--i18n-relations-file", default=None)

    # Answer generation
    parser.add_argument("--mock-answer", action="store_true",
                        help="Skip LLM call; generate mock answer")

    args = parser.parse_args(argv)

    # Resolve neptune_graph_id
    if not args.neptune_graph_id:
        # Try env var
        args.neptune_graph_id = os.environ.get("NEPTUNE_GRAPH_ID", "")
    if not args.neptune_graph_id:
        # Infer from endpoint
        args.neptune_graph_id = extract_graph_id_from_endpoint(args.neptune_endpoint)

    return args


# ---------------------------------------------------------------------------
# Rich Renderer
# ---------------------------------------------------------------------------

class QATerminalRenderer:
    """Rich-based terminal renderer for QA results."""

    def __init__(self, console: Console, view: str = "debug", show_prompt: bool = False):
        self.console = console
        self.view = view
        self.show_prompt = show_prompt

    def render(self, result: dict[str, Any]):
        """Render a full QA result based on current view mode."""
        if self.view == "simple":
            self._render_simple(result)
        elif self.view == "full":
            self._render_debug(result)
            self._render_full_extra(result)
        else:
            self._render_debug(result)

    def _render_simple(self, result: dict):
        """Simple view: answer + citations only."""
        self.console.print()
        # Answer
        answer = result.get("answer", "(no answer)")
        self.console.print(Panel(
            Markdown(answer) if not answer.startswith("[") else Text(answer),
            title="[bold green]Answer[/bold green]",
            border_style="green",
        ))
        # Citations
        citations = result.get("citations", [])
        if citations:
            self._render_citations_table(citations)
        self.console.print()

    def _render_debug(self, result: dict):
        """Debug view: full pipeline details."""
        self.console.print()

        # A. Question Panel
        q_text = Text()
        q_text.append(result.get("question", ""), style="bold")
        q_text.append(f"\n  Language: {result.get('detected_language', '?')}")
        self.console.print(Panel(q_text, title="[bold cyan]Question[/bold cyan]", border_style="cyan"))

        # B. Entity Extraction
        mentions = result.get("entity_mentions", [])
        if mentions:
            t = Table(title="Entity Extraction", show_header=True, header_style="bold magenta")
            t.add_column("Mention", style="yellow")
            t.add_column("Matched Entity", style="green")
            t.add_column("Type")
            t.add_column("Conf", justify="right")
            t.add_column("Source")
            for m in mentions[:12]:
                t.add_row(
                    m.get("surface_form", "?"),
                    m.get("matched_entity", ""),
                    m.get("entity_type", ""),
                    f"{m.get('confidence', 0):.2f}",
                    m.get("source", ""),
                )
            self.console.print(t)
        else:
            self.console.print("[dim]No entity mentions extracted[/dim]")

        # C. Graph Search Terms
        terms = result.get("graph_search_terms", [])
        if terms:
            self.console.print(Panel(
                " | ".join(terms[:12]),
                title=f"[bold]Graph Search Terms ({len(terms)})[/bold]",
                border_style="blue",
            ))

        # D. Text Evidence
        text_ev = result.get("text_evidence", [])
        if text_ev:
            t = Table(title=f"Text Evidence (top {len(text_ev)})", show_header=True)
            t.add_column("#", style="dim", width=3)
            t.add_column("Score", justify="right", width=8)
            t.add_column("Chunk ID", width=18)
            t.add_column("Source", width=30)
            t.add_column("Section", width=15)
            t.add_column("Preview", width=60, no_wrap=False)
            for i, ev in enumerate(text_ev[:10]):
                score = getattr(ev, "score", 0.0) if hasattr(ev, "score") else 0.0
                distance = getattr(ev, "distance", None) if hasattr(ev, "distance") else None
                chunk_id = getattr(ev, "chunk_id", "") if hasattr(ev, "chunk_id") else ""
                source_uri = getattr(ev, "source_uri", "") if hasattr(ev, "source_uri") else ""
                section = getattr(ev, "section_title", "") if hasattr(ev, "section_title") else ""
                content = getattr(ev, "content", "") if hasattr(ev, "content") else ""
                # Score display: prefer similarity if >0, otherwise show distance-based
                if score > 0:
                    score_str = f"{score:.4f}"
                elif distance is not None and distance > 0:
                    # Normalized similarity from cosine distance (range [0,2])
                    sim = 1.0 / (1.0 + distance)
                    score_str = f"~{sim:.4f}"
                else:
                    score_str = "[dim]N/A[/dim]"
                t.add_row(
                    str(i + 1),
                    score_str,
                    chunk_id[:18] if chunk_id else "",
                    shorten_uri(source_uri),
                    section[:15] if section else "",
                    clean_preview(content, 200),
                )
            self.console.print(t)
        else:
            self.console.print("[dim]No text evidence retrieved[/dim]")

        # E. Graph Evidence
        graph_ev = result.get("graph_evidence", [])
        if graph_ev:
            t = Table(title=f"Graph Evidence (top {len(graph_ev)})", show_header=True)
            t.add_column("#", style="dim", width=3)
            t.add_column("Score", justify="right", width=8)
            t.add_column("Path / Content", width=60, no_wrap=False)
            t.add_column("Chunks", width=20)
            for i, ev in enumerate(graph_ev[:10]):
                score = getattr(ev, "score", 0.0) if hasattr(ev, "score") else 0.0
                path = getattr(ev, "path_description", "") if hasattr(ev, "path_description") else ""
                content = getattr(ev, "content", "") if hasattr(ev, "content") else ""
                display = path if path else clean_preview(content, 100)
                src_chunks = getattr(ev, "source_chunk_ids", []) if hasattr(ev, "source_chunk_ids") else []
                chunks_str = ", ".join(src_chunks[:3])
                score_str = f"{score:.4f}" if score > 0 else "[dim]N/A[/dim]"
                t.add_row(str(i + 1), score_str, display, chunks_str)
            self.console.print(t)
        elif result.get("graph_disabled"):
            self.console.print("[dim]Graph retrieval: DISABLED (no graph_id)[/dim]")
        else:
            self.console.print("[dim]No graph evidence retrieved[/dim]")

        # F. Fusion summary
        fused = result.get("fused_context")
        if fused:
            n_text = len(fused.text_evidence) if hasattr(fused, "text_evidence") else 0
            n_graph = len(fused.graph_evidence) if hasattr(fused, "graph_evidence") else 0
            self.console.print(Panel(
                f"Text: {n_text} | Graph: {n_graph} | Total: {n_text + n_graph}",
                title="[bold]Fusion[/bold]",
                border_style="yellow",
            ))

        # G. Answer
        answer = result.get("answer", "(no answer)")
        self.console.print(Panel(
            Markdown(answer) if not answer.startswith("[") else Text(answer),
            title="[bold green]Answer[/bold green]",
            border_style="green",
        ))

        # H. Citations
        citations = result.get("citations", [])
        if citations:
            self._render_citations_table(citations)

        # I. Latency
        self._render_latency(result.get("timings", {}))
        self.console.print()

    def _render_full_extra(self, result: dict):
        """Full view extras: raw context + prompt."""
        ctx = result.get("context_str", "")
        if ctx:
            self.console.print(Panel(
                ctx[:5000] + ("…" if len(ctx) > 5000 else ""),
                title="[bold]Raw Fused Context[/bold]",
                border_style="dim",
            ))
        if self.show_prompt:
            prompt = result.get("prompt", "(not available in mock mode)")
            if prompt:
                self.console.print(Panel(
                    prompt[:8000],
                    title="[bold]LLM Prompt[/bold]",
                    border_style="dim",
                ))

    def _render_citations_table(self, citations: list):
        t = Table(title="Citations", show_header=True)
        t.add_column("#", style="dim", width=3)
        t.add_column("Chunk ID", width=18)
        t.add_column("Source", width=40)
        t.add_column("Page/Section", width=20)
        for i, c in enumerate(citations[:8], 1):
            t.add_row(
                str(i),
                c.get("chunk_id", "")[:18],
                shorten_uri(c.get("source_uri", "")),
                c.get("section_title", "") or str(c.get("page", "")),
            )
        self.console.print(t)

    def _render_latency(self, timings: dict):
        t = Table(title="Latency", show_header=True, min_width=40)
        t.add_column("Phase", width=20)
        t.add_column("ms", justify="right", width=8)
        order = [
            ("Entity Extraction", "entity_extraction_ms"),
            ("Query Embedding", "embedding_ms"),
            ("Vector Search", "vector_search_ms"),
            ("Graph Search", "graph_search_ms"),
            ("Fusion", "fusion_ms"),
            ("Answer Generation", "answer_ms"),
        ]
        for label, key in order:
            val = timings.get(key)
            if val is not None:
                t.add_row(label, str(val))
        total = timings.get("total_ms", 0)
        t.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]", style="bold")
        self.console.print(t)


# ---------------------------------------------------------------------------
# QA Session
# ---------------------------------------------------------------------------

class QASession:
    """Encapsulates retrieval pipeline components for the QA session.

    READ-ONLY: Never writes to any external store.
    """

    def __init__(self, args: argparse.Namespace, console: Console):
        self.args = args
        self.console = console
        self._text_retriever = None
        self._graph_retriever = None
        self._entity_index = None
        self._query_extractor = None
        self._embedder = None
        self._context_builder = None
        self._answer_generator = None
        self._bedrock_client = None
        self._graph_enabled = False
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize pipeline components. Returns True if ready."""
        from hermes_bedrock_agent.retrieval.query_entity_extractor import (
            EntityIndex,
            QueryEntityExtractor,
        )
        from hermes_bedrock_agent.retrieval.context_builder import (
            ContextBuilder,
            ContextBuilderConfig,
        )

        args = self.args
        self.console.print("[bold]Initializing QA Session...[/bold]")

        # 1. Entity Index
        entities_path = Path(args.artifacts_dir) / "entities.jsonl"
        if not entities_path.exists():
            self.console.print(f"  [yellow]⚠ entities.jsonl not found at {entities_path}[/yellow]")
            self._entity_index = EntityIndex()
        else:
            self._entity_index = EntityIndex()
            self._entity_index.load_from_jsonl(str(entities_path))
            self.console.print(f"  ✓ EntityIndex: {self._entity_index.size} entities")

        # 2. Enrichment (optional)
        if args.use_enrichment:
            i18n_path = args.i18n_entities_file or str(
                Path(args.artifacts_dir) / "i18n_entities_enriched.jsonl"
            )
            if Path(i18n_path).exists():
                try:
                    self._entity_index.load_i18n_enrichment(i18n_path)
                    self.console.print(f"  ✓ i18n enrichment loaded")
                except Exception as e:
                    self.console.print(f"  [yellow]⚠ i18n enrichment failed: {e}[/yellow]")
            else:
                self.console.print(f"  [yellow]⚠ i18n file not found, using canonical names[/yellow]")

        # 3. Query Entity Extractor
        self._query_extractor = QueryEntityExtractor(self._entity_index)
        self.console.print("  ✓ QueryEntityExtractor ready")

        # 4. LanceDB Vector Store + Text Retriever
        if args.vector_store_backend == "lancedb":
            try:
                from hermes_bedrock_agent.vector_store.lancedb_store import LanceDBStore
                from hermes_bedrock_agent.retrieval.text_retriever import (
                    VectorStoreTextRetriever,
                    TextRetrieverConfig,
                )

                store = LanceDBStore(
                    db_path=args.local_vector_store_path,
                    collection=args.local_vector_collection,
                )
                self._text_retriever = VectorStoreTextRetriever(
                    store,
                    config=TextRetrieverConfig(top_k=args.top_k_text),
                )
                self.console.print(f"  ✓ LanceDB: {args.local_vector_collection}")
            except Exception as e:
                self.console.print(f"  [red]✗ LanceDB failed: {e}[/red]")

        # 5. Embedder
        try:
            from hermes_bedrock_agent.embedding.embedder import BedrockEmbedder, EmbedderConfig

            self._embedder = BedrockEmbedder(
                config=EmbedderConfig(model_id="amazon.titan-embed-text-v2:0", dimension=1024)
            )
            self.console.print("  ✓ Embedder: amazon.titan-embed-text-v2:0")
        except Exception as e:
            self.console.print(f"  [red]✗ Embedder failed: {e}[/red]")

        # 6. Neptune Graph Retriever
        graph_id = args.neptune_graph_id
        if graph_id:
            try:
                from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
                from hermes_bedrock_agent.retrieval.graph_retriever import (
                    NeptuneGraphRetriever,
                    GraphRetrieverConfig,
                )

                neptune_client = NeptuneClient(graph_id=graph_id)
                self._graph_retriever = NeptuneGraphRetriever(
                    neptune_client=neptune_client,
                    config=GraphRetrieverConfig(
                        max_hops=args.graph_depth,
                        max_entities=args.max_edges_per_node,
                        use_query_extractor=True,
                    ),
                    entity_index=self._entity_index,
                )
                self._graph_enabled = True
                self.console.print(f"  ✓ Neptune: graph_id={graph_id}, depth={args.graph_depth}")
            except Exception as e:
                self.console.print(f"  [red]✗ Neptune failed: {e}[/red]")
                self.console.print("    Graph retrieval will be disabled.")
        else:
            self.console.print("  [yellow]⚠ Neptune graph_id not set — graph retrieval DISABLED[/yellow]")
            self.console.print("    Use --neptune-graph-id or set NEPTUNE_GRAPH_ID")

        # 7. Context Builder
        self._context_builder = ContextBuilder(
            config=ContextBuilderConfig(language=args.lang)
        )

        # 8. Answer Generator + Bedrock Client
        if args.mock_answer:
            self.console.print("  ✓ Answer: MOCK mode (no LLM calls)")
        else:
            try:
                from hermes_bedrock_agent.clients.bedrock_client import (
                    BedrockRuntimeClient,
                    get_bedrock_client,
                )
                from hermes_bedrock_agent.generation.answer_generator import (
                    AnswerGenerator,
                    AnswerGeneratorConfig,
                )

                self._bedrock_client = get_bedrock_client()
                answer_model = os.environ.get(
                    "BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0"
                )
                self._answer_generator = AnswerGenerator(
                    bedrock_client=self._bedrock_client,
                    config=AnswerGeneratorConfig(model_id=answer_model, mock_mode=False),
                    context_builder=self._context_builder,
                )
                self.console.print(f"  ✓ Answer: Bedrock Claude ({answer_model})")
            except Exception as e:
                self.console.print(f"  [red]✗ Bedrock answer client failed: {e}[/red]")
                self.console.print("    [yellow]Tip: use --mock-answer to skip LLM dependency[/yellow]")
                # Fallback to mock
                args.mock_answer = True
                self.console.print("    → Falling back to MOCK answer mode")

        self._initialized = True
        self.console.print("[bold green]  Session ready.[/bold green]\n")
        return True

    def ask(self, question: str) -> dict[str, Any]:
        """Process one question through the full retrieval pipeline."""
        from hermes_bedrock_agent.retrieval.fusion import (
            fuse_evidence,
            FusionConfig,
            FusionStrategy,
        )

        args = self.args
        result: dict[str, Any] = {
            "question": question,
            "detected_language": "auto",
            "entity_mentions": [],
            "graph_search_terms": [],
            "matched_entities": [],
            "text_evidence": [],
            "graph_evidence": [],
            "graph_disabled": not self._graph_enabled,
            "fused_context": None,
            "context_str": "",
            "prompt": "",
            "answer": "",
            "citations": [],
            "timings": {},
        }

        # Language detection
        lang = args.lang if args.lang != "auto" else detect_language(question)
        result["detected_language"] = lang

        # Entity extraction
        t0 = time.time()
        if self._query_extractor:
            extraction = self._query_extractor.extract(question)
            result["entity_mentions"] = [
                {
                    "surface_form": m.surface_form,
                    "normalized": m.normalized,
                    "matched_entity": m.matched_entity_name or "",
                    "entity_type": m.entity_type or "",
                    "source": m.source,
                    "confidence": m.confidence,
                }
                for m in extraction.entity_mentions
            ]
            result["graph_search_terms"] = extraction.graph_search_terms
            result["matched_entities"] = [
                {
                    "matched_entity_name": m.matched_entity_name or m.normalized,
                    "entity_type": m.entity_type or "unknown",
                    "confidence": m.confidence,
                }
                for m in extraction.entity_mentions
            ]
        result["timings"]["entity_extraction_ms"] = int((time.time() - t0) * 1000)

        # Text retrieval (embedding + vector search)
        t0 = time.time()
        text_evidence = []
        if self._text_retriever and self._embedder:
            try:
                t_embed = time.time()
                query_embedding = self._embedder.embed_text(question)
                result["timings"]["embedding_ms"] = int((time.time() - t_embed) * 1000)
                text_evidence = self._text_retriever.vector_search(
                    query_embedding,
                    top_k=args.top_k_text,
                    query_text=question,
                )
            except Exception as e:
                logger.warning(f"Text retrieval failed: {e}")
        result["text_evidence"] = text_evidence
        result["timings"]["vector_search_ms"] = int((time.time() - t0) * 1000)

        # Graph retrieval
        t0 = time.time()
        graph_evidence = []
        if self._graph_retriever and self._graph_enabled:
            try:
                graph_evidence, _ = self._graph_retriever.retrieve_from_question(
                    question, max_hops=args.graph_depth
                )
                graph_evidence = graph_evidence[:args.top_k_graph]
            except Exception as e:
                logger.warning(f"Graph retrieval failed: {e}")
        result["graph_evidence"] = graph_evidence
        result["timings"]["graph_search_ms"] = int((time.time() - t0) * 1000)

        # Fusion
        t0 = time.time()
        fusion_config = FusionConfig(
            strategy=FusionStrategy.RRF,
            max_text_evidence=args.top_k_text,
            max_graph_evidence=args.top_k_graph,
        )
        fused = fuse_evidence(text_evidence, graph_evidence, query=question, config=fusion_config)
        result["fused_context"] = fused
        result["timings"]["fusion_ms"] = int((time.time() - t0) * 1000)

        # Context building
        context_str = ""
        if self._context_builder:
            context_str = self._context_builder.build_context(fused)
        result["context_str"] = context_str

        # Answer generation
        t0 = time.time()
        if args.mock_answer:
            n_text = len(text_evidence)
            n_graph = len(graph_evidence)
            result["answer"] = (
                f"[MOCK] Based on {n_text} text evidences and {n_graph} graph evidences, "
                f"the system would generate a detailed answer here.\n\n"
                f"Query: {question}"
            )
            result["citations"] = []
        else:
            try:
                from hermes_bedrock_agent.generation.prompts import build_answer_prompt

                system_prompt, user_prompt = build_answer_prompt(question, context_str)
                result["prompt"] = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}"

                if self._answer_generator:
                    answer_result = self._answer_generator.generate_answer(question, fused)
                    result["answer"] = answer_result.answer
                    result["citations"] = [
                        {
                            "chunk_id": c.chunk_id,
                            "source_uri": c.source_uri,
                            "page": c.page,
                            "section_title": c.section_title,
                        }
                        for c in answer_result.citations
                    ]
                else:
                    result["answer"] = "[ERROR] AnswerGenerator not initialized"
            except Exception as e:
                result["answer"] = f"[ERROR] Answer generation failed: {e}"

        result["timings"]["answer_ms"] = int((time.time() - t0) * 1000)
        result["timings"]["total_ms"] = sum(
            v for v in result["timings"].values() if isinstance(v, (int, float))
        )

        return result


# ---------------------------------------------------------------------------
# Legacy format functions (for tests that import them)
# ---------------------------------------------------------------------------

def format_result_simple(result: dict) -> str:
    """Format result as plain text for simple view."""
    lines = [f"\n{'=' * 70}", f"Answer:", f"  {result.get('answer', '')}"]
    citations = result.get("citations", [])
    if citations:
        lines.append("Citations:")
        for c in citations:
            lines.append(f"  - {c.get('source_uri', '?')} (chunk: {c.get('chunk_id', '?')})")
    lines.append(f"{'=' * 70}\n")
    return "\n".join(lines)


def format_result_debug(result: dict) -> str:
    """Format result as plain text for debug view."""
    lines = [f"\n{'=' * 70}"]
    lines.append(f"[A] Question: {result.get('question', '')}")
    lines.append(f"[B] Detected language: {result.get('detected_language', '?')}")
    mentions = result.get("entity_mentions", [])
    lines.append(f"[C] Extracted entity mentions ({len(mentions)}):")
    for m in mentions[:10]:
        lines.append(f"     • \"{m.get('surface_form', '?')}\" → {m.get('matched_entity', '?')} (conf={m.get('confidence', 0):.3f}, src={m.get('source', '?')})")
    terms = result.get("graph_search_terms", [])
    lines.append(f"[D] Graph search terms ({len(terms)}): {terms[:8]}")
    matched = result.get("matched_entities", [])
    lines.append(f"[E] Matched entities ({len(matched)}):")
    for e in matched[:10]:
        lines.append(f"     • {e.get('matched_entity_name', '?')} [{e.get('entity_type', '?')}] (conf={e.get('confidence', 0):.3f})")
    text_ev = result.get("text_evidence", [])
    lines.append(f"[F] TextEvidence Top-K ({len(text_ev)}):")
    for i, ev in enumerate(text_ev[:10]):
        score = getattr(ev, "score", 0.0) if hasattr(ev, "score") else 0.0
        chunk_id = getattr(ev, "chunk_id", "") if hasattr(ev, "chunk_id") else ""
        source_uri = getattr(ev, "source_uri", "") if hasattr(ev, "source_uri") else ""
        content = getattr(ev, "content", "") if hasattr(ev, "content") else ""
        score_str = f"{score:.4f}" if score > 0 else "N/A"
        lines.append(f"  [{i+1}] score={score_str} | chunk={chunk_id}")
        lines.append(f"      source={shorten_uri(source_uri)}")
        lines.append(f"      text: {clean_preview(content, 200)}")
    graph_ev = result.get("graph_evidence", [])
    lines.append(f"[G] GraphEvidence Top-K ({len(graph_ev)}):")
    for i, ev in enumerate(graph_ev[:10]):
        path = getattr(ev, "path_description", "") if hasattr(ev, "path_description") else ""
        content = getattr(ev, "content", "") if hasattr(ev, "content") else ""
        lines.append(f"  [{i+1}] {path or clean_preview(content, 100)}")
    fused = result.get("fused_context")
    if fused:
        n_text = len(fused.text_evidence) if hasattr(fused, "text_evidence") else 0
        n_graph = len(fused.graph_evidence) if hasattr(fused, "graph_evidence") else 0
        lines.append(f"[H] Fusion: {n_text} text + {n_graph} graph = {n_text + n_graph} total")
    lines.append(f"[I] Answer:")
    lines.append(f"    {result.get('answer', '(no answer)')}")
    citations = result.get("citations", [])
    lines.append(f"[J] Citations ({len(citations)}):")
    for c in citations[:5]:
        lines.append(f"    • {shorten_uri(c.get('source_uri', '?'))} chunk={c.get('chunk_id', '?')}")
    timings = result.get("timings", {})
    lines.append(f"[K] Latency: total={timings.get('total_ms', 0)}ms")
    lines.append(f"{'=' * 70}\n")
    return "\n".join(lines)


def format_result(result: dict, view: str, show_prompt: bool = False) -> str:
    """Plain-text format dispatcher (used by tests and --no-color fallback)."""
    if view == "simple":
        return format_result_simple(result)
    elif view == "full":
        out = format_result_debug(result)
        ctx = result.get("context_str", "")
        out += f"\n[FULL] Raw fused context:\n{ctx[:5000]}\n"
        if show_prompt:
            prompt = result.get("prompt", "(not available)")
            out += f"\n[FULL] Assembled prompt:\n{prompt[:8000]}\n"
        return out
    else:
        return format_result_debug(result)


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

def run_interactive(session: QASession, args: argparse.Namespace):
    """Main interactive loop."""
    console = session.console
    view_mode = args.view
    renderer = QATerminalRenderer(console, view=view_mode, show_prompt=args.show_prompt)

    # Banner
    console.print()
    console.print(Panel.fit(
        f"[bold]GraphRAG QA Terminal[/bold] — Phase 11A\n"
        f"run_id={args.run_id} | dataset={args.dataset}\n"
        f"view={view_mode} | lang={args.lang} | label={args.label_mode}\n"
        f"mock_answer={args.mock_answer} | enrichment={args.use_enrichment}\n"
        f"graph_id={args.neptune_graph_id or 'N/A'}\n"
        f"Type [bold]:help[/bold] for commands, [bold]:examples[/bold] for sample questions",
        border_style="bright_blue",
    ))
    console.print()

    while True:
        try:
            question = input("Q> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break

        if not question:
            continue

        # Handle commands
        if question.startswith(":"):
            cmd_parts = question.split(None, 1)
            cmd = cmd_parts[0].lower()
            cmd_arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

            if cmd in (":quit", ":exit"):
                console.print("Bye!")
                break
            elif cmd == ":help":
                console.print(Markdown(HELP_TEXT))
            elif cmd == ":examples":
                console.print("\n[bold]Example questions:[/bold]")
                for i, q in enumerate(EXAMPLE_QUESTIONS, 1):
                    console.print(f"  {i}. {q}")
                console.print()
            elif cmd == ":mode":
                if cmd_arg in ("simple", "debug", "full"):
                    view_mode = cmd_arg
                    renderer.view = view_mode
                    console.print(f"  View mode → [bold]{view_mode}[/bold]")
                else:
                    console.print("  Usage: :mode simple|debug|full")
            elif cmd == ":lang":
                if cmd_arg in ("zh", "ja", "en", "auto"):
                    args.lang = cmd_arg
                    console.print(f"  Language → [bold]{cmd_arg}[/bold]")
                else:
                    console.print("  Usage: :lang zh|ja|en|auto")
            elif cmd == ":label":
                if cmd_arg in ("technical", "business", "mixed"):
                    args.label_mode = cmd_arg
                    console.print(f"  Label mode → [bold]{cmd_arg}[/bold]")
                else:
                    console.print("  Usage: :label technical|business|mixed")
            elif cmd == ":clear":
                os.system("clear" if os.name != "nt" else "cls")
            else:
                console.print(f"  Unknown command: {cmd}. Type :help")
            continue

        # Process question
        result = session.ask(question)

        # Render
        if args.no_color:
            print(format_result(result, view_mode, show_prompt=args.show_prompt))
        else:
            renderer.render(result)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _load_env()
    args = parse_args()

    console = Console(force_terminal=not args.no_color, no_color=args.no_color)

    session = QASession(args, console)
    try:
        session.initialize()
    except Exception as e:
        console.print(f"\n[red][ERROR] Failed to initialize: {e}[/red]")
        console.print("[yellow]Tip: Use --mock-answer to skip LLM dependency.[/yellow]")
        sys.exit(1)

    run_interactive(session, args)


if __name__ == "__main__":
    main()
