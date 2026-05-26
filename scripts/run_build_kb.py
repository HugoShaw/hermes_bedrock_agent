#!/usr/bin/env python3
"""Thin wrapper: calls `hermes build-kb`. Run with: uv run python scripts/run_build_kb.py --help"""
import sys
from hermes_bedrock_agent.cli import app

if __name__ == "__main__":
    sys.argv = ["hermes", "build-kb"] + sys.argv[1:]
    app()
