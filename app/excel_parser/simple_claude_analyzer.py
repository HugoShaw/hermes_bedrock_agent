"""Simple Claude/Bedrock VLM analyzer for visual Excel sheets.

Uses boto3 bedrock-runtime converse API to analyze sheet screenshots
and OOXML object inventory, returning structured flow_spec JSON.

Gracefully degrades if Bedrock is not available.
"""
import os
import json
import base64
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def analyze_visual_sheet(
    screenshot_path: Optional[str],
    object_inventory: dict,
    cell_markdown: str,
    sheet_name: str,
    output_dir: str,
) -> Optional[dict]:
    """Analyze a visual sheet using Claude/Bedrock VLM.

    Args:
        screenshot_path: Path to sheet PNG screenshot (or None)
        object_inventory: Compact object inventory for this sheet
        cell_markdown: Cell content as markdown text
        sheet_name: Name of the sheet
        output_dir: Directory to save raw Claude responses

    Returns:
        Parsed JSON response from Claude, or None if unavailable/failed.
    """
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        logger.warning("boto3 not available; Claude analysis skipped")
        return None

    model_id = os.environ.get("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
    region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

    try:
        config = Config(
            read_timeout=600,
            connect_timeout=30,
            retries={"max_attempts": 2}
        )
        client = boto3.client("bedrock-runtime", region_name=region, config=config)
    except Exception as e:
        logger.warning(f"Cannot create Bedrock client: {e}")
        return None

    # Build the prompt
    has_screenshot = bool(screenshot_path and Path(screenshot_path).exists())
    prompt_text = _build_prompt(object_inventory, cell_markdown, sheet_name, has_screenshot=has_screenshot)

    # Build message content
    content_blocks = []

    # Add screenshot if available
    if screenshot_path and Path(screenshot_path).exists():
        try:
            png_bytes = Path(screenshot_path).read_bytes()
            # Bedrock has a limit on image size; resize if too large (>5MB)
            if len(png_bytes) > 5 * 1024 * 1024:
                png_bytes = _resize_image(png_bytes, max_size_bytes=4 * 1024 * 1024)
                logger.info(f"  Resized screenshot to {len(png_bytes)} bytes")
            content_blocks.append({
                "image": {
                    "format": "png",
                    "source": {"bytes": png_bytes}
                }
            })
            logger.info(f"  Including screenshot: {screenshot_path} ({len(png_bytes)} bytes)")
        except Exception as e:
            logger.warning(f"  Cannot read screenshot {screenshot_path}: {e}")

    content_blocks.append({"text": prompt_text})

    # Call Bedrock converse API
    try:
        logger.info(f"  Calling Bedrock VLM ({model_id}) for sheet '{sheet_name}'...")
        response = client.converse(
            modelId=model_id,
            messages=[{
                "role": "user",
                "content": content_blocks
            }],
            inferenceConfig={
                "maxTokens": 12000,
                "temperature": 0.1
            }
        )

        result_text = response["output"]["message"]["content"][0]["text"]

        # Save raw response
        response_dir = Path(output_dir) / "claude_responses"
        response_dir.mkdir(parents=True, exist_ok=True)
        safe_name = sheet_name.replace("/", "_").replace(" ", "_")
        raw_path = response_dir / f"{safe_name}_raw.txt"
        raw_path.write_text(result_text, encoding="utf-8")
        logger.info(f"  Claude raw response saved to: {raw_path}")

        # Parse JSON from response
        parsed = _extract_json(result_text)
        if parsed:
            parsed_path = response_dir / f"{safe_name}_parsed.json"
            parsed_path.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"  Parsed flow_spec: {len(parsed.get('flow_spec', {}).get('nodes', []))} nodes, "
                        f"{len(parsed.get('flow_spec', {}).get('edges', []))} edges")
            return parsed
        else:
            logger.warning(f"  Could not parse JSON from Claude response for '{sheet_name}'")
            return None

    except Exception as e:
        logger.warning(f"  Bedrock API call failed for sheet '{sheet_name}': {e}")
        return None


def _build_prompt(object_inventory: dict, cell_markdown: str, sheet_name: str, has_screenshot: bool = False) -> str:
    """Build the analysis prompt for Claude."""
    # Make compact inventory
    compact_inv = _compact_inventory(object_inventory)
    
    screenshot_instruction = ""
    if has_screenshot:
        screenshot_instruction = """
IMPORTANT: A screenshot of this Excel sheet is provided as an image. Use it as your PRIMARY visual reference.
Cross-reference what you see in the screenshot with the OOXML object inventory below.
The screenshot shows the actual layout, colors, and visual flow that OOXML data alone cannot capture.
Pay special attention to:
- Arrow directions and connections visible in the screenshot
- Decision diamond branch labels (Yes/No, or condition text near branches)
- Grouping/container boundaries visible in the screenshot
- Text that may be cut off in OOXML but visible in the rendered image
"""
    else:
        screenshot_instruction = """
NOTE: No screenshot is available for this sheet. Rely entirely on the OOXML object inventory below.
Be conservative with edge inference - mark low confidence if connector endpoints are ambiguous.
"""

    prompt = f"""You are analyzing an Excel sheet named "{sheet_name}" that contains visual diagrams (flowcharts, architecture diagrams, or process flows).
{screenshot_instruction}
Your task: Analyze the visual content and the OOXML object inventory below to understand the diagram semantics.

## Rules
1. Do NOT output Mermaid code.
2. Output ONLY valid JSON (no markdown fences, no extra text).
3. Identify the diagram type: flowchart, architecture, mixed, or unknown.
4. For each meaningful shape, create a node entry with:
   - id: a short safe ASCII identifier (e.g., "START", "TOKEN_GET", "READ_FILE")
   - text: the original Japanese/English text from the shape
   - type: one of start, end, process, decision, data, subroutine, annotation, loop_start, loop_end
   - source_shape_id: the Excel shape_id
   - confidence: 0.0-1.0
5. For each connection, create an edge entry with:
   - from: source node id
   - to: target node id
   - label: edge label text (null if none). For decision branches, include the condition text (e.g., "１（登録）の場合", "Yes", "No")
   - confidence: 0.0-1.0
   - evidence: brief explanation of why this edge exists
6. For DECISION nodes, ALWAYS try to identify branch labels:
   - Look for nearby text shapes that indicate branch conditions
   - Common patterns: numbered conditions (1, 2, 3), Yes/No, status codes
   - Include ALL branches you can identify, even if some have lower confidence
7. Skip decorative shapes, containers without semantic meaning, and very small annotation boxes.
8. If evidence is insufficient, mark confidence as low (<0.5). Do NOT guess.
9. Identify the main flow direction (top-to-bottom, left-to-right).
10. For loops, identify both the loop start and loop end markers.

## OOXML Object Inventory (compact)
```json
{compact_inv}
```

## Cell Content
```
{cell_markdown[:2000] if cell_markdown else "(no cell content)"}
```

## Required JSON Output Format
{{
  "sheet_name": "{sheet_name}",
  "diagram_type": "flowchart|architecture|mixed|unknown",
  "flow_direction": "TD|LR|RL|BT",
  "summary_markdown": "Brief description of what this diagram shows",
  "important_texts": ["key text 1", "key text 2"],
  "flow_spec": {{
    "nodes": [
      {{
        "id": "NODE_ID",
        "text": "Original text",
        "type": "process|decision|start|end|data|subroutine|loop_start|loop_end",
        "source_shape_id": "123",
        "confidence": 0.9
      }}
    ],
    "edges": [
      {{
        "from": "NODE_A",
        "to": "NODE_B",
        "label": "branch condition text or null",
        "confidence": 0.85,
        "evidence": "OOXML connector from shape 5 to shape 7"
      }}
    ]
  }},
  "warnings": ["any issues or uncertainties"],
  "confidence": 0.8
}}

Output the JSON now:"""
    return prompt


def _compact_inventory(inventory: dict) -> str:
    """Create a compact version of inventory for Claude prompt."""
    compact = {"shapes": [], "connectors": []}

    for shape in inventory.get("shapes", []):
        compact["shapes"].append({
            "id": shape.get("shape_id", ""),
            "text": shape.get("text", "")[:100],
            "geo": shape.get("geometry", ""),
            "role": shape.get("role_candidate", "unknown"),
            "x": shape.get("xfrm_x") or shape.get("x", 0),
            "y": shape.get("xfrm_y") or shape.get("y", 0),
        })

    for conn in inventory.get("connectors", []):
        compact["connectors"].append({
            "id": conn.get("connector_id", ""),
            "from": conn.get("start_shape_id", ""),
            "to": conn.get("end_shape_id", ""),
            "label": conn.get("nearby_label", ""),
            "arrow": conn.get("has_arrow", True),
        })

    # Truncate if too long
    compact_str = json.dumps(compact, ensure_ascii=False)
    if len(compact_str) > 15000:
        # Reduce to first 80 shapes and 80 connectors
        compact["shapes"] = compact["shapes"][:80]
        compact["connectors"] = compact["connectors"][:80]
        compact["_truncated"] = True
        compact_str = json.dumps(compact, ensure_ascii=False)

    return compact_str


def _resize_image(png_bytes: bytes, max_size_bytes: int = 4 * 1024 * 1024) -> bytes:
    """Resize a PNG image to fit within max_size_bytes."""
    try:
        from PIL import Image
        import io
        
        img = Image.open(io.BytesIO(png_bytes))
        # Iteratively reduce quality/size
        quality = 85
        scale = 1.0
        
        while True:
            if scale < 1.0:
                new_size = (int(img.width * scale), int(img.height * scale))
                resized = img.resize(new_size, Image.LANCZOS)
            else:
                resized = img
            
            buf = io.BytesIO()
            resized.save(buf, format="PNG", optimize=True)
            result = buf.getvalue()
            
            if len(result) <= max_size_bytes or scale < 0.3:
                return result
            
            scale *= 0.7
    except ImportError:
        # If Pillow not available, just return original
        return png_bytes


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from Claude response text."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try to find JSON block in markdown fences
    import re
    json_patterns = [
        r"```json\s*\n(.*?)\n```",
        r"```\s*\n(\{.*?\})\n```",
        r"(\{[^{}]*\"sheet_name\"[^{}]*\})",
    ]
    for pattern in json_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    # Last resort: find the outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None
