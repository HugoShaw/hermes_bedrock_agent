"""Image VLM parser: send image bytes to Bedrock VLM for classification and text extraction."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

VLM_DELAY = 3.0
_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp", ".webp"}

_IMAGE_PROMPT = """\
Analyze this image from a Japanese enterprise software project.

Step 1 — Classify the image as one of:
  diagram, flowchart, architecture, screenshot, table_image, scanned_doc, icon, logo, photo, mapping_screenshot

Step 2 — Extract ALL visible text verbatim. Preserve Japanese characters exactly.

Step 3 — Describe any tables, charts, data mappings, or flow structures you see.
For mapping screenshots (e.g., field-to-field mapping tables), extract each row as:
  Source Field | Target Field | Transformation/Notes

Output as structured markdown. Start with the image category on the first line as:
Category: <category>
"""


class ImageVlmParser(BaseParser):
    """Parse images via Bedrock VLM."""

    def __init__(self, delay: float = VLM_DELAY) -> None:
        self._delay = delay
        self._call_count = 0

    @property
    def name(self) -> str:
        return "image_vlm_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.IMAGE

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        base = super().estimated_cost(path)
        base.update({"needs_api": True, "estimated_cost_usd": 0.005, "estimated_tokens": 1700})
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
                source_type=SourceType.IMAGE,
                title=path.stem,
                content_markdown=f"# {path.stem}\n\n*Dry run — VLM not called.*\n",
                metadata={"dry_run": True},
                parse_method="dry_run",
            )]

        ext = path.suffix.lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".tiff": "image/tiff", ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        mime = mime_map.get(ext, "image/png")

        if self._call_count > 0:
            time.sleep(self._delay)

        from ..clients.bedrock import make_bedrock_client, converse_multimodal
        from ..config import config as app_config

        client = make_bedrock_client(app_config.aws_region)
        model_id = app_config.vlm_model_id

        img_bytes = path.read_bytes()
        logger.info("Image VLM parse: %s (%d bytes)", path.name, len(img_bytes))

        try:
            md_text, usage = converse_multimodal(client, model_id, [(img_bytes, mime)], _IMAGE_PROMPT)
            self._call_count += 1
        except Exception as exc:
            logger.warning("VLM failed for %s: %s", path.name, exc)
            md_text = f"*VLM extraction failed: {exc}*"
            usage = {}

        # Extract category from first line
        image_category = "unknown"
        lines = md_text.strip().splitlines()
        if lines and lines[0].lower().startswith("category:"):
            image_category = lines[0].split(":", 1)[1].strip()
            md_text = "\n".join(lines[1:]).strip()

        content = f"# {path.stem}\n\n**Image category:** {image_category}\n\n{md_text}"

        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.IMAGE,
            title=path.stem,
            content_markdown=content,
            metadata={
                "image_category": image_category,
                "file_size_bytes": len(img_bytes),
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
            },
            parse_method="image_vlm",
        )]
