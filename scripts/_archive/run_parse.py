#!/usr/bin/env python3
"""Thin wrapper: calls `hermes parse`. Run with: uv run python scripts/run_parse.py --help"""
import sys
from hermes_bedrock_agent.cli import app

if __name__ == "__main__":
    sys.argv = ["hermes", "parse"] + sys.argv[1:]
    app()
