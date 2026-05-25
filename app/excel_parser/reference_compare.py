"""Reference comparison tool for Excel-to-Markdown output validation."""
import re
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def compare_with_reference(generated_path: str, reference_path: str,
                          output_path: str) -> dict:
    """Compare generated Markdown against reference and produce audit report.
    
    Returns a summary dict with comparison results.
    """
    results = {
        "generated_exists": False,
        "reference_exists": False,
        "sheet_coverage": "N/A",
        "mermaid_blocks": "N/A",
        "shape_text_coverage": 0.0,
        "connector_coverage": 0.0,
        "issues": [],
        "missing_terms": [],
        "recommendations": [],
    }
    
    # Check file existence
    gen_path = Path(generated_path)
    ref_path = Path(reference_path)
    
    results["generated_exists"] = gen_path.exists()
    results["reference_exists"] = ref_path.exists()
    
    if not gen_path.exists():
        results["issues"].append("Generated markdown does not exist")
        _write_report(results, output_path)
        return results
    
    gen_text = gen_path.read_text(encoding="utf-8")
    
    if not ref_path.exists():
        results["issues"].append("Reference markdown does not exist - skipping comparison")
        results["recommendations"].append("Create reference markdown for future comparisons")
        _write_report(results, output_path)
        return results
    
    ref_text = ref_path.read_text(encoding="utf-8")
    
    # 1. Check sheet names
    gen_sheets = set(re.findall(r"## Sheet: (.+)", gen_text))
    ref_sheets = set(re.findall(r"## Sheet: (.+)", ref_text))
    # Also try reference format: Sheet「xxx」
    ref_sheets.update(re.findall(r"Sheet[「「]([^」」]+)[」」]", ref_text))
    
    if not ref_sheets:
        # Reference doesn't use Sheet format - check for known sheet names
        if "概要" in ref_text and "フローチャート" in ref_text:
            ref_sheets = {"概要", "フローチャート"}
    
    if gen_sheets == ref_sheets or gen_sheets.issuperset(ref_sheets):
        results["sheet_coverage"] = "OK"
    else:
        missing = ref_sheets - gen_sheets
        extra = gen_sheets - ref_sheets
        results["sheet_coverage"] = "NG"
        if missing:
            results["issues"].append(f"Missing sheets: {missing}")
        if extra:
            results["issues"].append(f"Extra sheets: {extra}")
    
    # 2. Check for 概要 and フローチャート
    if "概要" in gen_text:
        pass
    else:
        results["issues"].append("Missing '概要' content")
    
    if "フローチャート" in gen_text:
        pass
    else:
        results["issues"].append("Missing 'フローチャート' content")
    
    # 3. Check Mermaid blocks
    gen_mermaid_count = gen_text.count("```mermaid")
    ref_mermaid_count = ref_text.count("```mermaid")
    
    if gen_mermaid_count >= 1:
        results["mermaid_blocks"] = f"OK ({gen_mermaid_count} blocks)"
    else:
        results["mermaid_blocks"] = "NG (no mermaid blocks)"
        results["issues"].append("No Mermaid code blocks in generated output")
    
    # 4. Check image references
    gen_images = re.findall(r"image\d+\.\w+", gen_text)
    ref_images = re.findall(r"image\d+\.\w+", ref_text)
    if not gen_images and ref_images:
        results["issues"].append("Missing image references")
    
    # 5. Shape text coverage
    # Extract business terms from reference
    ref_terms = _extract_business_terms(ref_text)
    gen_terms = _extract_business_terms(gen_text)
    
    if ref_terms:
        matched = ref_terms & gen_terms
        coverage = len(matched) / len(ref_terms) * 100
        results["shape_text_coverage"] = round(coverage, 1)
        missing_terms = ref_terms - gen_terms
        results["missing_terms"] = sorted(list(missing_terms))[:30]
    
    # 6. Mermaid node/edge coverage
    gen_nodes = set(re.findall(r'N\d{3}\["?([^"\]]+)"?\]', gen_text))
    gen_nodes.update(re.findall(r'S\d+\["?([^"\]]+)"?\]', gen_text))
    ref_nodes = set(re.findall(r'N\d{3}\["?([^"\]]+)"?\]', ref_text))
    ref_nodes.update(re.findall(r'[A-Z]\w+\["?([^"\]]+)"?\]', ref_text))
    
    # 7. Connector coverage
    gen_edges = len(re.findall(r"-->", gen_text))
    ref_edges = len(re.findall(r"-->", ref_text))
    
    if ref_edges > 0:
        results["connector_coverage"] = round(gen_edges / ref_edges * 100, 1)
    elif gen_edges > 0:
        results["connector_coverage"] = 100.0
    
    # Recommendations
    if results["shape_text_coverage"] < 70:
        results["recommendations"].append(
            "Shape text coverage below 70% - check OOXML parser for missing text extraction"
        )
    if results["connector_coverage"] < 50:
        results["recommendations"].append(
            "Connector coverage below 50% - check connector parser and position inference"
        )
    if gen_mermaid_count == 0:
        results["recommendations"].append(
            "No Mermaid blocks generated - check mermaid_builder output"
        )
    
    _write_report(results, output_path)
    return results


def _extract_business_terms(text: str) -> set[str]:
    """Extract Japanese/Chinese business terms (3+ chars) from text."""
    # Match Japanese/Chinese character sequences (3+ chars)
    terms = set()
    patterns = re.findall(r"[ぁ-んァ-ヶー一-龥Ａ-Ｚａ-ｚ]{3,}", text)
    terms.update(patterns)
    
    # Also extract terms in quotes
    quoted = re.findall(r'["\']([^"\']{3,})["\']', text)
    for q in quoted:
        if re.search(r"[ぁ-んァ-ヶー一-龥]", q):
            terms.add(q)
    
    return terms


def _write_report(results: dict, output_path: str) -> None:
    """Write comparison report as Markdown."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    lines = []
    lines.append("# Reference Compare Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Item | Result |")
    lines.append("|---|---|")
    lines.append(f"| Generated Markdown Exists | {'OK' if results['generated_exists'] else 'NG'} |")
    lines.append(f"| Reference Markdown Exists | {'OK' if results['reference_exists'] else 'NG'} |")
    lines.append(f"| Sheet Coverage | {results['sheet_coverage']} |")
    lines.append(f"| Mermaid Blocks | {results['mermaid_blocks']} |")
    lines.append(f"| Shape Text Coverage | {results['shape_text_coverage']}% |")
    lines.append(f"| Connector Coverage | {results['connector_coverage']}% |")
    lines.append("")
    
    # Issues
    if results["issues"]:
        lines.append("## Issues Found")
        lines.append("")
        for issue in results["issues"]:
            lines.append(f"- {issue}")
        lines.append("")
    
    # Missing terms
    if results["missing_terms"]:
        lines.append("## Missing Text Candidates")
        lines.append("")
        for term in results["missing_terms"][:20]:
            lines.append(f"- {term}")
        if len(results["missing_terms"]) > 20:
            lines.append(f"- ... and {len(results['missing_terms']) - 20} more")
        lines.append("")
    
    # Recommendations
    if results["recommendations"]:
        lines.append("## Recommended Fixes")
        lines.append("")
        for rec in results["recommendations"]:
            lines.append(f"- {rec}")
        lines.append("")
    
    # Final judgment
    lines.append("## Final Judgment")
    lines.append("")
    critical_issues = [i for i in results["issues"] 
                      if "Missing" in i or "No Mermaid" in i]
    
    if not results["generated_exists"]:
        lines.append("**FAIL** - Generated markdown not found")
    elif critical_issues:
        lines.append(f"**NEEDS_FIX** - {len(critical_issues)} critical issues found")
    elif results["shape_text_coverage"] < 50:
        lines.append("**NEEDS_FIX** - Shape text coverage below 50%")
    else:
        lines.append("**OK** - Output meets minimum quality threshold")
    
    lines.append("")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    logger.info(f"Comparison report written: {output_path}")
