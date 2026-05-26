#!/usr/bin/env python
"""
CLI wrapper for Stage 11: QA E2E Test V2.

Full test (with LLM):
    PYTHONPATH=src python scripts/qa_e2e_test_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata

No-LLM mode:
    PYTHONPATH=src python scripts/qa_e2e_test_v2.py \
      --config configs/murata_semantic_v2.yaml \
      --run-id murata_semantic_v2 \
      --dataset murata \
      --no-llm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 QA E2E Test")
    parser.add_argument("--config", type=str, default="configs/murata_semantic_v2.yaml")
    parser.add_argument("--run-id", type=str, default="murata_semantic_v2")
    parser.add_argument("--dataset", type=str, default="murata")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM, use deterministic preview")
    parser.add_argument("--max-evidence-chunks", type=int, default=12)
    parser.add_argument("--max-total-context-chars", type=int, default=12000)
    args = parser.parse_args()

    # Resolve output dir
    output_dir = Path("data/outputs") / args.run_id

    from hermes_bedrock_agent.v2.pipelines.qa_e2e_test_v2 import run_e2e_test

    result = run_e2e_test(
        output_dir=output_dir,
        run_id=args.run_id,
        dataset=args.dataset,
        use_llm=not args.no_llm,
        max_evidence_chunks=args.max_evidence_chunks,
        max_total_context_chars=args.max_total_context_chars,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
