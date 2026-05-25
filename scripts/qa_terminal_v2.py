#!/usr/bin/env python
"""
CLI wrapper for Stage 11: QA Terminal V2.

Interactive mode:
    PYTHONPATH=src python scripts/qa_terminal_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --view debug

No-LLM mode:
    PYTHONPATH=src python scripts/qa_terminal_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --no-llm

Single query (non-interactive):
    PYTHONPATH=src python scripts/qa_terminal_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --query "仕訳基礎とは何ですか？" \
      --view debug
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 QA Terminal")
    parser.add_argument("--config", type=str, default="configs/murata_semantic_v2.yaml")
    parser.add_argument("--run-id", type=str, default="murata_semantic_v2")
    parser.add_argument("--dataset", type=str, default="murata")
    parser.add_argument("--view", type=str, choices=["normal", "debug"], default="normal")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM, use deterministic preview")
    parser.add_argument("--max-evidence-chunks", type=int, default=12)
    parser.add_argument("--max-total-context-chars", type=int, default=12000)
    parser.add_argument("--query", type=str, help="Single query (non-interactive)")
    args = parser.parse_args()

    # Resolve output dir
    output_dir = Path("data/outputs") / args.run_id

    from hermes_bedrock_agent.v2.qa.qa_terminal_v2 import QATerminalV2

    terminal = QATerminalV2(
        output_dir=output_dir,
        run_id=args.run_id,
        dataset=args.dataset,
        use_llm=not args.no_llm,
        debug=(args.view == "debug"),
        max_evidence_chunks=args.max_evidence_chunks,
        max_total_context_chars=args.max_total_context_chars,
    )

    if args.query:
        # Single-query mode
        result = terminal.process_single_query(args.query)
        terminal._print_result(result, result.get('elapsed', 0))
        return 0

    # Interactive mode
    terminal.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
