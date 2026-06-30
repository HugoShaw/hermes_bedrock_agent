"""Legacy .doc parser: converts binary OLE .doc files to PDF via LibreOffice headless,
then delegates to PdfVlmParser for content extraction.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)


def convert_doc_to_pdf(doc_path: Path, output_dir: Path) -> Path:
    """Convert .doc to .pdf using LibreOffice headless."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "libreoffice", "--headless", "--convert-to", "pdf",
            "--outdir", str(output_dir),
            str(doc_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice .doc→PDF conversion failed (rc={result.returncode}): "
            f"{result.stderr[:300]}"
        )
    pdf_path = output_dir / (doc_path.stem + ".pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"LibreOffice conversion produced no output PDF at {pdf_path}"
        )
    return pdf_path


class DocParser(BaseParser):
    """Parse legacy .doc (OLE binary) files via LibreOffice→PDF→VLM pipeline."""

    @property
    def name(self) -> str:
        return "doc_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return path.suffix.lower() == ".doc" and source_type == SourceType.DOCX

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        base = super().estimated_cost(path)
        base.update({
            "needs_api": True,
            "estimated_cost_usd": 0.01,
            "note": ".doc→PDF→VLM pipeline",
        })
        return base

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        cfg = config or {}
        dry_run: bool = cfg.get("dry_run", False)
        rel = relative_path or path.name

        if dry_run:
            return [ParsedDocument(
                doc_id=generate_doc_id(project_id, rel),
                project_id=project_id,
                source_path=str(path),
                source_type=SourceType.DOCX,
                title=path.stem,
                content_markdown=f"# {path.stem}\n\n*Dry run — .doc VLM not called.*\n",
                metadata={"dry_run": True},
                parse_method="dry_run",
            )]

        logger.info("Converting .doc to PDF: %s", path.name)

        with tempfile.TemporaryDirectory(prefix="doc_conv_") as tmpdir:
            pdf_path = convert_doc_to_pdf(path, Path(tmpdir))

            from .pdf_vlm_parser import PdfVlmParser
            parser = PdfVlmParser()
            docs = parser.parse(pdf_path, project_id, config=cfg, relative_path=rel)

            # Re-tag source info since PdfVlmParser sets source_type=PDF_NATIVE
            for doc in docs:
                doc.source_path = str(path)
                doc.source_type = SourceType.DOCX
                doc.parse_method = "doc_libreoffice_vlm"
                doc.metadata["original_format"] = "ole_doc"
                doc.metadata["conversion"] = "libreoffice_headless"

            return docs
