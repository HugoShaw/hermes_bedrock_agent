#!/usr/bin/env python3
"""
Wrapper script for the V2 Vector Evidence Store pipeline.

Usage:
    # JSONL-only mode (default):
    python scripts/build_vector_evidence_store_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --jsonl-only

    # With vector index building:
    python scripts/build_vector_evidence_store_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --build-index

    # Dev mode (limited files):
    python scripts/build_vector_evidence_store_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --max-files 10 \
        --jsonl-only
"""
import sys
from pathlib import Path

# Ensure src/ is on the path when run from project root
project_root = Path(__file__).resolve().parent.parent
src_dir = project_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from hermes_bedrock_agent.v2.pipelines.build_vector_evidence_store import main

if __name__ == "__main__":
    sys.exit(main())
