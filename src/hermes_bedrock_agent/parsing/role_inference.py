"""Document role inference: multi-signal classification of project files.

Uses filename patterns, parent folder, and source type to assign DocumentRole.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ..models.document import DocumentRole, ProjectFile, SourceType

# ── Filename pattern rules (ordered: first match wins) ──────────────────────
_FILENAME_RULES: list[tuple[re.Pattern, DocumentRole]] = [
    (re.compile(r"合同|contract|契約", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"验收|受入", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"报价|見積|quotation", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"保密|confidential|nda", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"外包", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"テスト|测试|test.*case|HKL\d+", re.IGNORECASE), DocumentRole.TEST_CASE),
    (re.compile(r"IF-[A-Z0-9]+|IF_[A-Z0-9]+", re.IGNORECASE), DocumentRole.SPECIFICATION),
    (re.compile(r"GLISM", re.IGNORECASE), DocumentRole.DATA_MAPPING),
    (re.compile(r"设计|design|仕様|式样|specification|spec", re.IGNORECASE), DocumentRole.DESIGN_DOC),
    (re.compile(r"Interface Test Case", re.IGNORECASE), DocumentRole.TEST_CASE),
    (re.compile(r"Inventory|inventory", re.IGNORECASE), DocumentRole.DATA_SAMPLE),
    (re.compile(r"jquery|\.min\.(js|css)$", re.IGNORECASE), DocumentRole.ASSET),
    (re.compile(r"\.(css|js)$", re.IGNORECASE), DocumentRole.CONFIGURATION),
    (re.compile(r"index\.html?$", re.IGNORECASE), DocumentRole.SPECIFICATION),
]

# ── Parent folder rules ──────────────────────────────────────────────────────
_FOLDER_RULES: list[tuple[re.Pattern, DocumentRole]] = [
    (re.compile(r"开发合同|合同", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"验收申请|受入申請", re.IGNORECASE), DocumentRole.CONTRACT),
    (re.compile(r"A136_洋马"), DocumentRole.CONTRACT),
    (re.compile(r"测试报告|テスト報告|test.*report", re.IGNORECASE), DocumentRole.TEST_CASE),
    (re.compile(r"设计_\d+|設計", re.IGNORECASE), DocumentRole.DESIGN_DOC),
    (re.compile(r"IF03文件式样|IF.*式样|IF.*仕様", re.IGNORECASE), DocumentRole.DATA_MAPPING),
    (re.compile(r"2026Rest-CSV", re.IGNORECASE), DocumentRole.DATA_MAPPING),
    (re.compile(r"HDS式样书.*assets|assets", re.IGNORECASE), DocumentRole.ASSET),
    (re.compile(r"HDS式样书", re.IGNORECASE), DocumentRole.SPECIFICATION),
]

# ── Asset filename patterns (icons, small GIFs) ──────────────────────────────
_ICON_NAME_RE = re.compile(
    r"Icon\$|Icon\.|icon\.|\.gif$|Arrow|Button|Check|Close|Open|Plus|Minus|Edit|Delete",
    re.IGNORECASE,
)


def infer_role(pf: ProjectFile) -> DocumentRole:
    """Infer document role from filename, parent folder, size, and source type."""
    filename = PurePosixPath(pf.relative_path).name
    parent = pf.parent_folder or ""

    # Small images → asset (icons, decorations)
    if pf.source_type == SourceType.IMAGE and pf.size_bytes < 10240:
        return DocumentRole.ASSET

    # Large images in assets/ → screenshot (mapping diagrams, not decorations)
    if pf.source_type == SourceType.IMAGE and "assets" in parent.lower():
        return DocumentRole.SCREENSHOT

    # Minified JS → asset
    if ".min.js" in filename.lower() or ".min.css" in filename.lower():
        return DocumentRole.ASSET

    # ── Filename pattern matching ────────────────────────────────────────────
    for pattern, role in _FILENAME_RULES:
        if pattern.search(filename):
            return role

    # ── Parent folder matching ───────────────────────────────────────────────
    for pattern, role in _FOLDER_RULES:
        if pattern.search(parent):
            return role

    # ── Source type fallbacks ────────────────────────────────────────────────
    if pf.source_type == SourceType.HTML:
        return DocumentRole.SPECIFICATION
    if pf.source_type == SourceType.MERMAID:
        return DocumentRole.PROCESS_FLOW
    if pf.source_type == SourceType.MARKDOWN:
        return DocumentRole.SPECIFICATION
    if pf.source_type == SourceType.CODE:
        return DocumentRole.CONFIGURATION
    if pf.source_type == SourceType.CSV:
        return DocumentRole.DATA_SAMPLE
    if pf.source_type == SourceType.EXCEL_SHEET:
        return DocumentRole.DATA_SAMPLE
    if pf.source_type in (SourceType.PDF_NATIVE, SourceType.DOCX):
        return DocumentRole.CONTRACT

    return DocumentRole.UNKNOWN


def run_role_inference(files: list[ProjectFile]) -> None:
    """Assign document_role to all files in-place."""
    for pf in files:
        role = infer_role(pf)
        pf.document_role = role.value
