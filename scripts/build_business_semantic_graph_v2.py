#!/usr/bin/env python3
"""
Wrapper script for the V2 Business Semantic Graph pipeline (Stage 05).

Usage:
    # Dry-run mode (select candidates, report, no extraction):
    PYTHONPATH=src python scripts/build_business_semantic_graph_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata \
        --dry-run

    # Full extraction mode (heuristic):
    PYTHONPATH=src python scripts/build_business_semantic_graph_v2.py \
        --config configs/murata_semantic_v2.yaml \
        --run-id murata_semantic_v2 \
        --dataset murata
"""

from hermes_bedrock_agent.v2.pipelines.build_business_semantic_graph import main

if __name__ == "__main__":
    main()
