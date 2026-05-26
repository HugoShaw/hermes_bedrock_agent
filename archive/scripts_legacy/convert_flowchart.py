#!/usr/bin/env python3
"""Script to convert a flowchart PDF/image to Mermaid + SVG."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flowchart_to_mermaid.cli import main

if __name__ == "__main__":
    main()
