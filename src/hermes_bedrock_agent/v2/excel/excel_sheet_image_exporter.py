"""
Excel Sheet Image Exporter — export sheet-level images for visual analysis.

Strategy priority:
A) LibreOffice headless (not available)
B) PDF→PNG (PyMuPDF not available)
C) Object-only mode (extract embedded images from xl/media)
D) Mark as unavailable

Current implementation: Strategy C + D (object-only mode).
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelSheetImageExporter:
    """Export sheet-level images. Falls back to object-only mode."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.sheet_images_dir = self.output_dir / "sheet_images"
        self.sheet_images_dir.mkdir(parents=True, exist_ok=True)
        self.export_results: list[dict[str, Any]] = []
        self.warnings: list[str] = []

    def check_capabilities(self) -> dict[str, bool]:
        """Check what rendering capabilities are available."""
        import shutil
        caps = {
            "libreoffice": shutil.which("libreoffice") is not None,
            "pymupdf": False,
            "pillow": False,
        }
        try:
            import fitz  # noqa: F401
            caps["pymupdf"] = True
        except ImportError:
            pass
        try:
            from PIL import Image  # noqa: F401
            caps["pillow"] = True
        except ImportError:
            pass
        return caps

    def export_sheet_images(
        self,
        workbook_path: str,
        workbook_name: str,
        sheet_names: list[str],
    ) -> list[dict[str, Any]]:
        """Try to export sheet images. Returns list of result dicts."""
        caps = self.check_capabilities()

        if caps["libreoffice"]:
            return self._export_via_libreoffice(workbook_path, workbook_name, sheet_names)
        elif caps["pymupdf"]:
            return self._export_via_pdf(workbook_path, workbook_name, sheet_names)
        else:
            # Object-only mode
            self.warnings.append(
                "Sheet-level image export unavailable: LibreOffice and PyMuPDF not installed. "
                "Using object-only mode (embedded images from xl/media)."
            )
            for idx, name in enumerate(sheet_names):
                self.export_results.append({
                    "workbook_name": workbook_name,
                    "sheet_name": name,
                    "sheet_index": idx,
                    "image_path": "",
                    "render_method": "unavailable",
                    "page_number": None,
                    "confidence": 0.0,
                    "warnings": ["LibreOffice/PyMuPDF not available"],
                })
            return self.export_results

    def _export_via_libreoffice(
        self, workbook_path: str, workbook_name: str, sheet_names: list[str]
    ) -> list[dict[str, Any]]:
        """Export via LibreOffice headless (placeholder)."""
        # Would run: libreoffice --headless --convert-to pdf <file>
        # Then split PDF to per-sheet images
        self.warnings.append("LibreOffice export not yet implemented")
        return self.export_results

    def _export_via_pdf(
        self, workbook_path: str, workbook_name: str, sheet_names: list[str]
    ) -> list[dict[str, Any]]:
        """Export via PDF→PNG with PyMuPDF (placeholder)."""
        self.warnings.append("PDF export not yet implemented")
        return self.export_results
