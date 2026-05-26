"""PDF vision parser - uses multimodal LLM for scanned/image PDFs."""
from __future__ import annotations

import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, DocumentChunk, ParserType

logger = logging.getLogger(__name__)


class PdfVisionParser(BaseParser):
    """Parse scanned PDFs by rendering to images and using vision LLM.

    This parser is invoked as a second pass for pages where PdfTextParser
    failed to extract quality text.
    """

    @property
    def supported_extensions(self) -> set[str]:
        return {".pdf"}

    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        """Render PDF pages to images and invoke vision LLM.

        NOTE: Full implementation requires pdf2image/Pillow + LLM client.
        This is the structural placeholder that integrates with the LLM module.
        """
        logger.info("PdfVisionParser: would process %s with vision LLM", source_uri)
        # In dry-run or without LLM configured, return placeholder
        source_file = Path(source_uri.split("/")[-1]).name if "/" in source_uri else source_uri
        return [DocumentChunk(
            id=self.make_chunk_id(source_uri, 0, 0),
            source_uri=source_uri,
            source_file=source_file,
            content_type=ContentType.IMAGE,
            title="Vision parse pending",
            text="",
            visual_description="PDF requires vision LLM parsing",
            confidence=0.0,
            parser_type=ParserType.LLM_VISION_PARSER,
            needs_review=True,
        )]
