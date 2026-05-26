#!/usr/bin/env python3
"""
VLM-based Excel Sheet Parser using Claude Sonnet via Bedrock.

Processes each sheet's PDF-rendered images through Claude Sonnet multimodal API
to extract text, tables, flowcharts, mapping relationships, and business logic.

Strategy:
- Small sheets (≤4000px both dims): single overview image
- Tiled sheets: process each tile individually, then synthesize
- Very wide mapping sheets: special tile-by-tile parsing with column tracking
"""
import os
import sys
import json
import time
import base64
import traceback
from io import BytesIO
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config
from PIL import Image
from dotenv import load_dotenv

# Load env
load_dotenv(os.path.expanduser("~/projects/hermes_bedrock_agent/.env"))

Image.MAX_IMAGE_PIXELS = 500_000_000

# Config
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
MODEL_ID = os.getenv("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
OUTPUT_BASE = os.path.expanduser("~/projects/hermes_bedrock_agent/outputs/reparse_wb2")
IMG_DIR = f"{OUTPUT_BASE}/images_v2"
TILE_DIR = f"{OUTPUT_BASE}/tiles_v2"
PARSED_DIR = f"{OUTPUT_BASE}/vlm_parsed"
os.makedirs(PARSED_DIR, exist_ok=True)

# Bedrock client
client = boto3.client(
    'bedrock-runtime',
    config=Config(
        region_name=AWS_REGION,
        read_timeout=600,
        retries={'max_attempts': 3, 'mode': 'adaptive'}
    )
)

# Sheet metadata
SHEET_NAMES = {
    'sheet_01': '変更履歴',
    'sheet_02': 'API呼出順序',
    'sheet_03': 'DataSpider開発仕様',
    'sheet_04': 'マッピングシート（SAP→中間F）',
    'sheet_05': 'マッピングシート（中間F→Andpad）【登録】',
    'sheet_06': 'マッピングシート（発注情報登録）',
    'sheet_07': 'マッピングシート（中間F→納品中間F）【変更】',
    'sheet_08': 'マッピングシート（納品中間F→Andpad）【変更】',
    'sheet_09': 'マッピングシート（納品データ編集）',
    'sheet_10': 'マッピングシート（中間F→発注中間F）【変更】',
    'sheet_11': 'マッピングシート（発注中間F→Andpad）【変更】',
    'sheet_12': 'マッピングシート（請負済のデータ編集）',
    'sheet_13': 'マッピングシート（中間F→Andpad）【納品キャンセル】',
    'sheet_14': 'マッピングシート（納品のキャンセル）',
    'sheet_15': 'マッピングシート（中間F→Andpad）【請負済キャンセル】',
    'sheet_16': 'マッピングシート（請負済のキャンセル）',
    'sheet_17': 'データ取得条件（納品一覧取得）',
    'sheet_18': 'マッピングシート（納品一覧取得）',
    'sheet_19': 'データ取得条件（納品明細）',
    'sheet_20': 'マッピングシート（納品明細）',
    'sheet_21': 'データ取得条件（発注明細）',
    'sheet_22': 'マッピングシート（発注明細）',
    'sheet_23': 'データ取得条件（発注一覧取得）',
    'sheet_24': 'マッピングシート（発注一覧取得）',
    'sheet_25': 'マッピングシート（発注ステータス変更）',
    'sheet_26': 'マッピングシート（発注前のデータ削除）',
    'sheet_27': '補足事項(DataSpider)',
}


def image_to_bytes(img_path, max_dim=7900, max_bytes=4_500_000):
    """Load image, resize if needed, return PNG bytes."""
    img = Image.open(img_path)
    w, h = img.size
    
    # Resize if too large for API
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    
    # Convert to PNG bytes
    buf = BytesIO()
    img.save(buf, format='PNG', optimize=True)
    png_bytes = buf.getvalue()
    
    # If still too large, reduce quality via JPEG
    if len(png_bytes) > max_bytes:
        buf = BytesIO()
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.save(buf, format='JPEG', quality=85)
        png_bytes = buf.getvalue()
        media_type = "image/jpeg"
    else:
        media_type = "image/png"
    
    img.close()
    return png_bytes, media_type


def call_vlm(images, prompt, max_tokens=12000):
    """Call Claude Sonnet VLM with one or more images."""
    content = []
    
    for img_bytes, media_type in images:
        content.append({
            "image": {
                "format": media_type.split("/")[1],
                "source": {"bytes": img_bytes}
            }
        })
    
    content.append({"text": prompt})
    
    response = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1}
    )
    
    result_text = ""
    for block in response['output']['message']['content']:
        if 'text' in block:
            result_text += block['text']
    
    usage = response.get('usage', {})
    return result_text, usage


def get_sheet_type(sheet_key):
    """Classify sheet type for prompt selection."""
    name = SHEET_NAMES.get(sheet_key, '')
    if '変更履歴' in name:
        return 'change_history'
    elif 'API呼出順序' in name:
        return 'flowchart'
    elif 'DataSpider開発仕様' in name:
        return 'dev_spec'
    elif '補足事項' in name:
        return 'supplementary'
    elif 'データ取得条件' in name:
        return 'data_condition'
    elif 'マッピングシート' in name:
        return 'mapping'
    return 'unknown'


def get_prompt_for_type(sheet_type, sheet_name, tile_context=""):
    """Get appropriate VLM prompt based on sheet type."""
    
    base_context = f"""You are analyzing a sheet from a Japanese enterprise IF (Interface) Mapping Definition Document (IFマッピング定義書).
This workbook defines the data mapping between SAP S4/HANA and ANDPAD (construction project management) via DataSpider middleware.
The overall interface is: 205_発注情報(登録・変更・取消) — Purchase Order Information (Registration/Change/Cancellation).

Current sheet: {sheet_name}
{tile_context}
"""
    
    if sheet_type == 'change_history':
        return base_context + """
Please extract the change history table. For each row, identify:
- No (revision number)
- 変更日時 (change date)
- 変更者 (changed by)
- 変更内容 (change description)

Output as a structured markdown table. Also note the overall document revision status."""

    elif sheet_type == 'flowchart':
        return base_context + """
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

    elif sheet_type == 'dev_spec':
        return base_context + """
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

    elif sheet_type == 'data_condition':
        return base_context + """
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

    elif sheet_type == 'mapping':
        return base_context + """
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

    elif sheet_type == 'supplementary':
        return base_context + """
This is a supplementary/notes sheet. Extract any text content, specifications, or additional rules."""

    return base_context + """
Please analyze this sheet image and extract all visible content:
- Tables with all rows and columns
- Text content
- Any diagrams or visual elements
- Notes and annotations
Output in structured markdown."""


def get_tile_synthesis_prompt(sheet_name, sheet_type, n_tiles, tile_results):
    """Prompt to synthesize multiple tile results into coherent sheet analysis."""
    
    tiles_text = "\n\n---\n\n".join([
        f"### Tile {i+1} ({t['position']}):\n{t['content']}"
        for i, t in enumerate(tile_results)
    ])
    
    return f"""You previously analyzed {n_tiles} tiles from the sheet "{sheet_name}" (type: {sheet_type}).
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


def parse_sheet_single(sheet_key, img_path, sheet_type, sheet_name):
    """Parse a sheet using single overview image."""
    prompt = get_prompt_for_type(sheet_type, sheet_name)
    img_bytes, media_type = image_to_bytes(img_path)
    
    result, usage = call_vlm([(img_bytes, media_type)], prompt)
    return result, usage


def parse_sheet_tiled(sheet_key, sheet_type, sheet_name):
    """Parse a sheet using multiple tiles, then synthesize."""
    tile_dir = os.path.join(TILE_DIR, sheet_key)
    if not os.path.exists(tile_dir):
        # Fall back to overview
        overview = os.path.join(IMG_DIR, f"{sheet_key}.png")
        return parse_sheet_single(sheet_key, overview, sheet_type, sheet_name)
    
    # Get sorted tiles
    tiles = sorted([f for f in os.listdir(tile_dir) if f.endswith('.png')])
    
    tile_results = []
    total_usage = {'inputTokens': 0, 'outputTokens': 0}
    
    for i, tile_name in enumerate(tiles):
        tile_path = os.path.join(tile_dir, tile_name)
        # Parse position from filename: tile_r00_c00.png
        parts = tile_name.replace('.png', '').split('_')
        row = int(parts[1][1:])
        col = int(parts[2][1:])
        position = f"row {row}, col {col}"
        
        tile_context = f"\nThis is tile {i+1}/{len(tiles)} (position: {position}) of the full sheet."
        if sheet_type == 'mapping':
            if row == 0 and col == 0:
                tile_context += "\nThis tile contains the TOP-LEFT corner with header metadata and the first columns."
            elif row == 0:
                tile_context += f"\nThis tile contains the TOP area, columns section {col+1}. Look for mapping/transformation columns."
            elif col == 0:
                tile_context += "\nThis tile contains the LEFT area with source field definitions (lower rows)."
            else:
                tile_context += f"\nThis tile contains the MIDDLE/RIGHT area (rows section {row+1}, columns section {col+1})."
        elif sheet_type == 'flowchart':
            tile_context += f"\nThis is vertical section {row+1} of the flowchart."
        
        prompt = get_prompt_for_type(sheet_type, sheet_name, tile_context)
        img_bytes, media_type = image_to_bytes(tile_path, max_dim=4000)
        
        try:
            result, usage = call_vlm([(img_bytes, media_type)], prompt, max_tokens=8000)
            total_usage['inputTokens'] += usage.get('inputTokens', 0)
            total_usage['outputTokens'] += usage.get('outputTokens', 0)
            
            tile_results.append({
                'tile': tile_name,
                'position': position,
                'content': result
            })
            print(f"      Tile {i+1}/{len(tiles)} ({position}): {len(result)} chars", flush=True)
            
            # Rate limiting
            time.sleep(2)
            
        except Exception as e:
            print(f"      Tile {i+1}/{len(tiles)} ERROR: {e}", flush=True)
            tile_results.append({
                'tile': tile_name,
                'position': position,
                'content': f"[ERROR: {str(e)}]"
            })
            time.sleep(5)
    
    # Synthesize tile results
    if len(tile_results) > 1:
        print(f"      Synthesizing {len(tile_results)} tiles...", flush=True)
        synth_prompt = get_tile_synthesis_prompt(sheet_name, sheet_type, len(tiles), tile_results)
        
        try:
            # Text-only synthesis (no image)
            response = client.converse(
                modelId=MODEL_ID,
                messages=[{"role": "user", "content": [{"text": synth_prompt}]}],
                inferenceConfig={"maxTokens": 12000, "temperature": 0.1}
            )
            synth_text = ""
            for block in response['output']['message']['content']:
                if 'text' in block:
                    synth_text += block['text']
            synth_usage = response.get('usage', {})
            total_usage['inputTokens'] += synth_usage.get('inputTokens', 0)
            total_usage['outputTokens'] += synth_usage.get('outputTokens', 0)
        except Exception as e:
            print(f"      Synthesis ERROR: {e}", flush=True)
            synth_text = "\n\n---\n\n".join([t['content'] for t in tile_results])
    else:
        synth_text = tile_results[0]['content'] if tile_results else "[No content]"
    
    # Save tile-level results too
    tile_output_path = os.path.join(PARSED_DIR, f"{sheet_key}_tiles.json")
    with open(tile_output_path, 'w', encoding='utf-8') as f:
        json.dump(tile_results, f, ensure_ascii=False, indent=2)
    
    return synth_text, total_usage


def process_sheet(sheet_key):
    """Process a single sheet end-to-end."""
    sheet_name = SHEET_NAMES.get(sheet_key, sheet_key)
    sheet_type = get_sheet_type(sheet_key)
    overview_path = os.path.join(IMG_DIR, f"{sheet_key}.png")
    has_tiles = os.path.exists(os.path.join(TILE_DIR, sheet_key))
    
    print(f"  [{sheet_key}] {sheet_name} (type={sheet_type}, tiles={has_tiles})", flush=True)
    
    # Decide strategy
    if sheet_key == 'sheet_27':
        # Empty sheet
        result = f"# Sheet: {sheet_name}\n\n## 1. Sheet Overview\nThis sheet is empty (補足事項 DataSpider). No content to parse."
        usage = {'inputTokens': 0, 'outputTokens': 0}
    elif has_tiles and sheet_type in ('mapping', 'flowchart', 'dev_spec'):
        # Use tiles for detailed extraction
        result, usage = parse_sheet_tiled(sheet_key, sheet_type, sheet_name)
    else:
        # Use overview image
        result, usage = parse_sheet_single(sheet_key, overview_path, sheet_type, sheet_name)
    
    # Save results
    output_path = os.path.join(PARSED_DIR, f"{sheet_key}.md")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)
    
    # Save metadata
    meta_path = os.path.join(PARSED_DIR, f"{sheet_key}_meta.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({
            'sheet_key': sheet_key,
            'sheet_name': sheet_name,
            'sheet_type': sheet_type,
            'has_tiles': has_tiles,
            'usage': usage,
            'output_length': len(result),
            'timestamp': datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    return {
        'key': sheet_key,
        'name': sheet_name,
        'type': sheet_type,
        'output_path': output_path,
        'chars': len(result),
        'usage': usage,
        'status': 'ok'
    }


def main():
    start_time = time.time()
    print(f"VLM Sheet Parser - {datetime.now().isoformat()}")
    print(f"Model: {MODEL_ID}")
    print(f"Sheets: {len(SHEET_NAMES)}")
    print(f"Output: {PARSED_DIR}")
    print("=" * 60)
    
    # Check for resume (skip already-parsed sheets)
    skip_sheets = set()
    for f in os.listdir(PARSED_DIR):
        if f.endswith('.md') and f.startswith('sheet_'):
            key = f.replace('.md', '')
            # Only skip if file has substantial content
            path = os.path.join(PARSED_DIR, f)
            if os.path.getsize(path) > 200:
                skip_sheets.add(key)
    
    if skip_sheets:
        print(f"Resuming: skipping {len(skip_sheets)} already-parsed sheets")
        print(f"  Skipping: {sorted(skip_sheets)}")
    
    results = []
    for sheet_key in sorted(SHEET_NAMES.keys()):
        if sheet_key in skip_sheets:
            results.append({
                'key': sheet_key,
                'name': SHEET_NAMES[sheet_key],
                'status': 'skipped (already parsed)'
            })
            continue
        
        try:
            result = process_sheet(sheet_key)
            results.append(result)
            print(f"    -> {result['chars']} chars, "
                  f"tokens: {result['usage'].get('inputTokens', 0)}in/{result['usage'].get('outputTokens', 0)}out",
                  flush=True)
        except Exception as e:
            print(f"    -> ERROR: {e}", flush=True)
            traceback.print_exc()
            results.append({
                'key': sheet_key,
                'name': SHEET_NAMES[sheet_key],
                'status': f'error: {str(e)}'
            })
        
        # Rate limiting between sheets
        time.sleep(3)
    
    # Save run summary
    elapsed = time.time() - start_time
    summary = {
        'timestamp': datetime.now().isoformat(),
        'model': MODEL_ID,
        'total_sheets': len(SHEET_NAMES),
        'parsed': sum(1 for r in results if r.get('status') == 'ok'),
        'skipped': sum(1 for r in results if 'skipped' in str(r.get('status', ''))),
        'errors': sum(1 for r in results if 'error' in str(r.get('status', ''))),
        'total_chars': sum(r.get('chars', 0) for r in results),
        'total_input_tokens': sum(r.get('usage', {}).get('inputTokens', 0) for r in results),
        'total_output_tokens': sum(r.get('usage', {}).get('outputTokens', 0) for r in results),
        'elapsed_seconds': int(elapsed),
        'results': results
    }
    
    summary_path = os.path.join(PARSED_DIR, "run_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"DONE in {int(elapsed)}s ({int(elapsed/60)}m)")
    print(f"  Parsed: {summary['parsed']}/{summary['total_sheets']}")
    print(f"  Total output: {summary['total_chars']} chars")
    print(f"  Tokens: {summary['total_input_tokens']} in / {summary['total_output_tokens']} out")
    print(f"  Summary: {summary_path}")


if __name__ == '__main__':
    main()
