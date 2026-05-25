#!/usr/bin/env python3
"""Compare generated Excel-to-Markdown output against reference.

Usage:
    python scripts/compare_excel_markdown_reference.py \
        --generated data/outputs/excel_markdown/markdown/msha_dss_excel_converted.md \
        --reference data/reference/excel_markdown/msha_dss_excel_converted.reference.md \
        --output data/outputs/excel_markdown/audit/reference_compare_report.md
"""
import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.excel_parser.reference_compare import compare_with_reference


def main():
    parser = argparse.ArgumentParser(description="Compare Excel-to-Markdown output")
    parser.add_argument("--generated", type=str, required=True,
                       help="Path to generated markdown")
    parser.add_argument("--reference", type=str, required=True,
                       help="Path to reference markdown")
    parser.add_argument("--output", type=str, required=True,
                       help="Path to output report")
    args = parser.parse_args()
    
    results = compare_with_reference(args.generated, args.reference, args.output)
    
    print(f"Report written: {args.output}")
    print(f"  Sheet coverage:      {results['sheet_coverage']}")
    print(f"  Mermaid blocks:      {results['mermaid_blocks']}")
    print(f"  Shape text coverage: {results['shape_text_coverage']}%")
    print(f"  Connector coverage:  {results['connector_coverage']}%")
    
    if results["issues"]:
        print(f"  Issues: {len(results['issues'])}")
        for issue in results["issues"]:
            print(f"    - {issue}")


if __name__ == "__main__":
    main()
