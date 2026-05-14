"""Image parser — extracts metadata and prepares VisualBlocks from images.

Handles: PNG, JPG, JPEG, GIF, BMP, TIFF, SVG
Extracts: dimensions, format, file size
Produces: VisualBlock with image_base64 ready for VLM processing
"""

from __future__ import annotations

import base64
import struct
from datetime import datetime, timezone
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.parsers.base import BaseParser, ParserContext, ParserOutput
from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceType
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType
from hermes_bedrock_agent.utils.hashing import content_hash, make_visual_id

logger = get_logger(__name__)


class ImageParser(BaseParser):
    """Parser for image files.

    Extracts image metadata (dimensions, format) and produces a VisualBlock.
    Does NOT call VLM directly — that's handled by VlmParser in a second pass.
    """

    @property
    def parser_name(self) -> str:
        return "ImageParser"

    def parse(self, ctx: ParserContext) -> ParserOutput:
        """Parse an image file.

        Args:
            ctx: Parser context with image bytes.

        Returns:
            ParserOutput with minimal NormalizedDocument and a VisualBlock.
        """
        doc = ctx.document
        image_bytes = ctx.content_bytes
        fmt = self._detect_format(doc.filename, image_bytes)
        width, height = self._get_dimensions(image_bytes, fmt)

        # Create VisualBlock for the image
        visual_block = VisualBlock(
            visual_id=make_visual_id(doc.document_id, 1, "image"),
            document_id=doc.document_id,
            source_uri=doc.source_uri,
            page=1,
            visual_type=VisualType.PHOTOGRAPH if fmt in ("jpg", "jpeg") else VisualType.DIAGRAM,
            image_base64=base64.b64encode(image_bytes).decode(),
            image_format=fmt,
            width=width,
            height=height,
            extracted_text="",
            confidence=0.0,  # Awaiting VLM processing
            model_name="",
            created_at=datetime.now(timezone.utc),
        )

        # Create minimal NormalizedDocument
        normalized = NormalizedDocument(
            document_id=doc.document_id,
            source_uri=doc.source_uri,
            source_type=SourceType.IMAGE,
            title=doc.filename,
            content=f"[Image: {doc.filename}, {width}x{height}, {fmt}]",
            sections=[],
            language="",
            page_count=1,
            content_hash=content_hash(image_bytes),
            metadata={
                "parser": self.parser_name,
                "format": fmt,
                "width": width,
                "height": height,
                "file_size": len(image_bytes),
            },
            visual_block_ids=[visual_block.visual_id],
            created_at=datetime.now(timezone.utc),
        )

        return ParserOutput(
            normalized_document=normalized,
            visual_blocks=[visual_block],
        )

    def _detect_format(self, filename: str, data: bytes) -> str:
        """Detect image format from filename and magic bytes."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        # Verify with magic bytes
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        elif data[:2] == b"\xff\xd8":
            return "jpeg"
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            return "gif"
        elif data[:2] == b"BM":
            return "bmp"
        elif data[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
            return "tiff"

        return ext if ext else "unknown"

    def _get_dimensions(self, data: bytes, fmt: str) -> tuple[int, int]:
        """Extract image dimensions without full decode.

        Returns:
            (width, height) tuple. (0, 0) if unable to determine.
        """
        try:
            if fmt == "png" and len(data) >= 24:
                # PNG IHDR chunk starts at byte 16
                width = struct.unpack(">I", data[16:20])[0]
                height = struct.unpack(">I", data[20:24])[0]
                return width, height

            elif fmt == "jpeg" and len(data) > 2:
                return self._jpeg_dimensions(data)

            elif fmt == "gif" and len(data) >= 10:
                width = struct.unpack("<H", data[6:8])[0]
                height = struct.unpack("<H", data[8:10])[0]
                return width, height

            elif fmt == "bmp" and len(data) >= 26:
                width = struct.unpack("<I", data[18:22])[0]
                height = abs(struct.unpack("<i", data[22:26])[0])
                return width, height

        except (struct.error, IndexError):
            pass

        return 0, 0

    def _jpeg_dimensions(self, data: bytes) -> tuple[int, int]:
        """Parse JPEG SOF marker for dimensions."""
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            # SOF markers: 0xC0 - 0xCF (excluding 0xC4, 0xC8, 0xCC)
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height = struct.unpack(">H", data[i + 5:i + 7])[0]
                width = struct.unpack(">H", data[i + 7:i + 9])[0]
                return width, height
            else:
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + length
        return 0, 0
