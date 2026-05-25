#!/usr/bin/env python3
"""Validate a Mermaid .mmd file."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flowchart_to_mermaid.cli import app

if __name__ == "__main__":
    app(["validate"])
