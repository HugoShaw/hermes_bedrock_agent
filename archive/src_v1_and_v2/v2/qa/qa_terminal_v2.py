"""
V2 QA Terminal — Interactive QA terminal with debug mode.

Provides an interactive REPL for querying the V2 Knowledge Graph system.
Shows business graph, implementation graph, evidence, and LLM answers.
Supports debug mode showing full retrieval trace.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.qa.answer_generator import (
    AnswerGeneratorV2,
    ContextBudget,
)
from hermes_bedrock_agent.v2.retrieval.hybrid_context_builder import HybridContextBuilder
from hermes_bedrock_agent.v2.schemas.retrieval_schema import HybridContext


BANNER = """\
╔══════════════════════════════════════════════════════════════════╗
║                    GraphRAG QA Terminal V2                        ║
║  Architecture: Business Semantic Graph + Implementation Graph    ║
║                + Vector Evidence Store                            ║
╚══════════════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """\
Commands:
  :help          Show this help
  :exit          Exit terminal
  :debug on      Enable debug output
  :debug off     Disable debug output
  :stats         Show data store statistics
  :sources       Show available source documents
  :last-context  Show last query's budgeted context
  :last-debug    Show last query's debug record

Type any question to query the knowledge graph.
"""


class QATerminalV2:
    """Interactive QA terminal with debug mode and context budgeting."""

    def __init__(
        self,
        output_dir: str | Path,
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
        use_llm: bool = True,
        debug: bool = False,
        max_evidence_chunks: int = 12,
        max_total_context_chars: int = 12000,
    ):
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.dataset = dataset
        self.use_llm = use_llm
        self.debug = debug

        # Context budget
        self.budget = ContextBudget(
            max_evidence_chunks=max_evidence_chunks,
            max_total_context_chars=max_total_context_chars,
        )

        # Initialize components
        self.context_builder = HybridContextBuilder(
            output_dir=output_dir,
            top_k_evidence=max_evidence_chunks * 2,  # retrieve more, then budget
            top_k_graph=15,
            graph_depth=1,
        )
        self.answer_generator = AnswerGeneratorV2(budget=self.budget)

        # State
        self._last_context: HybridContext | None = None
        self._last_result: dict[str, Any] | None = None

    def run(self) -> None:
        """Run the interactive terminal loop."""
        self._print_banner()
        self._load_data()

        while True:
            try:
                query = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            if not query:
                continue

            if query.startswith(':'):
                if not self._handle_command(query):
                    break
                continue

            self._process_query(query)

    def process_single_query(self, query: str) -> dict[str, Any]:
        """Process a single query and return result (for programmatic use)."""
        self._load_data()
        start = time.time()
        plan = self.context_builder.router.route(query)
        context = self.context_builder.build_context(query, plan)
        self._last_context = context
        result = self.answer_generator.generate_answer(
            query=query,
            hybrid_context=context,
            use_llm=self.use_llm,
        )
        self._last_result = result
        result['elapsed'] = round(time.time() - start, 2)
        return result

    def _print_banner(self) -> None:
        """Print startup banner."""
        print(BANNER)
        print(f"  run_id:              {self.run_id}")
        print(f"  dataset:             {self.dataset}")
        print(f"  retrieval_backend:   jsonl")
        print(f"  neptune_loaded:      false")
        print(f"  vector_index:        jsonl-only")
        print(f"  llm_mode:            {'enabled' if self.use_llm else 'disabled (no-llm)'}")
        print(f"  debug:               {'on' if self.debug else 'off'}")
        print(f"  max_evidence_chunks: {self.budget.max_evidence_chunks}")
        print(f"  max_context_chars:   {self.budget.max_total_context_chars}")
        print()
        print("Type :help for commands, or ask a question.")

    def _load_data(self) -> None:
        """Force-load data stores if not loaded."""
        builder = self.context_builder
        if builder.vector_retriever._chunks is None:
            print("  Loading data stores...")
            builder.vector_retriever._load()
            builder.business_retriever._load()
            builder.implementation_retriever._load()
            chunk_count = len(builder.vector_retriever._chunks or [])
            biz_count = len(builder.business_retriever._nodes or [])
            impl_count = len(builder.implementation_retriever._nodes or [])
            print(f"    Evidence chunks: {chunk_count:,}")
            print(f"    Business nodes:  {biz_count}")
            print(f"    Implementation nodes: {impl_count}")

    def _handle_command(self, cmd: str) -> bool:
        """Handle a : command. Returns False to exit."""
        cmd = cmd.strip()

        if cmd == ':exit' or cmd == ':quit' or cmd == ':q':
            print("Exiting.")
            return False
        elif cmd == ':help':
            print(HELP_TEXT)
        elif cmd == ':debug on':
            self.debug = True
            print("Debug mode: ON")
        elif cmd == ':debug off':
            self.debug = False
            print("Debug mode: OFF")
        elif cmd == ':stats':
            self._show_stats()
        elif cmd == ':sources':
            self._show_sources()
        elif cmd == ':last-context':
            self._show_last_context()
        elif cmd == ':last-debug':
            self._show_last_debug()
        else:
            print(f"Unknown command: {cmd}. Type :help for commands.")

        return True

    def _process_query(self, query: str, interactive: bool = True) -> dict[str, Any]:
        """Process a user query through the full pipeline."""
        start = time.time()

        # Route and retrieve
        plan = self.context_builder.router.route(query)
        context = self.context_builder.build_context(query, plan)
        self._last_context = context

        # Generate answer
        result = self.answer_generator.generate_answer(
            query=query,
            hybrid_context=context,
            use_llm=self.use_llm,
        )
        self._last_result = result
        elapsed = time.time() - start

        if interactive:
            self._print_result(result, elapsed)

        return result

    def _print_result(self, result: dict[str, Any], elapsed: float) -> None:
        """Print query result to terminal."""
        debug = result.get('debug', {})

        if self.debug:
            print("\n--- DEBUG ---")
            print(f"  Intent:              {debug.get('intent', '?')}")
            print(f"  Primary path:        {debug.get('primary_path', '?')}")
            print(f"  Secondary paths:     {debug.get('secondary_paths', [])}")
            print(f"  Business nodes:      {debug.get('business_nodes_used', 0)}")
            print(f"  Business edges:      {debug.get('business_edges_used', 0)}")
            print(f"  Impl nodes:          {debug.get('implementation_nodes_used', 0)}")
            print(f"  Impl edges:          {debug.get('implementation_edges_used', 0)}")
            print(f"  Evidence (budgeted): {debug.get('evidence_chunks_used', 0)}")
            print(f"  Evidence (before):   {debug.get('evidence_chunks_before_budget', 0)}")
            print(f"  Context chars:       {debug.get('context_chars_budgeted', 0):,}")
            print(f"  Prompt chars:        {debug.get('prompt_chars', 0):,}")
            print(f"  Answer mode:         {result.get('mode', '?')}")
            print(f"  Elapsed:             {elapsed:.1f}s")
            print("--- END DEBUG ---\n")

        # Warnings
        warnings = result.get('warnings', [])
        if warnings:
            for w in warnings:
                print(f"  ⚠️  {w}")

        # Answer
        print(f"\n{'=' * 60}")
        print(result.get('answer', '[No answer generated]'))
        print(f"{'=' * 60}")

        # Footer
        mode = result.get('mode', '?')
        model = result.get('model', 'none')
        print(f"\n  [mode={mode}, model={model}, {elapsed:.1f}s]")

    def _show_stats(self) -> None:
        """Show data store statistics."""
        builder = self.context_builder
        chunks = builder.vector_retriever._chunks or []
        biz_nodes = builder.business_retriever._nodes or []
        impl_nodes = builder.implementation_retriever._nodes or []
        biz_edges = builder.business_retriever._edges or []
        impl_edges = builder.implementation_retriever._edges or []

        print(f"\n  Data Store Statistics:")
        print(f"    Evidence chunks:       {len(chunks):,}")
        print(f"    Business nodes:        {len(biz_nodes)}")
        print(f"    Business edges:        {len(biz_edges)}")
        print(f"    Implementation nodes:  {len(impl_nodes)}")
        print(f"    Implementation edges:  {len(impl_edges)}")
        print(f"    Run ID:                {self.run_id}")
        print(f"    Dataset:               {self.dataset}")

    def _show_sources(self) -> None:
        """Show available source documents."""
        import json
        docs_path = self.output_dir / 'documents.jsonl'
        if not docs_path.exists():
            print("  No documents.jsonl found.")
            return
        docs = []
        with open(docs_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    docs.append(json.loads(line))
        print(f"\n  Source documents ({len(docs)}):")
        for doc in docs[:20]:
            title = doc.get('title', '')
            source = doc.get('source_path', '')
            print(f"    - {title or source}")
        if len(docs) > 20:
            print(f"    ... and {len(docs) - 20} more")

    def _show_last_context(self) -> None:
        """Show last query's budgeted context."""
        if not self._last_context:
            print("  No previous query.")
            return
        ctx = self._last_context
        print(f"\n  Last context ({ctx.total_items} items, {ctx.total_chars:,} chars):")
        print(f"    Business: {len(ctx.business_context)} items")
        print(f"    Implementation: {len(ctx.implementation_context)} items")
        print(f"    Evidence: {len(ctx.evidence_context)} items")
        print(f"    Constraints: {len(ctx.reasoning_constraints)}")

    def _show_last_debug(self) -> None:
        """Show last query's full debug record."""
        if not self._last_result:
            print("  No previous query.")
            return
        import json
        debug = self._last_result.get('debug', {})
        print(json.dumps(debug, indent=2, ensure_ascii=False))
