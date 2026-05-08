"""Image vision parser - uses multimodal LLM for images, diagrams, screenshots."""
from __future__ import annotations

import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, DocumentChunk, ParserType

logger = logging.getLogger(__name__)


class ImageVisionParser(BaseParser):
    """Parse images (diagrams, screenshots, ER diagrams, flowcharts) via vision LLM."""

    @property
    def supported_extensions(self) -> set[str]:
        return {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"}

    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        """Parse image using vision LLM.

        NOTE: Full implementation invokes the multimodal_client.
        This is the structural placeholder.
        """
        source_file = Path(source_uri.split("/")[-1]).name if "/" in source_uri else source_uri
        logger.info("ImageVisionParser: would process %s with vision LLM", source_uri)
        return [DocumentChunk(
            id=self.make_chunk_id(source_uri, 0, 0),
            source_uri=source_uri,
            source_file=source_file,
            content_type=ContentType.DIAGRAM,
            title="Image parse pending",
            text="",
            visual_description="Image requires vision LLM parsing",
            confidence=0.0,
            parser_type=ParserType.LLM_VISION_PARSER,
            needs_review=True,
        )]
