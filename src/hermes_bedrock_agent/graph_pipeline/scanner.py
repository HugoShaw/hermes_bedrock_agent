"""Phase 0: Scan vlm_parsed and parsed/ directories for markdown files and classify them."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ._utils import normalize_id

logger = logging.getLogger(__name__)


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown text."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            try:
                import yaml
                return yaml.safe_load(text[4:end]) or {}
            except Exception:
                pass
    return {}


def _derive_workbook_name(md_file: Path) -> str:
    """Determine workbook_name from directory structure."""
    parent_name = md_file.parent.name
    grandparent_name = md_file.parent.parent.name if md_file.parent.parent else ""

    if parent_name == "vlm_parsed":
        return grandparent_name
    elif grandparent_name == "parsed":
        return parent_name
    elif grandparent_name == "excel":
        return parent_name
    else:
        return parent_name


def scan_markdown_files(project_id: str, project_name: str, input_dirs: list[str]) -> list[dict]:
    """Recursively find all .md and mermaid .json files under input_dirs and build an inventory list."""
    inventory = []
    for input_dir in input_dirs:
        p = Path(input_dir).expanduser()
        if not p.exists():
            logger.warning("Input dir not found: %s", input_dir)
            continue

        # Collect .md files and mermaid-related .json/.mmd files
        candidate_files = sorted(p.rglob("*.md"))
        # Include mermaid_structure.json and mermaid_parsed.md (already .md)
        # Also include .mmd files and mermaid .json files from mermaid/ dirs
        is_mermaid_dir = "mermaid" in str(p).lower()
        if is_mermaid_dir:
            for json_file in sorted(p.rglob("*.json")):
                if json_file not in candidate_files:
                    candidate_files.append(json_file)
            for mmd_file in sorted(p.rglob("*.mmd")):
                if mmd_file not in candidate_files:
                    candidate_files.append(mmd_file)

        for md_file in sorted(candidate_files):
            workbook_name = _derive_workbook_name(md_file)
            sheet_name = md_file.stem

            # Detect if this is a mermaid artifact
            is_mermaid_file = (
                "mermaid" in str(md_file).lower()
                or md_file.suffix == ".mmd"
                or md_file.name in ("mermaid_structure.json", "mermaid_parsed.md", "mermaid_raw.mmd")
            )

            try:
                content = md_file.read_text(encoding="utf-8")
                first_lines = content[:3000]
            except Exception as exc:
                logger.error("Failed to read %s: %s", md_file, exc)
                content = ""
                first_lines = ""

            frontmatter = _parse_frontmatter(content) if md_file.suffix == ".md" else {}
            if frontmatter.get("source_file"):
                sheet_name = sheet_name or md_file.stem

            # For mermaid dirs, set workbook_name to "mermaid"
            if is_mermaid_file:
                workbook_name = "mermaid"
                # Use parent dir name as subgroup (e.g. "flowchart")
                if md_file.parent.name != "mermaid":
                    sheet_name = f"{md_file.parent.name}_{md_file.stem}"

            sheet_type = _classify_sheet_type(first_lines, sheet_name, content)
            # Override sheet_type for known mermaid artifacts
            if is_mermaid_file:
                sheet_type = "mermaid_flowchart"

            has_mermaid = (
                "```mermaid" in content
                or "flowchart TD" in content
                or "flowchart LR" in content
            )
            has_mapping_table = any(
                kw in content
                for kw in [
                    "Source Table", "Target Table", "マッピング", "Mapping Rules",
                    "Source Field", "Target Field", "ソーステーブル", "ターゲットテーブル",
                ]
            )
            has_api_table = any(
                kw in content
                for kw in [
                    "API", "endpoint", "HTTP", "REST", "request", "response",
                    "APIデータ形式", "API呼出",
                ]
            )
            has_business_rules = any(
                kw in content
                for kw in [
                    "Business Rule", "ビジネスルール", "条件", "Condition",
                    "変換ルール", "Conversion", "TransformationRule",
                ]
            )
            has_uncertain = any(
                kw in content
                for kw in ["Uncertain", "Ambiguous", "不明", "未確定", "要確認"]
            )

            file_id = (
                f"file:{project_id}:{normalize_id(workbook_name)}:{normalize_id(sheet_name)}"
            )

            inventory.append({
                "project_name": project_name,
                "project_id": project_id,
                "file_id": file_id,
                "file_path": str(md_file),
                "file_name": md_file.name,
                "document_group": (
                    workbook_name.split("_")[0]
                    if "_" in workbook_name
                    else workbook_name
                ),
                "workbook_name": workbook_name,
                "sheet_name": sheet_name,
                "sheet_index": _extract_sheet_index(sheet_name),
                "sheet_type": sheet_type,
                "has_mermaid": has_mermaid,
                "has_mapping_table": has_mapping_table,
                "has_api_table": has_api_table,
                "has_business_rules": has_business_rules,
                "has_uncertain_points": has_uncertain,
                "content_length": len(content),
                "read_status": "success" if content else "failed",
                "notes": "",
                "source_file": frontmatter.get("source_file", ""),
                "source_type": frontmatter.get("source_type", ""),
                "parser_type": frontmatter.get("parser_type", ""),
                "document_role": frontmatter.get("document_role", ""),
            })

    return inventory


def _classify_sheet_type(first_lines: str, sheet_name: str, full_content: str) -> str:
    lower = first_lines.lower() + " " + full_content[:5000].lower()

    if any(kw in lower for kw in ["変更履歴", "change history", "表紙", "cover"]):
        return "overview"
    if any(kw in lower for kw in ["目次", "table of contents"]):
        return "overview"
    if any(kw in lower for kw in [
        "```mermaid", "flowchart td", "flowchart lr", "フローチャート",
        "function modules", "decision points", "main process flow",
    ]):
        return "flowchart"
    if any(kw in lower for kw in ["api呼出順序", "api call sequence", "api呼出", "call order"]):
        return "api_call_sequence"
    if any(kw in lower for kw in [
        "マッピング", "mapping rules", "source table", "target table",
        "mapping sheet", "field mapping",
    ]):
        return "mapping_sheet"
    if any(kw in lower for kw in [
        "apiデータ形式", "api data format", "request", "response", "endpoint", "rest",
    ]):
        return "api_request_response_spec"
    if any(kw in lower for kw in ["スクリプト", "script", "フロー図", "flow diagram"]):
        return "middleware_development_spec"
    if any(kw in lower for kw in ["試験", "test", "テスト"]):
        return "test_spec"
    if any(kw in lower for kw in ["レビュー", "review"]):
        return "review_record"
    if any(kw in lower for kw in [
        "取得条件", "retrieval condition", "data retrieval", "抽出条件", "filter",
    ]):
        return "data_retrieval_condition"
    if any(kw in lower for kw in ["変換", "conversion", "コード変換"]):
        return "conversion_rule"
    if any(kw in lower for kw in ["概要", "overview", "summary"]):
        return "overview"
    if any(kw in lower for kw in ["仕様", "specification", "設定"]):
        return "implementation_spec"
    return "unknown"


def _extract_sheet_index(sheet_name: str) -> str:
    m = re.search(r"(\d+)", sheet_name)
    return m.group(1) if m else ""
