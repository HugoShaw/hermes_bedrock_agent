"""PDF VLM parser: renders PDF pages as images and extracts content via VLM.

Falls back to PdfTextParser when VLM is disabled or unavailable.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

TOKENS_PER_PAGE_INPUT = 1500
TOKENS_PER_PAGE_OUTPUT = 200
# Claude Sonnet approximate cost (USD per 1K tokens)
COST_PER_1K_INPUT = 0.003
COST_PER_1K_OUTPUT = 0.015
VLM_PAGE_DELAY = 3.0


class PdfVlmParser(BaseParser):
    """Parse PDFs via VLM (page-by-page image extraction). Falls back to text."""

    @property
    def name(self) -> str:
        return "pdf_vlm_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.PDF_NATIVE

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        base = super().estimated_cost(path)
        if path.exists():
            try:
                doc = fitz.open(str(path))
                pages = len(doc)
                doc.close()
                total_input = pages * TOKENS_PER_PAGE_INPUT
                total_output = pages * TOKENS_PER_PAGE_OUTPUT
                cost = (total_input / 1000 * COST_PER_1K_INPUT) + (total_output / 1000 * COST_PER_1K_OUTPUT)
                base.update({
                    "page_count": pages,
                    "estimated_tokens": total_input + total_output,
                    "estimated_input_tokens": total_input,
                    "estimated_output_tokens": total_output,
                    "estimated_cost_usd": round(cost, 4),
                    "needs_api": True,
                })
            except Exception:
                pass
        return base

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        cfg = config or {}
        vlm_enabled: bool = cfg.get("vlm_enabled", True)
        dry_run: bool = cfg.get("dry_run", False)
        output_dir: Path | None = cfg.get("output_dir")
        dpi: int = cfg.get("dpi", 150)

        if not vlm_enabled:
            from .pdf_text_parser import PdfTextParser
            return PdfTextParser().parse(path, project_id, config, relative_path)

        if dry_run:
            return self._dry_run(path, project_id, relative_path)

        return self._parse_with_vlm(path, project_id, relative_path, output_dir, dpi)

    def _dry_run(self, path: Path, project_id: str, relative_path: str) -> list[ParsedDocument]:
        """Return cost estimate without calling VLM."""
        doc = fitz.open(str(path))
        pages = len(doc)
        doc.close()

        total_input = pages * TOKENS_PER_PAGE_INPUT
        total_output = pages * TOKENS_PER_PAGE_OUTPUT
        cost = (total_input / 1000 * COST_PER_1K_INPUT) + (total_output / 1000 * COST_PER_1K_OUTPUT)

        rel = relative_path or path.name
        content = (
            f"# {path.stem}\n\n"
            f"*Dry run — VLM not called.*\n\n"
            f"- Pages: {pages}\n"
            f"- Estimated input tokens: {total_input}\n"
            f"- Estimated output tokens: {total_output}\n"
            f"- Estimated cost: ${cost:.4f} USD\n"
        )
        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.PDF_NATIVE,
            title=path.stem,
            content_markdown=content,
            metadata={
                "dry_run": True,
                "page_count": pages,
                "vlm_pages": 0,
                "estimated_input_tokens": total_input,
                "estimated_output_tokens": total_output,
                "estimated_cost_usd": round(cost, 4),
            },
            parse_method="dry_run",
        )]

    def _parse_with_vlm(
        self,
        path: Path,
        project_id: str,
        relative_path: str,
        output_dir: Path | None,
        dpi: int,
    ) -> list[ParsedDocument]:
        import shutil

        from ..clients.bedrock import make_bedrock_client, converse_multimodal
        from ..config import config as app_config

        client = make_bedrock_client(app_config.aws_region)
        model_id = app_config.vlm_model_id

        pdf_doc = fitz.open(str(path))
        page_count = len(pdf_doc)
        logger.info("PDF VLM parse: %s (%d pages)", path.name, page_count)

        _cleanup_tmp = output_dir is None
        tmp_dir = output_dir or Path(tempfile.mkdtemp(prefix="dualrag_pdf_"))
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            page_markdowns: list[str] = []
            total_input_tokens = 0
            total_output_tokens = 0

            for i, page in enumerate(pdf_doc):
                page_num = i + 1
                img_path = tmp_dir / f"{path.stem}_page{page_num:03d}.png"

                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                pix.save(str(img_path))

                img_bytes = img_path.read_bytes()
                prompt = (
                    f"You are analyzing page {page_num} of a Japanese enterprise document. "
                    "Extract ALL visible content as structured markdown. "
                    "Preserve tables, lists, headers, and Japanese text exactly. "
                    "Include any form fields, stamps, or annotations."
                )

                try:
                    md_text, usage = converse_multimodal(
                        client, model_id, [(img_bytes, "image/png")], prompt
                    )
                    total_input_tokens += usage.get("inputTokens", TOKENS_PER_PAGE_INPUT)
                    total_output_tokens += usage.get("outputTokens", TOKENS_PER_PAGE_OUTPUT)
                    page_markdowns.append(f"## Page {page_num}\n\n{md_text.strip()}")
                    logger.debug("Page %d/%d extracted (%d chars)", page_num, page_count, len(md_text))
                except Exception as exc:
                    logger.warning("VLM failed for page %d: %s", page_num, exc)
                    page_markdowns.append(f"## Page {page_num}\n\n*VLM extraction failed: {exc}*")

                if i < page_count - 1:
                    time.sleep(VLM_PAGE_DELAY)

            pdf_doc.close()

            content = f"# {path.stem}\n\n" + "\n\n---\n\n".join(page_markdowns)
            cost = (total_input_tokens / 1000 * COST_PER_1K_INPUT) + (total_output_tokens / 1000 * COST_PER_1K_OUTPUT)

            rel = relative_path or path.name
            return [ParsedDocument(
                doc_id=generate_doc_id(project_id, rel),
                project_id=project_id,
                source_path=str(path),
                source_type=SourceType.PDF_NATIVE,
                title=path.stem,
                content_markdown=content,
                metadata={
                    "page_count": page_count,
                    "vlm_pages": page_count,
                    "estimated_input_tokens": total_input_tokens,
                    "estimated_output_tokens": total_output_tokens,
                    "estimated_cost_usd": round(cost, 4),
                },
                language=_detect_pdf_language(content),
                parse_method="vlm",
            )]
        finally:
            if _cleanup_tmp:
                shutil.rmtree(tmp_dir, ignore_errors=True)


def _detect_pdf_language(text: str) -> str:
    sample = text[:3000]
    cjk = sum(1 for c in sample if "一" <= c <= "鿿")
    jp = sum(1 for c in sample if "぀" <= c <= "ヿ")
    total = len(sample) if sample else 1
    if jp / total > 0.03:
        return "ja"
    elif cjk / total > 0.05:
        return "zh"
    return "en"
