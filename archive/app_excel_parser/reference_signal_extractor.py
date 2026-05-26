"""Reference signal extractor - extracts structured signals from reference markdown.

Instead of naive full-text comparison, this extracts:
- Sheet names
- Business terms
- Possible node texts
- Possible edge labels
- Region titles
- Flow hints
"""
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_reference_signals(reference_path: str) -> dict:
    """Extract structured signals from a reference markdown file.
    
    Returns dict with:
        sheet_names: list[str]
        business_terms: list[str]
        possible_node_texts: list[str]
        possible_edge_labels: list[str]
        possible_region_titles: list[str]
        possible_flow_hints: list[str]
    """
    path = Path(reference_path)
    if not path.exists():
        logger.warning(f"Reference file not found: {reference_path}")
        return _empty_signals()
    
    text = path.read_text(encoding="utf-8")
    
    # Remove code blocks for term extraction (but parse mermaid separately)
    mermaid_blocks = re.findall(r'```mermaid\n(.*?)```', text, re.DOTALL)
    clean_text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    
    signals = {
        "sheet_names": _extract_sheet_names(text),
        "business_terms": _extract_business_terms(clean_text),
        "possible_node_texts": _extract_node_texts(mermaid_blocks),
        "possible_edge_labels": _extract_edge_labels(mermaid_blocks),
        "possible_region_titles": _extract_region_titles(text),
        "possible_flow_hints": _extract_flow_hints(clean_text),
    }
    
    logger.info(
        f"Extracted reference signals: "
        f"{len(signals['business_terms'])} terms, "
        f"{len(signals['possible_node_texts'])} node texts, "
        f"{len(signals['possible_edge_labels'])} edge labels"
    )
    return signals


def extract_generated_signals(flow_spec_dict: dict, mermaid_text: str) -> dict:
    """Extract signals from generated output for comparison."""
    signals = {
        "sheet_names": [],
        "business_terms": [],
        "flow_spec_node_texts": [],
        "flow_spec_edge_labels": [],
        "region_titles": [],
        "mermaid_node_texts": [],
        "mermaid_edge_labels": [],
    }
    
    # From flow_spec
    if flow_spec_dict:
        nodes = flow_spec_dict.get("nodes", [])
        edges = flow_spec_dict.get("edges", [])
        lanes = flow_spec_dict.get("lanes", [])
        
        for node in nodes:
            text = node.get("text", "").strip()
            if text:
                signals["flow_spec_node_texts"].append(text)
                # Extract business terms from node text
                signals["business_terms"].extend(_extract_terms_from_text(text))
        
        for edge in edges:
            label = edge.get("label", "").strip()
            if label:
                signals["flow_spec_edge_labels"].append(label)
        
        for lane in lanes:
            title = lane.get("title", "").strip()
            if title:
                signals["region_titles"].append(title)
    
    # From mermaid text
    if mermaid_text:
        # Extract node labels from mermaid
        node_labels = re.findall(r'\["(.+?)"\]|\{\{"(.+?)"\}\}|\(\["(.+?)"\]\)', mermaid_text)
        for match in node_labels:
            label = next((m for m in match if m), "")
            if label:
                signals["mermaid_node_texts"].append(label.replace("<br/>", " "))
        
        # Extract edge labels
        edge_labels = re.findall(r'\|"(.+?)"\|', mermaid_text)
        signals["mermaid_edge_labels"] = edge_labels
    
    return signals


def compare_signals(ref_signals: dict, gen_signals: dict) -> dict:
    """Compare reference and generated signals to produce metrics."""
    metrics = {}
    
    # Business term coverage
    ref_terms = set(ref_signals.get("business_terms", []))
    gen_terms = set(gen_signals.get("business_terms", []))
    gen_node_texts = set(gen_signals.get("flow_spec_node_texts", []))
    
    if ref_terms:
        # Check how many ref terms appear in generated content
        covered = 0
        for term in ref_terms:
            if term in gen_terms or any(term in t for t in gen_node_texts):
                covered += 1
        metrics["business_term_coverage"] = round(covered / len(ref_terms) * 100, 1)
    else:
        metrics["business_term_coverage"] = 100.0
    
    # Node text coverage
    ref_nodes = set(ref_signals.get("possible_node_texts", []))
    gen_nodes = set(gen_signals.get("flow_spec_node_texts", []))
    
    if ref_nodes:
        covered = 0
        for rn in ref_nodes:
            # Fuzzy match: check if ref node text appears in any generated node
            if rn in gen_nodes or any(rn in gn or gn in rn for gn in gen_nodes):
                covered += 1
        metrics["node_text_coverage"] = round(covered / len(ref_nodes) * 100, 1)
    else:
        metrics["node_text_coverage"] = 100.0
    
    # Edge label coverage
    ref_labels = set(ref_signals.get("possible_edge_labels", []))
    gen_labels = set(gen_signals.get("flow_spec_edge_labels", []))
    
    if ref_labels:
        covered = sum(1 for rl in ref_labels if rl in gen_labels)
        metrics["edge_label_coverage"] = round(covered / len(ref_labels) * 100, 1)
    else:
        metrics["edge_label_coverage"] = 100.0
    
    # Region coverage
    ref_regions = set(ref_signals.get("possible_region_titles", []))
    gen_regions = set(gen_signals.get("region_titles", []))
    
    if ref_regions:
        covered = 0
        for rr in ref_regions:
            if any(rr in gr or gr in rr for gr in gen_regions):
                covered += 1
        metrics["region_coverage"] = round(covered / len(ref_regions) * 100, 1)
    else:
        metrics["region_coverage"] = 100.0
    
    return metrics


def _empty_signals() -> dict:
    return {
        "sheet_names": [],
        "business_terms": [],
        "possible_node_texts": [],
        "possible_edge_labels": [],
        "possible_region_titles": [],
        "possible_flow_hints": [],
    }


def _extract_sheet_names(text: str) -> list[str]:
    """Extract sheet names from headings."""
    names = re.findall(r"Sheet[「:](.+?)[」\n]", text)
    return list(set(names))


def _extract_business_terms(text: str) -> list[str]:
    """Extract business-relevant Japanese terms."""
    terms = set()
    
    # Look for quoted terms
    terms.update(re.findall(r"「(.+?)」", text))
    
    # Look for key business patterns
    patterns = [
        r"(トークン取得|伝票データ|中間ファイル|分割ファイル|処理結果)",
        r"(RETファイル|リターンファイル|発注|納品|明細)",
        r"(税率処理|変数初期化|エラー結果|ヘッダ明細マージ)",
        r"(フォルダ圧縮|ファイル削除|ファイル移動)",
        r"(発注一覧|納品一覧|発注明細|納品明細)",
        r"(入力データ|発注データ|納品データ)",
        r"(ステータス変更|キャンセル)",
    ]
    for pat in patterns:
        terms.update(re.findall(pat, text))
    
    return sorted(terms)


def _extract_node_texts(mermaid_blocks: list[str]) -> list[str]:
    """Extract node label texts from mermaid code blocks."""
    nodes = set()
    for block in mermaid_blocks:
        # Match various node syntaxes
        labels = re.findall(r'\["(.+?)"\]|\{"(.+?)"\}|\(\["(.+?)"\]\)', block)
        for match in labels:
            label = next((m for m in match if m), "")
            if label:
                clean = label.replace("<br/>", "\n").strip()
                if len(clean) > 1:  # Skip single chars
                    nodes.add(clean)
    return sorted(nodes)


def _extract_edge_labels(mermaid_blocks: list[str]) -> list[str]:
    """Extract edge labels from mermaid code blocks."""
    labels = set()
    for block in mermaid_blocks:
        found = re.findall(r'\|"(.+?)"\|', block)
        labels.update(found)
    return sorted(labels)


def _extract_region_titles(text: str) -> list[str]:
    """Extract possible region/function module titles."""
    titles = set()
    # 機能No patterns
    titles.update(re.findall(r"(機能No\d+[：:].+?)(?:\n|$)", text))
    titles.update(re.findall(r"(機能No\.\d+.+?)(?:\n|$)", text))
    return sorted(titles)


def _extract_flow_hints(text: str) -> list[str]:
    """Extract flow structure hints from prose text."""
    hints = []
    # Look for sequential descriptions
    seq_patterns = re.findall(r"(.+?)→(.+?)(?:→|$)", text)
    for src, dst in seq_patterns:
        hints.append(f"{src.strip()} -> {dst.strip()}")
    return hints


def _extract_terms_from_text(text: str) -> list[str]:
    """Extract business terms from a node text."""
    terms = []
    # Key patterns
    if "API" in text:
        terms.append(text.split("API")[0].strip() + "API")
    if "ファイル" in text:
        terms.append(text)
    return terms
