#!/usr/bin/env python3
"""Validate all outputs from the Excel conversion pipeline.

Checks: structure, file completeness, mermaid syntax, skeleton results, edge labels.
"""
import json
import sys
from pathlib import Path


def validate_output(output_dir: str) -> dict:
    """Validate a single document's output directory."""
    output_path = Path(output_dir)
    results = {
        "document_id": output_path.name,
        "path": str(output_path),
        "checks": [],
        "pass": True,
    }
    
    def check(name: str, condition: bool, detail: str = ""):
        results["checks"].append({
            "name": name,
            "pass": condition,
            "detail": detail,
        })
        if not condition:
            results["pass"] = False
    
    # 1. Directory structure
    required_dirs = ["markdown", "mermaid", "audit", "intermediate", "svg", "png"]
    for d in required_dirs:
        check(f"dir_exists:{d}", (output_path / d).is_dir(),
              f"{output_path / d}")
    
    # 2. Required files
    doc_id = output_path.name
    required_files = [
        f"markdown/{doc_id}.full.md",
        f"markdown/{doc_id}.rag.md",
        f"markdown/{doc_id}.debug.md",
        "mermaid/business_readable/business_readable.mmd",
        "mermaid/semantic_draft/semantic_draft.mmd",
        "mermaid/raw/raw_from_shapes.mmd",
        "intermediate/flow_spec.full.json",
        "intermediate/flow_spec.full.yaml",
        "intermediate/object_inventory.json",
        "intermediate/region_spec.json",
        "audit/semantic_skeleton_check_report.md",
        "audit/override_apply_report.md",
        "audit/semantic_review_summary.md",
        "audit/edge_label_assignment_report.md",
        "audit/region_coverage_report.md",
        "audit/mermaid_render_report.md",
        "audit/run_metadata.json",
        "audit/config_snapshot.yaml",
        "png/business_readable/business_readable.png",
    ]
    
    for f in required_files:
        fpath = output_path / f
        check(f"file_exists:{f}", fpath.is_file(), str(fpath))
    
    # 3. File sizes (non-empty)
    for f in required_files:
        fpath = output_path / f
        if fpath.is_file():
            size = fpath.stat().st_size
            check(f"file_nonempty:{f}", size > 0, f"{size} bytes")
    
    # 4. Mermaid syntax check
    mmd_path = output_path / "mermaid/business_readable/business_readable.mmd"
    if mmd_path.is_file():
        content = mmd_path.read_text(encoding="utf-8")
        check("mermaid:starts_with_flowchart",
              content.strip().startswith("flowchart"),
              content[:30])
        check("mermaid:has_nodes",
              " -->" in content or " ---" in content,
              f"has edges")
    
    # 5. Skeleton check results
    skel_path = output_path / "audit/semantic_skeleton_check_report.md"
    if skel_path.is_file():
        skel_content = skel_path.read_text(encoding="utf-8")
        check("skeleton:overall_pass",
              "✅ PASS" in skel_content,
              "PASS" if "✅ PASS" in skel_content else "FAIL")
    
    # 6. Flow spec validity
    spec_path = output_path / "intermediate/flow_spec.full.json"
    if spec_path.is_file():
        try:
            with open(spec_path, 'r', encoding='utf-8') as f:
                spec = json.load(f)
            # Check for main flowchart sheet
            sheets = list(spec.keys())
            check("flow_spec:has_sheets", len(sheets) > 0, str(sheets))
            
            # Get first sheet with nodes
            for sheet_name, sheet_data in spec.items():
                nodes = sheet_data.get("nodes", [])
                edges = sheet_data.get("edges", [])
                if nodes and len(nodes) > 10:  # Only validate primary flowchart sheets
                    check(f"flow_spec:{sheet_name}:nodes", len(nodes) > 10,
                          f"{len(nodes)} nodes")
                    check(f"flow_spec:{sheet_name}:edges", len(edges) > 5,
                          f"{len(edges)} edges")
                    
                    # Check labeled edges
                    labeled = [e for e in edges if e.get("label")]
                    check(f"flow_spec:{sheet_name}:labeled_edges",
                          len(labeled) >= 10,
                          f"{len(labeled)}/{len(edges)} labeled")
                    break
        except json.JSONDecodeError as e:
            check("flow_spec:valid_json", False, str(e))
    
    # 7. Run metadata
    meta_path = output_path / "audit/run_metadata.json"
    if meta_path.is_file():
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            check("metadata:has_timestamp",
                  "timestamp" in meta or "run_id" in meta or "run_start" in meta,
                  str(list(meta.keys())[:5]))
        except json.JSONDecodeError:
            check("metadata:valid_json", False, "invalid JSON")
    
    # 8. Region mermaid files
    regions_dir = output_path / "mermaid/regions"
    if regions_dir.is_dir():
        region_files = list(regions_dir.glob("*.mmd"))
        check("regions:count", len(region_files) >= 5,
              f"{len(region_files)} region files")
    
    return results


def print_report(results: dict):
    """Print validation results."""
    print(f"\n{'='*60}")
    print(f"Validation Report: {results['document_id']}")
    print(f"{'='*60}")
    print(f"Path: {results['path']}")
    print(f"Overall: {'✅ PASS' if results['pass'] else '❌ FAIL'}")
    print()
    
    passed = [c for c in results["checks"] if c["pass"]]
    failed = [c for c in results["checks"] if not c["pass"]]
    
    print(f"Checks: {len(passed)}/{len(results['checks'])} pass")
    
    if failed:
        print(f"\n❌ FAILED ({len(failed)}):")
        for c in failed:
            print(f"  - {c['name']}: {c['detail']}")
    
    if "--verbose" in sys.argv:
        print(f"\n✅ PASSED ({len(passed)}):")
        for c in passed:
            print(f"  - {c['name']}: {c['detail']}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_outputs.py <output_dir> [--verbose]")
        print("  output_dir: path to document output directory")
        print("  Example: python validate_outputs.py data/outputs/excel_markdown/msha_dss_flowchart")
        sys.exit(1)
    
    output_dir = sys.argv[1]
    if not Path(output_dir).is_dir():
        print(f"ERROR: Directory not found: {output_dir}")
        sys.exit(1)
    
    results = validate_output(output_dir)
    print_report(results)
    
    sys.exit(0 if results["pass"] else 1)


if __name__ == "__main__":
    main()
