#!/usr/bin/env python3
"""CLI script to compare two Mermaid flowchart files.

Usage:
    python scripts/compare_mermaid_outputs.py --actual path/to/actual.md --expected path/to/expected.md --output-dir output/

Exit codes:
    0 - Success (no CRITICAL diffs)
    1 - CRITICAL diffs found or error
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowchart_to_mermaid.compare.mermaid_parser import MermaidParser
from flowchart_to_mermaid.compare.graph_normalizer import GraphNormalizer
from flowchart_to_mermaid.compare.graph_diff import GraphDiff
from flowchart_to_mermaid.compare.comparison_reporter import ComparisonReporter


def extract_mermaid_code(text: str) -> str:
    """Extract Mermaid code from markdown fenced blocks or return as-is."""
    import re

    # Try to find ```mermaid ... ``` block
    pattern = r"```mermaid\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try ``` ... ``` block (generic code block)
    pattern = r"```\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        # Check if it looks like mermaid
        if content.startswith(("flowchart", "graph")):
            return content

    # Return as-is (assume it's raw mermaid)
    return text.strip()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Compare two Mermaid flowchart files and generate a diff report."
    )
    parser.add_argument(
        "--actual",
        required=True,
        help="Path to the actual (generated) Mermaid file",
    )
    parser.add_argument(
        "--expected",
        required=True,
        help="Path to the expected (reference) Mermaid file",
    )
    parser.add_argument(
        "--output-dir",
        default="comparison_output",
        help="Directory to write comparison artifacts (default: comparison_output)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed output to stdout",
    )

    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.actual):
        print(f"ERROR: Actual file not found: {args.actual}", file=sys.stderr)
        return 1

    if not os.path.exists(args.expected):
        print(f"ERROR: Expected file not found: {args.expected}", file=sys.stderr)
        return 1

    # Read files
    with open(args.actual, "r", encoding="utf-8") as f:
        actual_text = f.read()

    with open(args.expected, "r", encoding="utf-8") as f:
        expected_text = f.read()

    # Extract mermaid code
    actual_mermaid = extract_mermaid_code(actual_text)
    expected_mermaid = extract_mermaid_code(expected_text)

    if args.verbose:
        print(f"Actual mermaid: {len(actual_mermaid)} chars")
        print(f"Expected mermaid: {len(expected_mermaid)} chars")

    # Parse
    mermaid_parser = MermaidParser()
    actual_parsed = mermaid_parser.parse(actual_mermaid)
    expected_parsed = mermaid_parser.parse(expected_mermaid)

    if args.verbose:
        print(f"Actual parsed: {len(actual_parsed.nodes)} nodes, {len(actual_parsed.edges)} edges")
        print(f"Expected parsed: {len(expected_parsed.nodes)} nodes, {len(expected_parsed.edges)} edges")

    # Normalize
    normalizer = GraphNormalizer()
    actual_normalized = normalizer.normalize(actual_parsed)
    expected_normalized = normalizer.normalize(expected_parsed)

    if args.verbose:
        print(f"Actual normalized: {len(actual_normalized.nodes)} nodes, {len(actual_normalized.edges)} edges")
        print(f"Expected normalized: {len(expected_normalized.nodes)} nodes, {len(expected_normalized.edges)} edges")

    # Diff
    differ = GraphDiff()
    diff_result = differ.diff(actual_normalized, expected_normalized)

    # Report
    reporter = ComparisonReporter()
    saved_files = reporter.save_all(
        output_dir=args.output_dir,
        actual_path=args.actual,
        expected_path=args.expected,
        diff_result=diff_result,
        actual_normalized=actual_normalized,
        expected_normalized=expected_normalized,
    )

    # Print summary
    print(f"\n{'='*60}")
    print("MERMAID COMPARISON RESULTS")
    print(f"{'='*60}")
    print(f"  CRITICAL: {diff_result.severity_counts['CRITICAL']}")
    print(f"  HIGH:     {diff_result.severity_counts['HIGH']}")
    print(f"  MEDIUM:   {diff_result.severity_counts['MEDIUM']}")
    print(f"  LOW:      {diff_result.severity_counts['LOW']}")
    print(f"{'='*60}")
    print(f"  Missing nodes: {len(diff_result.missing_nodes)}")
    print(f"  Extra nodes:   {len(diff_result.extra_nodes)}")
    print(f"  Missing edges: {len(diff_result.missing_edges)}")
    print(f"  Extra edges:   {len(diff_result.extra_edges)}")
    print(f"{'='*60}")
    print(f"\nArtifacts saved to: {args.output_dir}/")
    for name, path in saved_files.items():
        print(f"  - {os.path.basename(path)}")

    # Exit code based on CRITICAL count
    if diff_result.severity_counts["CRITICAL"] > 0:
        print(f"\n❌ FAIL: {diff_result.severity_counts['CRITICAL']} CRITICAL differences found.")
        return 1
    else:
        print(f"\n✅ PASS: No CRITICAL differences.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
