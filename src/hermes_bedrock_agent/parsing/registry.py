"""Parser registry: routes files to the correct parser by SourceType."""

from __future__ import annotations

from pathlib import Path

from ..models.document import SourceType
from .base_parser import BaseParser


class ParserRegistry:
    """Routes files to the appropriate parser based on SourceType."""

    def __init__(self) -> None:
        self._parsers: list[BaseParser] = []

    def register(self, parser: BaseParser) -> None:
        self._parsers.append(parser)

    def get_parser(self, path: Path, source_type: SourceType) -> BaseParser | None:
        """Find the first parser that can handle this file."""
        for p in self._parsers:
            if p.can_handle(path, source_type):
                return p
        return None

    @property
    def parsers(self) -> dict[str, BaseParser]:
        """Return registered parsers keyed by name (for inspection)."""
        return {p.name: p for p in self._parsers}

    def get_all_parsers(self) -> list[BaseParser]:
        return list(self._parsers)


def create_default_registry() -> ParserRegistry:
    """Create a registry with all available parsers."""
    from .pdf_vlm_parser import PdfVlmParser
    from .doc_parser import DocParser
    from .docx_parser import DocxParser
    from .csv_parser import CsvParser
    from .pdf_text_parser import PdfTextParser
    from .mermaid_v2_parser import MermaidParser
    from .image_vlm_parser import ImageVlmParser
    from .html_parser import HtmlParser
    from .code_parser import CodeParser
    from .markdown_parser import MarkdownParser
    from .excel_vlm_adapter import ExcelVlmAdapter

    reg = ParserRegistry()
    reg.register(ExcelVlmAdapter())  # Excel VLM (UNO subprocess)
    reg.register(DocParser())        # Legacy .doc → PDF → VLM
    reg.register(PdfVlmParser())     # PDF VLM first — delegates to text parser when VLM disabled
    reg.register(DocxParser())
    reg.register(CsvParser())
    reg.register(PdfTextParser())    # fallback for PDF (never reached via default registry)
    reg.register(MermaidParser())
    reg.register(ImageVlmParser())
    reg.register(HtmlParser())
    reg.register(CodeParser())
    reg.register(MarkdownParser())
    return reg
