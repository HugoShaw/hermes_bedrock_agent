"""Unified parsing package: legacy Excel VLM pipeline + multi-type v2 parsers."""

from .base_parser import BaseParser
from .docx_parser import DocxParser
from .csv_parser import CsvParser
from .pdf_text_parser import PdfTextParser
from .pdf_vlm_parser import PdfVlmParser
from .mermaid_v2_parser import MermaidParser
from .image_vlm_parser import ImageVlmParser
from .html_parser import HtmlParser
from .code_parser import CodeParser
from .markdown_parser import MarkdownParser
from .registry import ParserRegistry, create_default_registry
from .role_inference import infer_role, run_role_inference
from .strategy import select_parser, run_strategy_selection, SKIP_TYPES, VLM_TYPES
from .orchestrator import run_project_parsing, save_parsing_manifest, ParsingResult
from .utils import compute_content_hash, download_s3_file, sanitize_filename

__all__ = [
    # v2 parsers
    "BaseParser",
    "DocxParser",
    "CsvParser",
    "PdfTextParser",
    "PdfVlmParser",
    "MermaidParser",
    "ImageVlmParser",
    "HtmlParser",
    "CodeParser",
    "MarkdownParser",
    "ParserRegistry",
    "create_default_registry",
    "infer_role",
    "run_role_inference",
    "select_parser",
    "run_strategy_selection",
    "SKIP_TYPES",
    "VLM_TYPES",
    "run_project_parsing",
    "save_parsing_manifest",
    "ParsingResult",
    # utils
    "compute_content_hash",
    "download_s3_file",
    "sanitize_filename",
]
