"""
Excel Bedrock Vision Analyzer — sends images to Bedrock Claude Sonnet for analysis.

Uses the existing BedrockRuntimeClient converse API with multimodal image input.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, field
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_visual_schema import BedrockVisualAnalysisRecord

logger = logging.getLogger(__name__)

VISION_ANALYSIS_PROMPT = """You are analyzing an Excel sheet image from an enterprise integration project (Japanese/Chinese enterprise system documentation).

Please extract all useful knowledge from the image.

Focus on:
1. visible text (preserve Japanese/Chinese exactly)
2. flowchart boxes and process steps
3. arrows and connectors (direction matters)
4. decision points (diamond shapes)
5. systems mentioned
6. APIs or interfaces
7. files or data stores
8. tables or data structures
9. field mappings
10. business rules
11. screenshots or UI labels
12. chart title and meaning if any
13. any notes, annotations, or comments

Return structured JSON with this exact format:

{
  "summary": "Brief description of what this image shows",
  "detected_text": ["list of all visible text strings"],
  "detected_objects": [
    {
      "object_type": "flow_step|decision|system|table|field|api|file|note|chart|image|arrow|connector|unknown",
      "label": "visible text label",
      "description": "what this object represents",
      "position_hint": "top-left|top|top-right|center-left|center|center-right|bottom-left|bottom|bottom-right",
      "confidence": 0.9
    }
  ],
  "flowchart_steps": [
    {
      "step_no": 1,
      "label": "step label text",
      "description": "what happens in this step",
      "next_steps": ["label of next step"],
      "condition": "condition for branching if applicable",
      "confidence": 0.9
    }
  ],
  "diagram_nodes": [
    {
      "node_id": "short_id",
      "label": "node label",
      "type": "system|process|file|table|api|screen|datastore|unknown",
      "description": "what this node represents",
      "confidence": 0.9
    }
  ],
  "diagram_edges": [
    {
      "source": "source node label",
      "target": "target node label",
      "relation": "flows_to|calls|reads|writes|maps_to|depends_on|triggers|unknown",
      "label": "edge label if visible",
      "confidence": 0.9
    }
  ],
  "business_terms": ["list of business terms found"],
  "systems": ["list of system names found"],
  "tables": ["list of table names found"],
  "fields": ["list of field names found"],
  "api_names": ["list of API or interface names found"],
  "rules": ["list of business rules described"],
  "warnings": ["any issues or uncertainties"],
  "confidence": 0.8
}

If the image is blank, unreadable, or contains only decorative elements, say so in summary and set confidence to 0.1.
Do not invent objects that are not visible.
Preserve Japanese/Chinese text exactly when visible.
Return ONLY the JSON object, no markdown fences."""


class ExcelBedrockVisionAnalyzer:
    """Analyze Excel visual objects using Bedrock Claude Sonnet multimodal."""

    def __init__(
        self,
        model_id: str = "",
        region: str = "ap-northeast-1",
        max_images: int = 100,
        run_id: str = "",
        dataset: str = "",
    ):
        self.model_id = model_id
        self.region = region
        self.max_images = max_images
        self.run_id = run_id
        self.dataset = dataset
        self.results: list[BedrockVisualAnalysisRecord] = []
        self.warnings: list[str] = []
        self._client = None

    def _get_client(self):
        """Lazy-init Bedrock client with extended timeout for vision."""
        if self._client is None:
            import boto3
            from botocore.config import Config
            # Vision analysis can take 40-120s per image
            config = Config(
                read_timeout=300,
                connect_timeout=10,
                retries={"max_attempts": 2, "mode": "adaptive"},
            )
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=config,
            )
        return self._client

    def _resolve_model_id(self) -> str:
        """Resolve model ID from config or env."""
        if self.model_id:
            return self.model_id
        # Try env vars
        model = os.environ.get("BEDROCK_VLM_MODEL_ID") or os.environ.get("VISION_LLM_MODEL_ID")
        if model:
            return model
        # Fallback
        return "jp.anthropic.claude-sonnet-4-6"

    def analyze_image(
        self,
        image_path: str,
        workbook_name: str = "",
        sheet_name: str = "",
        sheet_id: str = "",
        workbook_id: str = "",
        visual_object_id: str = "",
        analysis_target_type: str = "embedded_image",
    ) -> BedrockVisualAnalysisRecord | None:
        """Analyze a single image with Bedrock Claude Sonnet."""
        if not os.path.exists(image_path):
            self.warnings.append(f"Image not found: {image_path}")
            return None

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = f.read()

        if len(image_data) < 100:
            self.warnings.append(f"Image too small (likely invalid): {image_path}")
            return None

        # Determine media type
        ext = os.path.splitext(image_path)[1].lower()
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        media_type = media_type_map.get(ext, "image/png")

        # SVG cannot be sent directly to Bedrock vision — skip
        if media_type == "image/svg+xml":
            self.warnings.append(f"SVG images not supported for Bedrock analysis: {image_path}")
            return None

        model_id = self._resolve_model_id()

        # Map extension to Bedrock format enum
        format_map = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp"}
        img_format = format_map.get(ext, "png")

        # Build converse API message with image
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": img_format,
                            "source": {"bytes": image_data},
                        }
                    },
                    {
                        "text": VISION_ANALYSIS_PROMPT,
                    },
                ],
            }
        ]

        analysis_id = hashlib.md5(
            f"{workbook_name}|{sheet_name}|{visual_object_id}|{image_path}".encode()
        ).hexdigest()[:16]

        try:
            client = self._get_client()
            logger.info("Analyzing image: %s (model=%s)", os.path.basename(image_path), model_id)

            response = client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={"maxTokens": 4096, "temperature": 0.1},
            )

            # Extract text response
            raw_text = ""
            output = response.get("output", {})
            message = output.get("message", {})
            for block in message.get("content", []):
                if "text" in block:
                    raw_text += block["text"]

            # Parse JSON from response
            parsed = self._parse_json_response(raw_text)

            record = BedrockVisualAnalysisRecord(
                analysis_id=analysis_id,
                workbook_id=workbook_id,
                workbook_name=workbook_name,
                sheet_id=sheet_id,
                sheet_name=sheet_name,
                visual_object_id=visual_object_id,
                image_path=image_path,
                analysis_target_type=analysis_target_type,
                model_id=model_id,
                prompt_version="v1",
                language="ja",
                summary=parsed.get("summary", ""),
                detected_text=parsed.get("detected_text", []),
                detected_objects=parsed.get("detected_objects", []),
                flowchart_steps=parsed.get("flowchart_steps", []),
                diagram_nodes=parsed.get("diagram_nodes", []),
                diagram_edges=parsed.get("diagram_edges", []),
                business_terms=parsed.get("business_terms", []),
                systems=parsed.get("systems", []),
                tables=parsed.get("tables", []),
                fields=parsed.get("fields", []),
                api_names=parsed.get("api_names", []),
                rules=parsed.get("rules", []),
                warnings=parsed.get("warnings", []),
                confidence=parsed.get("confidence", 0.0),
                raw_response=raw_text[:5000],
                run_id=self.run_id,
                dataset=self.dataset,
            )
            self.results.append(record)

            # Rate limiting
            time.sleep(2)
            return record

        except Exception as e:
            err_msg = f"Bedrock analysis failed for {image_path}: {e}"
            logger.error(err_msg)
            self.warnings.append(err_msg)
            # Return partial record
            record = BedrockVisualAnalysisRecord(
                analysis_id=analysis_id,
                workbook_id=workbook_id,
                workbook_name=workbook_name,
                sheet_id=sheet_id,
                sheet_name=sheet_name,
                visual_object_id=visual_object_id,
                image_path=image_path,
                analysis_target_type=analysis_target_type,
                model_id=model_id,
                summary=f"Analysis failed: {e}",
                warnings=[str(e)],
                confidence=0.0,
                run_id=self.run_id,
                dataset=self.dataset,
            )
            self.results.append(record)
            return record

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Parse JSON from Bedrock response, handling markdown fences."""
        # Try direct parse
        text = text.strip()
        # Remove markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            return {
                "summary": text[:500],
                "warnings": ["structured_parse_failed"],
                "confidence": 0.1,
            }

    def analyze_all_images(
        self,
        image_targets: list[dict[str, Any]],
    ) -> list[BedrockVisualAnalysisRecord]:
        """Analyze multiple images. Respects max_images limit."""
        if len(image_targets) > self.max_images:
            logger.warning(
                "Image count %d exceeds max %d, analyzing first %d",
                len(image_targets), self.max_images, self.max_images
            )
            self.warnings.append(
                f"Skipped {len(image_targets) - self.max_images} images (max={self.max_images})"
            )
            image_targets = image_targets[:self.max_images]

        for target in image_targets:
            self.analyze_image(**target)

        return self.results
