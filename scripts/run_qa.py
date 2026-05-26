#!/usr/bin/env python3
"""Thin wrapper: calls `hermes qa`. Run with: uv run python scripts/run_qa.py --help"""
import sys
from hermes_bedrock_agent.cli import app

if __name__ == "__main__":
    sys.argv = ["hermes", "qa"] + sys.argv[1:]
    app()
