"""Excel VLM adapter: wraps the legacy Excel pipeline as a BaseParser-compatible class.

The Excel→PDF conversion requires LibreOffice UNO bindings which only work with
system Python (/usr/bin/python3). This adapter calls that step as a subprocess,
then uses the in-process PDF rendering and VLM parsing pipeline.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

_UNO_SCRIPT = '''\
import sys, json, importlib, importlib.util

# Bootstrap: make the package importable without triggering __init__.py
# (system Python lacks pandas/etc. needed by csv_parser imported in __init__)
src_root = "{src_root}"
sys.path.insert(0, src_root)

# Create minimal package stubs so relative imports in excel_parser work
import types
pkg = types.ModuleType("hermes_bedrock_agent")
pkg.__path__ = [src_root + "/hermes_bedrock_agent"]
sys.modules["hermes_bedrock_agent"] = pkg

parsing_pkg = types.ModuleType("hermes_bedrock_agent.parsing")
parsing_pkg.__path__ = [src_root + "/hermes_bedrock_agent/parsing"]
sys.modules["hermes_bedrock_agent.parsing"] = parsing_pkg

# Load config (needed by excel_parser)
config_spec = importlib.util.spec_from_file_location(
    "hermes_bedrock_agent.config",
    src_root + "/hermes_bedrock_agent/config.py"
)
config_mod = importlib.util.module_from_spec(config_spec)
sys.modules["hermes_bedrock_agent.config"] = config_mod
config_spec.loader.exec_module(config_mod)

# Load models (SheetInfo, SheetPDF)
models_spec = importlib.util.spec_from_file_location(
    "hermes_bedrock_agent.parsing.models",
    src_root + "/hermes_bedrock_agent/parsing/models.py"
)
models_mod = importlib.util.module_from_spec(models_spec)
sys.modules["hermes_bedrock_agent.parsing.models"] = models_mod
models_spec.loader.exec_module(models_mod)

# Load libreoffice (connect, open_document)
lo_spec = importlib.util.spec_from_file_location(
    "hermes_bedrock_agent.parsing.libreoffice",
    src_root + "/hermes_bedrock_agent/parsing/libreoffice.py"
)
lo_mod = importlib.util.module_from_spec(lo_spec)
sys.modules["hermes_bedrock_agent.parsing.libreoffice"] = lo_mod
lo_spec.loader.exec_module(lo_mod)

# Load excel_parser
ep_spec = importlib.util.spec_from_file_location(
    "hermes_bedrock_agent.parsing.excel_parser",
    src_root + "/hermes_bedrock_agent/parsing/excel_parser.py"
)
ep_mod = importlib.util.module_from_spec(ep_spec)
sys.modules["hermes_bedrock_agent.parsing.excel_parser"] = ep_mod
ep_spec.loader.exec_module(ep_mod)

results = ep_mod.convert_excel_to_pdfs("{xlsx_path}", "{output_dir}")
out = []
for sp in results:
    out.append(sp.model_dump())
print(json.dumps(out, ensure_ascii=False))
'''


class ExcelVlmAdapter(BaseParser):
    """Parse .xlsx files using the legacy Excel VLM pipeline."""

    @property
    def name(self) -> str:
        return "excel_vlm_adapter"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.EXCEL_SHEET

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        base = super().estimated_cost(path)
        base.update({
            "needs_api": True,
            "estimated_cost_usd": 0.05,
            "note": "Excel VLM: cost depends on sheet count and content density",
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
                source_type=SourceType.EXCEL_SHEET,
                title=path.stem,
                content_markdown=f"# {path.stem}\n\n*Dry run — Excel VLM not called.*\n",
                metadata={"dry_run": True},
                parse_method="dry_run",
            )]

        return self._parse_excel(path, project_id, rel, cfg)

    def _parse_excel(
        self,
        path: Path,
        project_id: str,
        relative_path: str,
        cfg: dict[str, Any],
    ) -> list[ParsedDocument]:
        from .pdf_parser import render_all_sheets
        from .vlm_client import parse_all_sheets
        from .text_parser import post_process_all
        from .models import SheetPDF, SheetInfo

        with tempfile.TemporaryDirectory(prefix="excel_vlm_") as tmpdir:
            tmp = Path(tmpdir)
            pdf_dir = tmp / "pdf"
            image_dir = tmp / "images"
            parsed_dir = tmp / "parsed"
            pdf_dir.mkdir()
            image_dir.mkdir()
            parsed_dir.mkdir()

            # Step 1: Excel → PDF via system python subprocess (UNO)
            sheet_pdfs = self._convert_excel_subprocess(path, pdf_dir)

            if not sheet_pdfs:
                raise RuntimeError(f"Excel→PDF conversion returned no sheets for {path.name}")

            # Reconstruct SheetPDF objects from subprocess output
            pdf_objects = []
            for sp_data in sheet_pdfs:
                si_data = sp_data["sheet_info"]
                si = SheetInfo(**si_data)
                pdf_objects.append(SheetPDF(
                    sheet_info=si,
                    pdf_path=sp_data.get("pdf_path", ""),
                    page_size=tuple(sp_data.get("page_size", (0, 0))),
                    pages=sp_data.get("pages", 0),
                    paper_label=sp_data.get("paper_label", ""),
                ))

            # Step 2: PDF → Images (in-process, uses PIL/pdf2image)
            logger.info("Rendering %d sheet PDFs to images...", len(pdf_objects))
            all_images = render_all_sheets(pdf_objects, str(image_dir))

            if not all_images:
                raise RuntimeError(f"PDF→Image rendering returned no results for {path.name}")

            # Step 3: VLM parsing (in-process, includes rate limiting)
            logger.info("VLM parsing %d sheets...", len(all_images))
            parse_results = parse_all_sheets(
                all_images, str(parsed_dir),
                workbook_name=path.stem,
            )

            # Step 4: Post-processing
            parse_results = post_process_all(parse_results)

            # Combine all sheets into unified markdown
            sheet_markdowns: list[str] = []
            for pr, si in zip(parse_results, all_images):
                sheet_name = pr.sheet_info.name
                sheet_idx = pr.sheet_info.index
                header = f"## Sheet {sheet_idx}: {sheet_name}"
                strategy = si.rendering_strategy
                dpi = si.dpi_used
                pages = si.page_count
                tiles = len(si.tile_paths)
                paper = ""
                for sp in pdf_objects:
                    if sp.sheet_info.index == sheet_idx:
                        paper = sp.paper_label
                        break
                meta_comment = (
                    f"<!-- rendering: strategy={strategy}, paper={paper}, "
                    f"dpi={dpi}, pages={pages}, tiles={tiles} -->"
                )
                sheet_markdowns.append(f"{header}\n{meta_comment}\n\n{pr.markdown.strip()}")

            content = f"# {path.stem}\n\n" + "\n\n---\n\n".join(sheet_markdowns)

            metadata: dict[str, Any] = {
                "sheet_count": len(parse_results),
                "sheets": [
                    {
                        "index": pr.sheet_info.index,
                        "name": pr.sheet_info.name,
                        "rows": pr.sheet_info.rows,
                        "cols": pr.sheet_info.cols,
                        "rendering_strategy": si.rendering_strategy,
                        "page_count": si.page_count,
                        "dpi_used": si.dpi_used,
                    }
                    for pr, si in zip(parse_results, all_images)
                ],
            }

            return [ParsedDocument(
                doc_id=generate_doc_id(project_id, relative_path),
                project_id=project_id,
                source_path=str(path),
                source_type=SourceType.EXCEL_SHEET,
                title=path.stem,
                content_markdown=content,
                metadata=metadata,
                parse_method="excel_vlm",
            )]

    def _convert_excel_subprocess(self, xlsx_path: Path, pdf_dir: Path) -> list[dict]:
        """Call convert_excel_to_pdfs via system Python for UNO access."""
        src_root = str(Path(__file__).resolve().parents[2])

        script = _UNO_SCRIPT.format(
            src_root=src_root,
            xlsx_path=str(xlsx_path).replace("\\", "\\\\"),
            output_dir=str(pdf_dir).replace("\\", "\\\\"),
        )

        logger.info("Running Excel→PDF conversion via /usr/bin/python3 (UNO)...")
        result = subprocess.run(
            ["/usr/bin/python3", "-c", script],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error("UNO subprocess stderr: %s", result.stderr)
            raise RuntimeError(
                f"Excel→PDF subprocess failed (rc={result.returncode}): {result.stderr[:500]}"
            )

        stdout = result.stdout.strip()
        if not stdout:
            raise RuntimeError("Excel→PDF subprocess produced no output")

        # The JSON output is on the last line (earlier lines may be log messages)
        lines = stdout.splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("["):
                return json.loads(line)

        raise RuntimeError(f"Excel→PDF subprocess output not parseable: {stdout[:200]}")
