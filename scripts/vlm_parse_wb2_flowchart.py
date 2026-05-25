#!/usr/bin/env python3
"""VLM parser for the DSSスクリプト改修概要_フローチャート workbook (2 sheets).

Processes tiles through Claude Sonnet for visual understanding, then synthesizes.
"""
import os
import sys
import json
import time
import base64
from pathlib import Path
from datetime import datetime

import boto3
from botocore.config import Config
from PIL import Image
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/projects/hermes_bedrock_agent/.env"))
Image.MAX_IMAGE_PIXELS = 500_000_000

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
MODEL_ID = os.getenv("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
OUTPUT_BASE = os.path.expanduser("~/projects/hermes_bedrock_agent/outputs/wb2_flowchart")
IMG_DIR = f"{OUTPUT_BASE}/images"
TILE_DIR = f"{OUTPUT_BASE}/tiles"
PARSED_DIR = f"{OUTPUT_BASE}/vlm_parsed"
os.makedirs(PARSED_DIR, exist_ok=True)

client = boto3.client(
    'bedrock-runtime',
    config=Config(
        region_name=AWS_REGION,
        read_timeout=600,
        retries={'max_attempts': 3, 'mode': 'adaptive'}
    )
)

SHEET_NAMES = ["概要", "フローチャート"]
WORKBOOK_NAME = "M社様_DSSスクリプト改修概要_フローチャート"
S3_EXCEL_PATH = "s3://s3-hulftchina-rd/サンプル20260519/01_基本設計/M社様_DSSスクリプト改修概要_フローチャート.xlsx"

total_in = 0
total_out = 0


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def call_vlm(messages: list, max_tokens: int = 12000) -> dict:
    global total_in, total_out
    response = client.converse(
        modelId=MODEL_ID,
        messages=messages,
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1}
    )
    usage = response.get("usage", {})
    total_in += usage.get("inputTokens", 0)
    total_out += usage.get("outputTokens", 0)
    return response


def get_text(response: dict) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(block.get("text", "") for block in content)


def make_image_block(path: str) -> dict:
    return {
        "image": {
            "format": "png",
            "source": {"bytes": open(path, "rb").read()}
        }
    }


def parse_sheet_overview(sheet_idx: int) -> str:
    """Parse sheet with overview prompt (general purpose)."""
    sheet_name = SHEET_NAMES[sheet_idx - 1]
    tile_dir = Path(f"{TILE_DIR}/sheet_{sheet_idx:02d}")
    tiles = sorted(tile_dir.glob("tile_*.png"))
    
    print(f"\n{'='*60}")
    print(f"Sheet {sheet_idx:02d}: {sheet_name} ({len(tiles)} tiles)")
    print(f"{'='*60}")
    
    # Process each tile
    tile_results = []
    for tile_path in tiles:
        print(f"  Processing {tile_path.name}...", end=" ", flush=True)
        t0 = time.time()
        
        # Determine tile position from filename
        parts = tile_path.stem.split("_")
        row = int(parts[1][1:])
        col = int(parts[2][1:])
        
        if sheet_idx == 1:
            prompt = f"""This is tile (row={row}, col={col}) of sheet "{sheet_name}" from workbook "{WORKBOOK_NAME}".
This sheet is an overview/summary sheet for a DSS (DataSpider) script modification project.

Please analyze this tile and extract:
1. All visible text content (preserve Japanese exactly)
2. Any tables (reproduce as markdown tables)
3. Section headers and structure
4. Any metadata (dates, authors, versions, document IDs)
5. Any references to other systems or processes

Output in structured markdown format."""
        else:
            prompt = f"""This is tile (row={row}, col={col}) of sheet "{sheet_name}" from workbook "{WORKBOOK_NAME}".
This sheet contains a flowchart/process diagram for DSS script modifications.

Please analyze this tile and extract:
1. All flowchart nodes (rectangles, diamonds, ovals, parallelograms) with their text labels
2. All arrows/connections between nodes (direction and labels)
3. Decision points (diamonds) with their branch labels (Yes/No, True/False, etc.)
4. Process steps (rectangles) with their descriptions
5. Start/End points (ovals)
6. Any annotations, comments, or labels
7. The spatial position of elements (top/middle/bottom, left/center/right)

Preserve all Japanese text exactly. Note which elements connect to edges of this tile (they connect to adjacent tiles).

Output in structured markdown format."""

        messages = [{
            "role": "user",
            "content": [make_image_block(str(tile_path)), {"text": prompt}]
        }]
        
        resp = call_vlm(messages)
        text = get_text(resp)
        elapsed = time.time() - t0
        print(f"OK ({elapsed:.1f}s, {len(text)} chars)")
        
        tile_results.append({
            "tile": tile_path.name,
            "row": row,
            "col": col,
            "content": text
        })
        time.sleep(2)  # Rate limiting
    
    # Synthesis step
    print(f"  Synthesizing {len(tile_results)} tiles...", end=" ", flush=True)
    t0 = time.time()
    
    tiles_text = "\n\n".join([
        f"### Tile (row={t['row']}, col={t['col']}) - {t['tile']}:\n{t['content']}"
        for t in tile_results
    ])
    
    if sheet_idx == 1:
        synth_prompt = f"""You just analyzed {len(tile_results)} tiles from the sheet "{sheet_name}" of workbook "{WORKBOOK_NAME}".

The tiles form a 2×3 grid (2 rows, 3 columns) covering the full sheet.

Here are all tile analyses:

{tiles_text}

Now create a UNIFIED structured markdown document that:
1. Merges overlapping content from adjacent tiles
2. Reconstructs complete tables that span multiple tiles
3. Provides a coherent overview of the sheet's content
4. Identifies the document purpose, project scope, and key metadata

Format:
## Sheet Meta
- Sheet name: {sheet_name}
- Workbook: {WORKBOOK_NAME}
- Sheet type: overview/summary

## Content Summary
(Overall purpose and key information)

## Extracted Tables
(All tables merged and complete)

## Key Findings
(Important metadata, project scope, systems involved)

## Cross-References
(References to other sheets, documents, or systems)
"""
    else:
        synth_prompt = f"""You just analyzed {len(tile_results)} tiles from the sheet "{sheet_name}" of workbook "{WORKBOOK_NAME}".

The tiles form a 2×3 grid (2 rows, 3 columns) covering the full sheet.

Here are all tile analyses:

{tiles_text}

Now create a UNIFIED structured markdown document that:
1. Reconstructs the complete flowchart by connecting nodes across tile boundaries
2. Identifies the full process flow from start to end
3. Lists all decision points and their branches
4. Identifies all process steps in sequence
5. Notes any parallel paths or loops
6. Generates a valid Mermaid flowchart diagram

Format:
## Sheet Meta
- Sheet name: {sheet_name}
- Workbook: {WORKBOOK_NAME}
- Sheet type: flowchart/process diagram

## Content Summary
(What process/workflow does this flowchart represent?)

## Flowchart Nodes
(Complete list of all nodes with their types and labels)

## Process Flow
(Step-by-step description of the complete flow)

## Decision Points
(All decision points with their conditions and outcomes)

## Mermaid Diagram
```mermaid
flowchart TD
    ...
```

## Key Findings
(Important business logic, conditions, and special cases)

## Uncertain Points
(Any connections or labels that are unclear, cut off, or ambiguous)
"""

    messages = [{
        "role": "user",
        "content": [{"text": synth_prompt}]
    }]
    
    resp = call_vlm(messages, max_tokens=16000)
    synthesis = get_text(resp)
    elapsed = time.time() - t0
    print(f"OK ({elapsed:.1f}s, {len(synthesis)} chars)")
    
    # Save outputs
    output_path = f"{PARSED_DIR}/sheet_{sheet_idx:02d}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(synthesis)
    
    # Save tile responses for audit
    tiles_path = f"{PARSED_DIR}/sheet_{sheet_idx:02d}_tiles.json"
    with open(tiles_path, "w", encoding="utf-8") as f:
        json.dump(tile_results, f, ensure_ascii=False, indent=2)
    
    print(f"  Saved: {output_path} ({len(synthesis)} chars)")
    return synthesis


def main():
    global total_in, total_out
    start = time.time()
    
    print(f"VLM Parsing: {WORKBOOK_NAME}")
    print(f"Model: {MODEL_ID}")
    print(f"Sheets: {len(SHEET_NAMES)}")
    print(f"Output: {PARSED_DIR}")
    
    for i in range(1, len(SHEET_NAMES) + 1):
        parse_sheet_overview(i)
    
    elapsed = time.time() - start
    
    # Save summary
    summary = {
        "workbook": WORKBOOK_NAME,
        "s3_path": S3_EXCEL_PATH,
        "timestamp": datetime.now().isoformat(),
        "model": MODEL_ID,
        "sheets_parsed": len(SHEET_NAMES),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "elapsed_seconds": round(elapsed, 1)
    }
    with open(f"{PARSED_DIR}/run_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"COMPLETE")
    print(f"  Sheets: {len(SHEET_NAMES)}")
    print(f"  Tokens: {total_in:,} in / {total_out:,} out")
    print(f"  Time: {elapsed:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
