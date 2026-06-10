"""Parser strategy selection: maps (source_type, document_role) → parser_type string.

Parser type strings:
  "excel_vlm"   — Excel VLM pipeline (UNO→PDF→VLM)
  "doc_vlm"     — Legacy .doc → LibreOffice PDF → VLM
  "pdf_vlm"     — PDF rendered page-by-page and sent to VLM
  "docx"        — python-docx text+table extraction
  "csv"         — CSV parser (role-aware row preservation)
  "image_vlm"   — image bytes sent to VLM
  "html"        — BeautifulSoup HTML → markdown
  "code"        — raw code wrapped in fenced block
  "markdown"    — passthrough markdown
  "mermaid"     — existing mermaid parser; skip re-run
  "skip"        — do not parse
"""

from __future__ import annotations

from ..models.document import DocumentRole, ProjectFile, SourceType

# parser_type values that should not be executed in this pipeline
SKIP_TYPES = {"skip", "mermaid"}
# parser_type values that call the VLM (need rate-limit delay)
VLM_TYPES = {"pdf_vlm", "image_vlm", "excel_vlm", "doc_vlm"}


def select_parser(pf: ProjectFile) -> tuple[str, str]:
    """Return (parser_type, skip_reason). skip_reason is "" when not skipped."""
    st = pf.source_type
    role = pf.document_role

    if st == SourceType.EXCEL_SHEET:
        return "excel_vlm", ""

    if st == SourceType.PDF_NATIVE:
        return "pdf_vlm", ""

    if st == SourceType.DOCX:
        # Legacy .doc (binary OLE) → LibreOffice conversion then VLM
        if pf.relative_path.lower().endswith(".doc"):
            return "doc_vlm", ""
        return "docx", ""

    if st == SourceType.CSV:
        return "csv", ""

    if st == SourceType.MERMAID:
        return "mermaid", "already handled by mermaid parser"

    if st == SourceType.MARKDOWN:
        return "markdown", ""

    if st == SourceType.HTML:
        return "html", ""

    if st == SourceType.IMAGE:
        if role == DocumentRole.ASSET.value:
            return "skip", f"small icon/asset (size={pf.size_bytes}B)"
        return "image_vlm", ""

    if st == SourceType.CODE:
        # Minified JS → skip
        if ".min." in pf.relative_path.lower():
            return "skip", "minified JS/CSS asset"
        return "code", ""

    if st == SourceType.UNKNOWN:
        name = pf.relative_path.lower()
        if name.endswith(".js") or name.endswith(".css") or name.endswith(".properties"):
            if ".min." in name:
                return "skip", "minified asset"
            return "code", ""
        return "skip", f"unknown file type: {pf.relative_path}"

    if st == SourceType.PLAINTEXT:
        return "code", ""

    return "skip", f"no parser for source_type={st.value}"


def run_strategy_selection(files: list[ProjectFile]) -> None:
    """Assign parser_type and skip_reason to all files in-place."""
    for pf in files:
        parser_type, skip_reason = select_parser(pf)
        pf.parser_type = parser_type
        pf.skip_reason = skip_reason
