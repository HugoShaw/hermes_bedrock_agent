"""Stage 4: VLM parsing — send images to Claude Sonnet, get structured markdown.

Key production rules:
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

from ..clients.bedrock import converse_multimodal, converse_text, make_bedrock_client
from ..config import Config, config as _default_config
from .image_utils import load_for_vlm
from .models import ParseResult, SheetImages

logger = logging.getLogger(__name__)


def classify_sheet_type(sheet_name: str, workbook_name: str = "") -> str:
    """Classify sheet type from sheet tab name and optional workbook name.

    When the sheet tab name is generic (e.g., "sheet_02"), the workbook name
    is used as a fallback signal for classification.
    """
    # Combine sheet name and workbook name for classification signals
    combined = sheet_name + " " + workbook_name

    if "変更履歴" in sheet_name:
        return "change_history"
    if "API呼出順序" in combined or ("API" in combined and "順序" in combined):
        return "flowchart"
    # フローチャート (flowchart) in either sheet or workbook name → flowchart type
    if "フローチャート" in combined:
        return "flowchart"
    if "DataSpider開発仕様" in combined or "開発仕様" in combined:
        return "dev_spec"
    if "データ取得条件" in sheet_name:
        return "data_condition"
    if "マッピングシート" in combined or ("マッピング" in combined and "定義書" in combined):
        return "mapping"
    if "補足事項" in sheet_name:
        return "supplementary"
    return "generic"


def _base_context(sheet_name: str, tile_context: str = "", workbook_name: str = "") -> str:
    """Build a generic base context for VLM prompts.

    Does NOT hardcode any project-specific system names (SAP, ANDPAD, DataSpider, etc.)
    to avoid cross-project hallucination contamination.
    """
    wb_hint = f" from workbook \"{workbook_name}\"" if workbook_name else ""
    return (
        "You are analyzing a sheet from a Japanese enterprise document"
        f"{wb_hint}. "
        "Extract the content exactly as shown in the image. "
        "Do NOT assume or hallucinate system names, company names, or integration details "
        "that are not visible in the image.\n\n"
        f"Current sheet: {sheet_name}\n"
        f"{tile_context}\n"
    )


def build_prompt(sheet_type: str, sheet_name: str, tile_context: str = "", workbook_name: str = "") -> str:
    base = _base_context(sheet_name, tile_context, workbook_name=workbook_name)

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
3. **Step tables**: For each scenario, extract the numbered steps with descriptions, API calls, and data operations.
4. **API list**: List all APIs mentioned.
5. **Notes/Conditions**: Any special conditions, error handling, or business rules.

Output everything in structured markdown. Preserve Japanese text exactly."""

    if sheet_type == "dev_spec":
        return base + """
This sheet contains development specifications for a data integration interface.

Please extract:
1. **Processing overview** (処理概要): How this interface works
2. **System flow**: The data flow between source and target systems (as shown in the image)
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
2. **Request parameters**: For each parameter, extract No, 項目名, API parameter name, data type, required, value, notes
3. **Response mapping**: What data is returned and how it's used
4. **Filter conditions**: How records are filtered
5. **Pagination or limit settings**

Output as structured markdown tables."""

    if sheet_type == "mapping":
        return base + """
This sheet is a detailed field-level mapping table between systems.

Please extract ALL of the following carefully:

1. **Header metadata**: 文書名, シート名, IF機能名, IF-ID, source/target system info
2. **Left table (Source/Intermediate)**: For EVERY row: No, 項目名称, 変数, Type, 必須, 長さ, 備考
3. **Right table (Target/Destination)**: Same structure as left table.
4. **Mapping columns between left and right**: マッピング元, 処理内容, 編集内容, conversion rules, fixed values
5. **Color coding meaning**: Yellow and red/pink highlighted rows
6. **Record types** (レコード区分): Header, Detail, and other sections

Output ALL field rows as markdown tables. Do not summarize or skip rows.
Preserve Japanese field names and notes exactly."""

    if sheet_type == "supplementary":
        return base + "This is a supplementary/notes sheet. Extract any text content, specifications, or additional rules."

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
3. Remove duplicate rows that appear in overlapping regions
4. Maintain correct row ordering (top tiles first, left tiles first)
5. Note any gaps or unclear transitions between tiles

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


def _parse_single(
    client, model_id: str, img_path: str, sheet_type: str, sheet_name: str,
    workbook_name: str = "", fallback_model_id: Optional[str] = None,
) -> tuple[str, dict]:
    prompt = build_prompt(sheet_type, sheet_name, workbook_name=workbook_name)
    img_bytes, media_type = load_for_vlm(img_path, max_dim=7900)
    return converse_multimodal(
        client, model_id, [(img_bytes, media_type)], prompt,
        max_tokens=12000, fallback_model_id=fallback_model_id,
    )


def _parse_tiled(
    client,
    model_id: str,
    tile_paths: list[str],
    sheet_type: str,
    sheet_name: str,
    tile_save_dir: Optional[str] = None,
    delay: float = 2.0,
    workbook_name: str = "",
    fallback_model_id: Optional[str] = None,
) -> tuple[str, dict]:
    tile_results: list[dict] = []
    total_usage: dict = {"inputTokens": 0, "outputTokens": 0}

    for i, tile_path in enumerate(sorted(tile_paths)):
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
                tile_context += f"\nThis tile contains the TOP area, columns section {col + 1}."
            elif col == 0:
                tile_context += "\nThis tile contains the LEFT area with source field definitions (lower rows)."
            else:
                tile_context += f"\nThis tile contains the MIDDLE/RIGHT area (rows section {row + 1}, columns section {col + 1})."
        elif sheet_type == "flowchart":
            tile_context += f"\nThis is vertical section {row + 1} of the flowchart."

        prompt = build_prompt(sheet_type, sheet_name, tile_context, workbook_name=workbook_name)
        img_bytes, media_type = load_for_vlm(tile_path, max_dim=4000)

        try:
            result, usage = converse_multimodal(
                client, model_id, [(img_bytes, media_type)], prompt,
                max_tokens=8000, fallback_model_id=fallback_model_id,
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
        with open(os.path.join(tile_save_dir, "tiles.json"), "w", encoding="utf-8") as f:
            json.dump(tile_results, f, ensure_ascii=False, indent=2)

    if len(tile_results) > 1:
        logger.info("      Synthesizing %d tiles…", len(tile_results))
        synth_prompt = _tile_synthesis_prompt(sheet_name, sheet_type, tile_results)
        try:
            synth_text, synth_usage = converse_text(
                client, model_id, synth_prompt, max_tokens=12000,
                fallback_model_id=fallback_model_id,
            )
            total_usage["inputTokens"] += synth_usage.get("inputTokens", 0)
            total_usage["outputTokens"] += synth_usage.get("outputTokens", 0)
        except Exception as e:
            logger.error("      Synthesis ERROR: %s", e)
            synth_text = "\n\n---\n\n".join(t["content"] for t in tile_results)
    else:
        synth_text = tile_results[0]["content"] if tile_results else "[No content]"

    return synth_text, total_usage


def _page_synthesis_prompt(sheet_name: str, sheet_type: str, page_results: list[dict]) -> str:
    pages_text = "\n\n---\n\n".join(
        f"### Page {p['page_num']} of {p['total_pages']}:\n{p['content']}"
        for p in page_results
    )
    n = len(page_results)
    return f"""You previously analyzed {n} pages from the sheet "{sheet_name}" (type: {sheet_type}).
Each page is a continuation of the same sheet content (the sheet was too large to fit on one PDF page).
Here are all page analyses:

{pages_text}

---

Now please synthesize all page analyses into ONE coherent, complete sheet-level analysis.

Requirements:
1. Pages are sequential — page 1 contains the top rows, page 2 continues where page 1 ended, etc.
2. Reconstruct complete tables by appending rows from later pages to the table started on page 1
3. The table headers typically only appear on page 1 — do NOT duplicate them
4. Remove any repeated header rows that may appear at the top of subsequent pages
5. Maintain correct row ordering
6. Note any gaps or unclear transitions between pages

Output the final unified result in structured markdown."""


def _parse_multi_page(
    client,
    model_id: str,
    page_image_paths: list[str],
    sheet_type: str,
    sheet_name: str,
    delay: float = 3.0,
    workbook_name: str = "",
    fallback_model_id: Optional[str] = None,
) -> tuple[str, dict]:
    """Parse each page of a multi-page sheet PDF separately, then merge results."""
    page_results: list[dict] = []
    total_usage: dict = {"inputTokens": 0, "outputTokens": 0}
    total_pages = len(page_image_paths)

    for i, page_path in enumerate(page_image_paths):
        page_num = i + 1
        page_context = (
            f"\nThis is page {page_num} of {total_pages} from a multi-page sheet. "
        )
        if page_num == 1:
            page_context += "This page contains the beginning of the sheet (headers and first rows)."
        else:
            page_context += "This page continues from the previous page (may start mid-table)."

        prompt = build_prompt(sheet_type, sheet_name, page_context, workbook_name=workbook_name)
        img_bytes, media_type = load_for_vlm(page_path, max_dim=7900)

        try:
            result, usage = converse_multimodal(
                client, model_id, [(img_bytes, media_type)], prompt,
                max_tokens=12000, fallback_model_id=fallback_model_id,
            )
            total_usage["inputTokens"] += usage.get("inputTokens", 0)
            total_usage["outputTokens"] += usage.get("outputTokens", 0)
            page_results.append({"page_num": page_num, "total_pages": total_pages, "content": result})
            logger.info("      Page %d/%d: %d chars", page_num, total_pages, len(result))
        except Exception as e:
            logger.error("      Page %d/%d ERROR: %s", page_num, total_pages, e)
            page_results.append({"page_num": page_num, "total_pages": total_pages, "content": f"[ERROR: {e}]"})
            time.sleep(5)
            continue

        if i < total_pages - 1:
            time.sleep(delay)

    if len(page_results) > 1:
        logger.info("      Synthesizing %d pages…", len(page_results))
        synth_prompt = _page_synthesis_prompt(sheet_name, sheet_type, page_results)
        try:
            synth_text, synth_usage = converse_text(
                client, model_id, synth_prompt, max_tokens=12000,
                fallback_model_id=fallback_model_id,
            )
            total_usage["inputTokens"] += synth_usage.get("inputTokens", 0)
            total_usage["outputTokens"] += synth_usage.get("outputTokens", 0)
        except Exception as e:
            logger.error("      Page synthesis ERROR: %s", e)
            synth_text = "\n\n---\n\n".join(p["content"] for p in page_results)
    else:
        synth_text = page_results[0]["content"] if page_results else "[No content]"

    return synth_text, total_usage


def parse_sheet(
    images: SheetImages,
    output_dir: str,
    cfg: Optional[Config] = None,
    client=None,
    workbook_name: str = "",
) -> ParseResult:
    """Run VLM parsing for one sheet. Never call this in parallel — Bedrock will time out."""
    cfg = cfg or _default_config
    if client is None:
        client = make_bedrock_client(cfg.aws_region)

    os.makedirs(output_dir, exist_ok=True)
    sheet_name = images.sheet_info.name
    sheet_type = classify_sheet_type(sheet_name, workbook_name=workbook_name)
    safe_name = f"sheet_{images.sheet_info.index:02d}"
    has_tiles = bool(images.tile_paths)
    is_multi_page = images.page_count > 1 and len(images.page_image_paths) > 1

    logger.info("  [%s] %s (type=%s, tiles=%s, pages=%d, strategy=%s)",
                safe_name, sheet_name, sheet_type, has_tiles,
                images.page_count, images.rendering_strategy)

    fallback = cfg.vlm_fallback_model_id or None
    if is_multi_page:
        markdown, usage = _parse_multi_page(
            client, cfg.vlm_model_id,
            images.page_image_paths, sheet_type, sheet_name,
            delay=cfg.vlm_delay_seconds,
            workbook_name=workbook_name,
            fallback_model_id=fallback,
        )
    elif has_tiles and sheet_type in ("mapping", "flowchart", "dev_spec", "generic"):
        tile_save_dir = os.path.join(output_dir, f"{safe_name}_tiles")
        markdown, usage = _parse_tiled(
            client, cfg.vlm_model_id,
            images.tile_paths, sheet_type, sheet_name,
            tile_save_dir=tile_save_dir, delay=2.0,
            workbook_name=workbook_name,
            fallback_model_id=fallback,
        )
    else:
        markdown, usage = _parse_single(
            client, cfg.vlm_model_id,
            images.vlm_ready_path or images.full_image_path,
            sheet_type, sheet_name,
            workbook_name=workbook_name,
            fallback_model_id=fallback,
        )

    md_path = os.path.join(output_dir, f"{safe_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    meta = {
        "sheet_index": images.sheet_info.index,
        "sheet_name": sheet_name,
        "sheet_type": sheet_type,
        "has_tiles": has_tiles,
        "page_count": images.page_count,
        "rendering_strategy": images.rendering_strategy,
        "usage": usage,
        "output_length": len(markdown),
    }
    with open(os.path.join(output_dir, f"{safe_name}_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info("    → %d chars, tokens: %din/%dout",
                len(markdown), usage.get("inputTokens", 0), usage.get("outputTokens", 0))

    return ParseResult(sheet_info=images.sheet_info, markdown=markdown, images=images)


def parse_all_sheets(
    all_images: list[SheetImages],
    output_dir: str,
    cfg: Optional[Config] = None,
    resume: bool = True,
    workbook_name: str = "",
) -> list[ParseResult]:
    """Parse every sheet sequentially. resume=True skips sheets with existing .md > 200 bytes."""
    cfg = cfg or _default_config
    client = make_bedrock_client(cfg.aws_region)
    results: list[ParseResult] = []

    skip_keys: set[str] = set()
    if resume and os.path.isdir(output_dir):
        for fname in os.listdir(output_dir):
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
            result = parse_sheet(images, output_dir=output_dir, cfg=cfg, client=client, workbook_name=workbook_name)
            results.append(result)
        except Exception as e:
            logger.error("  Sheet %d FAILED: %s", images.sheet_info.index, e)
            results.append(ParseResult(sheet_info=images.sheet_info, markdown=f"[PARSE ERROR: {e}]", images=images))

        time.sleep(cfg.vlm_delay_seconds)

    return results
