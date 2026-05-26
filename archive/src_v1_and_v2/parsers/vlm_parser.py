"""VLM parser — multimodal parsing using Bedrock Claude Vision.

Uses clients/bedrock_client.py to call Bedrock Claude with images.
Produces enriched VisualBlocks with:
- visual_summary
- extracted_text
- table_markdown
- diagram_nodes / diagram_edges
- detected_entities

Does NOT call boto3 directly — uses BedrockRuntimeClient.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType
from hermes_bedrock_agent.utils.hashing import make_visual_id

logger = get_logger(__name__)

# Default VLM model
DEFAULT_VLM_MODEL = "anthropic.claude-sonnet-4-20250514-v1:0"

# System prompt for VLM analysis
VLM_SYSTEM_PROMPT = """You are a document analysis assistant. Analyze the provided image and extract structured information.

Respond in JSON format with these fields:
{
  "visual_type": "diagram|table|screenshot|flowchart|architecture|photograph|chart|form",
  "visual_summary": "Brief description of what the image shows",
  "extracted_text": "All readable text in the image",
  "table_markdown": "If table detected, reproduce as markdown table; otherwise empty string",
  "diagram_nodes": ["list of node/entity labels if diagram"],
  "diagram_edges": ["list of edge/connection descriptions if diagram"],
  "detected_entities": ["list of named entities (systems, modules, people, etc.)"],
  "confidence": 0.0-1.0
}

Be thorough but concise. If a field is not applicable, use empty string or empty list."""


class VlmParser:
    """Vision Language Model parser for images and PDF page screenshots.

    Uses BedrockRuntimeClient.invoke_model() to call Claude Vision.
    Supports mock mode for testing without real AWS calls.
    """

    def __init__(
        self,
        bedrock_client: Optional[Any] = None,
        model_id: str = DEFAULT_VLM_MODEL,
        mock_mode: bool = False,
        mock_response: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize VLM parser.

        Args:
            bedrock_client: BedrockRuntimeClient instance.
            model_id: Bedrock model ID for vision calls.
            mock_mode: If True, return mock responses without calling AWS.
            mock_response: Custom mock response dict.
        """
        self._bedrock_client = bedrock_client
        self._model_id = model_id
        self._mock_mode = mock_mode
        self._mock_response = mock_response

    def parse_image(
        self,
        image_base64: str,
        image_format: str,
        document_id: str,
        source_uri: str,
        page: int = 1,
        image_id: str = "",
        context_hint: str = "",
    ) -> VisualBlock:
        """Parse a single image through VLM and return enriched VisualBlock.

        Args:
            image_base64: Base64-encoded image data.
            image_format: Image format (png, jpeg, gif, webp).
            document_id: Parent document ID.
            source_uri: Source URI of the original document.
            page: Page number (for PDFs).
            image_id: Optional image identifier.
            context_hint: Optional context about what the image might contain.

        Returns:
            VisualBlock with VLM-extracted fields populated.
        """
        if self._mock_mode:
            return self._mock_parse(
                image_base64, image_format, document_id, source_uri, page, image_id
            )

        if self._bedrock_client is None:
            raise RuntimeError(
                "VlmParser requires a bedrock_client when mock_mode=False. "
                "Pass a BedrockRuntimeClient instance."
            )

        # Build Claude Vision request
        user_message = "Analyze this image and extract structured information."
        if context_hint:
            user_message += f"\n\nContext: {context_hint}"

        # Map format to media_type
        media_type_map = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        media_type = media_type_map.get(image_format.lower(), "image/png")

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "system": VLM_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": user_message,
                        },
                    ],
                }
            ],
        }

        # Call Bedrock
        response = self._bedrock_client.invoke_model(
            model_id=self._model_id,
            body=request_body,
        )

        # Parse response
        vlm_data = self._parse_response(response)

        # Build VisualBlock
        visual_type = self._map_visual_type(vlm_data.get("visual_type", ""))
        visual_id = make_visual_id(document_id, page, image_id or "vlm")

        return VisualBlock(
            visual_id=visual_id,
            document_id=document_id,
            source_uri=source_uri,
            page=page,
            image_id=image_id,
            visual_type=visual_type,
            visual_summary=vlm_data.get("visual_summary", ""),
            extracted_text=vlm_data.get("extracted_text", ""),
            table_markdown=vlm_data.get("table_markdown", ""),
            diagram_nodes=vlm_data.get("diagram_nodes", []),
            diagram_edges=vlm_data.get("diagram_edges", []),
            detected_entities=vlm_data.get("detected_entities", []),
            image_base64=image_base64,
            image_format=image_format,
            confidence=float(vlm_data.get("confidence", 0.0)),
            model_name=self._model_id,
            created_at=datetime.now(timezone.utc),
        )

    def parse_batch(
        self,
        visual_blocks: list[VisualBlock],
        document_id: str,
        source_uri: str,
    ) -> list[VisualBlock]:
        """Parse multiple VisualBlocks (e.g. PDF page images) through VLM.

        Takes existing VisualBlocks (with image_base64) and enriches them
        with VLM analysis results.

        Args:
            visual_blocks: List of VisualBlocks with image_base64 populated.
            document_id: Parent document ID.
            source_uri: Source URI.

        Returns:
            List of enriched VisualBlocks.
        """
        enriched: list[VisualBlock] = []
        for vb in visual_blocks:
            if not vb.image_base64:
                enriched.append(vb)
                continue

            try:
                result = self.parse_image(
                    image_base64=vb.image_base64,
                    image_format=vb.image_format or "png",
                    document_id=document_id,
                    source_uri=source_uri,
                    page=vb.page,
                    image_id=vb.image_id or "",
                )
                enriched.append(result)
            except Exception as exc:
                logger.error("VLM parse failed for page %d: %s", vb.page, exc)
                enriched.append(vb)  # Keep original on failure

        return enriched

    def _parse_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Extract structured data from Claude Vision response."""
        try:
            content_blocks = response.get("content", [])
            text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    break

            # Try to parse as JSON
            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            return json.loads(text)
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            logger.warning("Failed to parse VLM response as JSON: %s", exc)
            return {
                "visual_summary": text[:500] if text else "",
                "extracted_text": "",
                "confidence": 0.3,
            }

    def _mock_parse(
        self,
        image_base64: str,
        image_format: str,
        document_id: str,
        source_uri: str,
        page: int,
        image_id: str,
    ) -> VisualBlock:
        """Return a mock VisualBlock for testing."""
        mock_data = self._mock_response or {
            "visual_type": "diagram",
            "visual_summary": "Mock VLM analysis result",
            "extracted_text": "Mock extracted text from image",
            "table_markdown": "",
            "diagram_nodes": ["NodeA", "NodeB"],
            "diagram_edges": ["NodeA -> NodeB"],
            "detected_entities": ["SystemA", "ModuleB"],
            "confidence": 0.85,
        }

        visual_type = self._map_visual_type(mock_data.get("visual_type", "diagram"))
        visual_id = make_visual_id(document_id, page, image_id or "vlm")

        return VisualBlock(
            visual_id=visual_id,
            document_id=document_id,
            source_uri=source_uri,
            page=page,
            image_id=image_id,
            visual_type=visual_type,
            visual_summary=mock_data.get("visual_summary", ""),
            extracted_text=mock_data.get("extracted_text", ""),
            table_markdown=mock_data.get("table_markdown", ""),
            diagram_nodes=mock_data.get("diagram_nodes", []),
            diagram_edges=mock_data.get("diagram_edges", []),
            detected_entities=mock_data.get("detected_entities", []),
            image_base64=image_base64[:100],  # Truncate for mock
            image_format=image_format,
            confidence=float(mock_data.get("confidence", 0.85)),
            model_name=f"mock:{self._model_id}",
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _map_visual_type(type_str: str) -> VisualType:
        """Map VLM response visual_type string to VisualType enum."""
        mapping = {
            "diagram": VisualType.DIAGRAM,
            "table": VisualType.TABLE,
            "screenshot": VisualType.PAGE_SCREENSHOT,
            "flowchart": VisualType.FLOWCHART,
            "architecture": VisualType.ARCHITECTURE,
            "photograph": VisualType.PHOTOGRAPH,
            "chart": VisualType.CHART,
            "form": VisualType.FORM,
        }
        return mapping.get(type_str.lower(), VisualType.DIAGRAM)
