#!/usr/bin/env python
"""Script to run the S3 Graph ETL pipeline.

Usage:
    python scripts/run_s3_graph_etl.py --dry-run
    python scripts/run_s3_graph_etl.py --once --prefix output/semantic_map
"""
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from hermes_bedrock_agent.s3_graph_etl.jobs.run_ingestion import main

if __name__ == "__main__":
    main()
