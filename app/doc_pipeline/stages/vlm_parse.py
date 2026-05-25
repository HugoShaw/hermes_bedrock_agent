"""Stage 4: VLM parsing — send images to Claude Sonnet, get structured markdown.

Key rules (learned from production):
- NEVER parallelize VLM calls — concurrent Bedrock calls cascade into 300s+ timeouts.
- Images are sent as raw bytes, NOT base64.
- 3-second delay between sheet-level calls.
- Tiles: 2-second delay between tile calls; text-only synthesis after all tiles.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from ..config import PipelineConfig, config as _default_config
from ..models import ParseResult, SheetImages, SheetInfo
from ..utils.bedrock_client import converse_multimodal, converse_text, make_bedrock_client
from ..utils.image_ops import load_for_vlm

logger = logging.getLogger(__name__)


# ── Sheet-type classification ─────────────────────────────────────────────────

def classify_sheet_type(sheet_name: str) -> str:
    """Infer VLM prompt strategy from sheet name."""
    if "変更履歴" in sheet_name:
        return "change_history"
    if "API呼出順序" in sheet_name or "API" in sheet_name and "順序" in sheet_name:
        return "flowchart"
    if "DataSpider開発仕様" in sheet_name or "開発仕様" in sheet_name:
        return "dev_spec"
    if "データ取得条件" in sheet_name:
        return "data_condition"
    if "マッピングシート" in sheet_name or "マッピング" in sheet_name:
        return "mapping"
    if "補足事項" in sheet_name or "フローチャート" in sheet_name:
        return "supplementary"
    return "generic"


# ── Prompt builders ───────────────────────────────────────────────────────────

def _base_context(sheet_name: str, tile_context: str = "") -> str:
    return (
        "You are analyzing a sheet from a Japanese enterprise IF (Interface) Mapping Definition Document "
        "(IFマッピング定義書). This workbook defines the data mapping between SAP S4/HANA and ANDPAD "
        "(construction project management) via DataSpider middleware.\n\n"
        f"Current sheet: {sheet_name}\n"
        f"{tile_context}\n"
    )


def build_prompt(sheet_type: str, sheet_name: str, tile_context: str = "") -> str:
    """Return the VLM prompt for a given sheet type."""
    base = _base_context(sheet_name, tile_context)

    if sheet_type == "change_history":
        return base + """
Please extract the change history table. For each row, identify:
- No (revision number)
- 変更日時 (change date)
- 変更者 (changed by)
- 変更内容 (change description)

Output as a structured markdown table. Also note the overall document revision status."""

    if sheet_type == "flowchart":
        return base + """
This sheet contains API call sequence flowcharts and detailed step tables.

Please extract:
1. **Flowchart diagrams**: Identify all shapes (ovals, rectangles, diamonds), arrows, and labels.
   Describe the flow from start to end for each flow path.
2. **Process scenarios**: The sheet defines multiple scenarios:
   - 【登録】(Registration) - normal flow
   - 【取消】(Cancellation) - with sub-paths:
     - ①発注前 (Before Order)
     - ②請負前 (Before Contract)
     - ③請負済 (Contract Completed)
3. **Step tables**: For each scenario, extract the numbered steps (S01, S02, etc. or 160, 210, etc.)
   with their descriptions, which API is called, and what data operation is performed.
4. **API list**: List all APIs mentioned (発注情報登録API, 発注一覧取得API, 納品一覧取得API, etc.)
5. **Notes/Conditions**: Any special conditions, error handling, or business rules.

Output everything in structured markdown. Preserve Japanese text exactly."""

    if sheet_type == "dev_spec":
        return base + """
This sheet contains DataSpider development specifications.

Please extract:
1. **Processing overview** (処理概要): How this interface works
2. **System flow**: SAP → DataSpider → ANDPAD data flow
3. **Processing steps**: Numbered steps describing the implementation
4. **File formats**: Input/output file specifications
5. **Error handling**: Exception processing rules
6. **Special logic**: Any conditional processing, loops, or branching
7. **Configuration items**: Parameters, settings, file paths

Output in structured markdown. Preserve Japanese text."""

    if sheet_type == "data_condition":
        return base + """
This sheet defines data retrieval conditions for an API call.

Please extract:
1. **API name and endpoint** being called
2. **Request parameters**: For each parameter, extract:
   - No (number)
   - 項目名 (field name in Japanese)
   - API parameter name
   - Data type
   - Required/Optional (必須)
   - Value/conditions
   - Notes/remarks
3. **Response mapping**: What data is returned and how it's used
4. **Filter conditions**: How records are filtered
5. **Pagination or limit settings**

Output as structured markdown tables."""

    if sheet_type == "mapping":
        return base + """
This sheet is a detailed field-level mapping table between systems.

Please extract ALL of the following carefully:

1. **Header metadata**:
   - 文書名 (document name)
   - シート名 (sheet name)
   - IF機能名 (interface function name)
   - IF-ID
   - Source system (送信元) info: name, format, file encoding, delimiter
   - Target system (送信先) info: name, format, API name

2. **Left table (Source/Intermediate)**:
   For EVERY row, extract:
   - No (field number)
   - 項目名称 (field name)
   - 変数/variable name
   - Type (data type: CHAR, NUMC, DATS, CURR, string, integer, etc.)
   - 必須 (required: ○ or blank)
   - 長さ/length
   - 備考 (remarks/notes)

3. **Right table (Target/Destination)**:
   Same structure as left table.

4. **Mapping columns between left and right** (the middle section):
   - マッピング元 (mapping source field reference)
   - 処理内容 (processing content)
   - 編集内容 (edit/transformation content)
   - Conversion rules (CONV_SXXXX references)
   - Fixed values (固定値)
   - Conditional logic

5. **Color coding meaning**:
   - Yellow highlighted rows: indicate what?
   - Red/pink rows: indicate what?

6. **Record types** (レコード区分):
   - Header record (ヘッダレコード)
   - Detail/line record (明細レコード)
   - Note any other record sections

Output ALL field rows as markdown tables. Do not summarize or skip rows.
Preserve Japanese field names and notes exactly."""

    if sheet_type == "supplementary":
        return base + "This is a supplementary/notes sheet. Extract any text content, specifications, or additional rules."

    # generic fallback
    return base + """
Please analyze this sheet image and extract all visible content:
- Tables with all rows and columns
- Text content
- Any diagrams or visual elements
- Notes and annotations
Output in structured markdown."""


def _tile_synthesis_prompt(sheet_name: str, sheet_type: str, tile_results: list[dict]) -> str:
    tiles_text = "\n\n---\n\n".join(
        f"### Tile {i + 1} ({t['position']}):\n{t['content']}"
        for i, t in enumerate(tile_results)
    )
    n = len(tile_results)
    return f"""You previously analyzed {n} tiles from the sheet "{sheet_name}" (type: {sheet_type}).
Each tile covered a different portion of the sheet. Here are all tile analyses:

{tiles_text}

---

Now please synthesize all tile analyses into ONE coherent, complete sheet-level analysis.

Requirements:
1. Merge overlapping content (tiles have 300px overlap)
2. Reconstruct complete tables by combining row fragments across tiles
3. Reconstruct complete mapping relationships
4. Remove duplicate rows that appear in overlapping regions
5. Maintain the correct row ordering (top tiles first, left tiles first)
6. Identify any content that may have been split across tile boundaries
7. Note any gaps or unclear transitions between tiles

For mapping sheets specifically:
- Merge the header metadata from the top-left tile
- Combine all field rows from all tiles into complete tables
- Ensure the source-to-target mapping is properly connected
- List ALL conversion rules (CONV_SXXXX) found across all tiles

Output the synthesized result in this structure:
# Sheet: {sheet_name}

## 1. Sheet Overview
## 2. Header Metadata
## 3. Source Table (Left)
## 4. Target Table (Right)
## 5. Mapping Rules (Middle columns)
## 6. Conversion Rules
## 7. Business Rules / Special Logic
## 8. Uncertain or Ambiguous Points
"""


# ── Core parse functions ──────────────────────────────────────────────────────

def _parse_single(
    client,
    model_id: str,
    img_path: str,
    sheet_type: str,
    sheet_name: str,
) -> tuple[str, dict]:
    prompt = build_prompt(sheet_type, sheet_name)
    img_bytes, media_type = load_for_vlm(img_path, max_dim=7900)
    return converse_multimodal(
        client, model_id, [(img_bytes, media_type)], prompt, max_tokens=12000
    )


def _parse_tiled(
    client,
    model_id: str,
    tile_paths: list[str],
    sheet_type: str,
    sheet_name: str,
    tile_save_dir: Optional[str] = None,
    delay: float = 2.0,
) -> tuple[str, dict]:
    """Process tiles sequentially then synthesize. Returns (markdown, usage)."""
    tile_results: list[dict] = []
    total_usage: dict = {"inputTokens": 0, "outputTokens": 0}

    for i, tile_path in enumerate(sorted(tile_paths)):
        # Parse position from filename: tile_r00_c00.png
        stem = Path(tile_path).stem
        parts = stem.split("_")
        try:
            row = int(parts[-2][1:])
            col = int(parts[-1][1:])
        except (IndexError, ValueError):
            row, col = i, 0
        position = f"row {row}, col {col}"

        tile_context = f"\nThis is tile {i + 1}/{len(tile_paths)} (position: {position}) of the full sheet."
        if sheet_type == "mapping":
            if row == 0 and col == 0:
                tile_context += "\nThis tile contains the TOP-LEFT corner with header metadata and the first columns."
            elif row == 0:
                tile_context += f"\nThis tile contains the TOP area, columns section {col + 1}. Look for mapping/transformation columns."
            elif col == 0:
                tile_context += "\nThis tile contains the LEFT area with source field definitions (lower rows)."
            else:
                tile_context += f"\nThis tile contains the MIDDLE/RIGHT area (rows section {row + 1}, columns section {col + 1})."
        elif sheet_type == "flowchart":
            tile_context += f"\nThis is vertical section {row + 1} of the flowchart."

        prompt = build_prompt(sheet_type, sheet_name, tile_context)
        img_bytes, media_type = load_for_vlm(tile_path, max_dim=4000)

        try:
            result, usage = converse_multimodal(
                client, model_id, [(img_bytes, media_type)], prompt, max_tokens=8000
            )
            total_usage["inputTokens"] += usage.get("inputTokens", 0)
            total_usage["outputTokens"] += usage.get("outputTokens", 0)
            tile_results.append({"tile": Path(tile_path).name, "position": position, "content": result})
            logger.info("      Tile %d/%d (%s): %d chars", i + 1, len(tile_paths), position, len(result))
        except Exception as e:
            logger.error("      Tile %d/%d ERROR: %s", i + 1, len(tile_paths), e)
            tile_results.append({"tile": Path(tile_path).name, "position": position, "content": f"[ERROR: {e}]"})
            time.sleep(5)
            continue

        time.sleep(delay)

    if tile_save_dir:
        os.makedirs(tile_save_dir, exist_ok=True)
        save_path = os.path.join(tile_save_dir, "tiles.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(tile_results, f, ensure_ascii=False, indent=2)

    # Synthesize (text-only call, no images)
    if len(tile_results) > 1:
        logger.info("      Synthesizing %d tiles…", len(tile_results))
        synth_prompt = _tile_synthesis_prompt(sheet_name, sheet_type, tile_results)
        try:
            synth_text, synth_usage = converse_text(
                client, model_id, synth_prompt, max_tokens=12000
            )
            total_usage["inputTokens"] += synth_usage.get("inputTokens", 0)
            total_usage["outputTokens"] += synth_usage.get("outputTokens", 0)
        except Exception as e:
            logger.error("      Synthesis ERROR: %s", e)
            synth_text = "\n\n---\n\n".join(t["content"] for t in tile_results)
    else:
        synth_text = tile_results[0]["content"] if tile_results else "[No content]"

    return synth_text, total_usage


# ── Public API ────────────────────────────────────────────────────────────────

def parse_sheet(
    images: SheetImages,
    output_dir: str,
    cfg: Optional[PipelineConfig] = None,
    client=None,
) -> ParseResult:
    """Run VLM parsing for one sheet. Writes .md and _meta.json to output_dir.

    Uses tiles when available and the sheet type warrants it.
    Never call this in parallel — Bedrock will time out.
    """
    cfg = cfg or _default_config
    if client is None:
        client = make_bedrock_client(cfg.aws_region)

    os.makedirs(output_dir, exist_ok=True)

    sheet_name = images.sheet_info.name
    sheet_type = classify_sheet_type(sheet_name)
    safe_name = f"sheet_{images.sheet_info.index:02d}"
    has_tiles = bool(images.tile_paths)

    logger.info(
        "  [%s] %s (type=%s, tiles=%s)",
        safe_name, sheet_name, sheet_type, has_tiles,
    )

    if has_tiles and sheet_type in ("mapping", "flowchart", "dev_spec"):
        tile_save_dir = os.path.join(output_dir, f"{safe_name}_tiles")
        markdown, usage = _parse_tiled(
            client, cfg.vlm_model_id,
            images.tile_paths, sheet_type, sheet_name,
            tile_save_dir=tile_save_dir,
            delay=2.0,
        )
    else:
        markdown, usage = _parse_single(
            client, cfg.vlm_model_id,
            images.vlm_ready_path or images.full_image_path,
            sheet_type, sheet_name,
        )

    # Save markdown
    md_path = os.path.join(output_dir, f"{safe_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    # Save metadata
    meta = {
        "sheet_index": images.sheet_info.index,
        "sheet_name": sheet_name,
        "sheet_type": sheet_type,
        "has_tiles": has_tiles,
        "usage": usage,
        "output_length": len(markdown),
    }
    meta_path = os.path.join(output_dir, f"{safe_name}_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(
        "    → %d chars, tokens: %din/%dout",
        len(markdown),
        usage.get("inputTokens", 0),
        usage.get("outputTokens", 0),
    )

    return ParseResult(
        sheet_info=images.sheet_info,
        markdown=markdown,
        images=images,
    )


def parse_all_sheets(
    all_images: list[SheetImages],
    output_dir: str,
    cfg: Optional[PipelineConfig] = None,
    resume: bool = True,
) -> list[ParseResult]:
    """Parse every sheet sequentially with inter-sheet delay.

    resume=True skips sheets whose .md already exists and is > 200 bytes.
    """
    cfg = cfg or _default_config
    client = make_bedrock_client(cfg.aws_region)
    results: list[ParseResult] = []

    skip_keys: set[str] = set()
    if resume:
        for fname in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
            if fname.endswith(".md") and fname.startswith("sheet_"):
                path = os.path.join(output_dir, fname)
                if os.path.getsize(path) > 200:
                    skip_keys.add(fname.replace(".md", ""))

    if skip_keys:
        logger.info("Resuming — skipping %d already-parsed sheets", len(skip_keys))

    for images in all_images:
        safe_name = f"sheet_{images.sheet_info.index:02d}"
        if safe_name in skip_keys:
            logger.info("  Skipping %s (already parsed)", safe_name)
            md_path = os.path.join(output_dir, f"{safe_name}.md")
            existing_md = Path(md_path).read_text(encoding="utf-8")
            results.append(ParseResult(sheet_info=images.sheet_info, markdown=existing_md, images=images))
            continue

        try:
            result = parse_sheet(images, output_dir=output_dir, cfg=cfg, client=client)
            results.append(result)
        except Exception as e:
            logger.error("  Sheet %d FAILED: %s", images.sheet_info.index, e)
            results.append(
                ParseResult(
                    sheet_info=images.sheet_info,
                    markdown=f"[PARSE ERROR: {e}]",
                    images=images,
                )
            )

        time.sleep(cfg.vlm_delay_seconds)

    return results
