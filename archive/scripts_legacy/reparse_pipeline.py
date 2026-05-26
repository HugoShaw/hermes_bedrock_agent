#!/usr/bin/env python3
"""
Complete Re-parse Pipeline: Extract structured data + VLM analysis for all 27 sheets.
Combines:
1. Structured Excel extraction (cell values, merged ranges)
2. VLM-based visual analysis using rendered PNGs
3. Markdown + JSON output generation
"""
import os
import sys
import json
import time
import csv
import traceback
from pathlib import Path
from datetime import datetime

import openpyxl
import boto3
from botocore.config import Config
from PIL import Image

# Configuration
XLSX_PATH = "/tmp/s3_downloads/サンプル20260519/02_詳細設計/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx"
OUTPUT_BASE = os.path.expanduser("~/projects/hermes_bedrock_agent/outputs/reparse_wb2")
IMG_DIR = f"{OUTPUT_BASE}/images"

# Bedrock config
REGION = "ap-northeast-1"
MODEL_ID = "jp.anthropic.claude-sonnet-4-6"
bedrock_config = Config(
    region_name=REGION,
    read_timeout=600,
    retries={"max_attempts": 3, "mode": "adaptive"}
)
bedrock_client = boto3.client("bedrock-runtime", config=bedrock_config)

# Load manifest
with open(f"{OUTPUT_BASE}/manifest.json") as f:
    manifest = json.load(f)
sheets = manifest['sheets']

# Logging
log_path = f"{OUTPUT_BASE}/logs/run.log"
os.makedirs(f"{OUTPUT_BASE}/logs", exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(log_path, 'a') as f:
        f.write(line + "\n")


def extract_structured_data(wb, sheet_name, max_row, max_col):
    """Extract cell values, merged ranges, and structural data."""
    ws = wb[sheet_name]
    
    data = {
        "sheet_name": sheet_name,
        "dimensions": f"{max_row}x{max_col}",
        "merged_ranges": [str(r) for r in ws.merged_cells.ranges],
        "header_rows": [],
        "data_rows": [],
        "non_empty_cells_count": 0,
    }
    
    # Extract all cell values (up to reasonable limits)
    rows_to_extract = min(max_row, 200)
    cols_to_extract = min(max_col, 200)
    
    for row_idx in range(1, rows_to_extract + 1):
        row_data = []
        for col_idx in range(1, cols_to_extract + 1):
            cell = ws.cell(row_idx, col_idx)
            val = cell.value
            if val is not None:
                data["non_empty_cells_count"] += 1
                cell_info = {
                    "row": row_idx,
                    "col": col_idx,
                    "value": str(val)[:500],
                    "bold": cell.font.bold if cell.font else False,
                }
                row_data.append(cell_info)
        if row_data:
            if row_idx <= 5:
                data["header_rows"].append(row_data)
            else:
                data["data_rows"].append(row_data)
    
    return data


def image_to_bytes(img_path, max_dim=7900):
    """Load image and return bytes for Bedrock, resizing if needed."""
    img = Image.open(img_path)
    w, h = img.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    
    import io
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    img.close()
    return buf.getvalue()


def call_vlm(image_bytes, prompt, sheet_name):
    """Call Bedrock Claude Sonnet with image + prompt."""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "image": {
                        "format": "png",
                        "source": {"bytes": image_bytes}
                    }
                },
                {
                    "text": prompt
                }
            ]
        }
    ]
    
    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=messages,
        inferenceConfig={"maxTokens": 12000, "temperature": 0.1}
    )
    
    output_text = ""
    for block in response["output"]["message"]["content"]:
        if "text" in block:
            output_text += block["text"]
    
    return output_text


def build_mapping_prompt(sheet_name, sheet_type, structured_data):
    """Build a targeted VLM prompt based on sheet type."""
    
    # Include some structural context
    merged_info = f"Merged cell ranges: {len(structured_data['merged_ranges'])}"
    header_sample = ""
    if structured_data['header_rows']:
        header_vals = [c['value'] for c in structured_data['header_rows'][0][:15]]
        header_sample = f"Header row sample: {header_vals}"
    
    if sheet_type == "mapping":
        return f"""Analyze this Excel mapping sheet image. Sheet name: "{sheet_name}"
{merged_info}
{header_sample}

This is a data field mapping specification from a Japanese enterprise integration project (SAP → DataSpider → ANDPAD).

Extract the following in detail:
1. Source system and format (e.g., SAP CSV, intermediate file, ANDPAD API)
2. Target system and format
3. ALL field mappings visible, for each:
   - Target field number (No.)
   - Target field name (Japanese)
   - Target data type and length
   - Whether required (必須)
   - Source field number(s) that map to it
   - Source field name(s)
   - Mapping type: direct copy, fixed value, conditional, code conversion, concatenation, or omit
   - Business rule or transformation logic (in Japanese as-is)
   - DataSpider-specific editing rules if any
   - Any evidence text or cell annotations

4. Color coding meaning (yellow, red, blue sections)
5. Any conditional logic or branching rules
6. Any notes, warnings, or special handling instructions

Output format: Provide a structured analysis. List every visible mapping row.
Preserve ALL Japanese text exactly as shown. Do not translate Japanese field names.
Mark any fields you cannot read clearly with [UNCERTAIN]."""

    elif sheet_type == "process_spec":
        return f"""Analyze this Excel process specification sheet image. Sheet name: "{sheet_name}"
{merged_info}
{header_sample}

This is a process/API specification from a Japanese enterprise integration project (SAP → DataSpider → ANDPAD).

Extract:
1. Main process flow and sequence
2. API call order and dependencies
3. Input/output files and data flows
4. Branch conditions and decision points
5. Error handling and retry logic
6. Status codes and their meanings
7. DataSpider script behavior and configuration
8. Any process diagrams or flowcharts described

Preserve ALL Japanese text exactly. Mark unclear areas with [UNCERTAIN]."""

    elif sheet_type == "data_condition":
        return f"""Analyze this Excel data condition sheet image. Sheet name: "{sheet_name}"
{merged_info}
{header_sample}

This is a data retrieval condition specification from a Japanese enterprise integration project.

Extract:
1. API name and endpoint
2. ALL request parameters:
   - Parameter name
   - Required/optional
   - Data type
   - Fixed value or dynamic
   - Description
3. Query conditions and filters
4. Pagination parameters
5. Status filters
6. Any special conditions or business rules

Preserve ALL Japanese text exactly. Mark unclear areas with [UNCERTAIN]."""

    else:  # change_log, empty, other
        return f"""Analyze this Excel sheet image. Sheet name: "{sheet_name}"
{merged_info}
{header_sample}

Describe:
1. What this sheet contains
2. Table structure and columns
3. Any data entries
4. Purpose of this sheet in the workbook

Preserve ALL Japanese text exactly."""


def build_json_prompt(sheet_name, sheet_type, vlm_response, structured_data):
    """Build prompt to generate structured JSON from VLM analysis."""
    
    if sheet_type == "mapping":
        return f"""Based on this analysis of mapping sheet "{sheet_name}", produce a structured JSON output.

Analysis:
{vlm_response[:8000]}

Structured data context:
- Merged cells: {len(structured_data['merged_ranges'])}
- Non-empty cells: {structured_data['non_empty_cells_count']}
- Dimensions: {structured_data['dimensions']}

Produce JSON with this exact structure:
{{
  "sheet_name": "{sheet_name}",
  "sheet_type": "mapping",
  "source_system": "<identified source>",
  "target_system": "<identified target>",
  "total_mappings": <count>,
  "mappings": [
    {{
      "target_no": "<number>",
      "target_field": "<Japanese field name>",
      "target_required": "<Y/N or empty>",
      "target_type": "<data type>",
      "source_refs": [
        {{"source_no": "<number>", "source_field": "<Japanese field name>"}}
      ],
      "mapping_type": "direct | fixed_value | conditional | code_conversion | concat | omit | unknown",
      "business_rule": "<rule in Japanese as-is>",
      "dataspider_rule": "<if any>",
      "evidence": "<cell text that supports this mapping>",
      "confidence": <0.0-1.0>,
      "review_note": "<any uncertainty>"
    }}
  ],
  "color_coding": {{}},
  "notes": [],
  "low_confidence_areas": []
}}

Output ONLY valid JSON. Include all mappings you can identify from the analysis."""

    elif sheet_type == "data_condition":
        return f"""Based on this analysis of data condition sheet "{sheet_name}", produce structured JSON.

Analysis:
{vlm_response[:8000]}

Produce JSON:
{{
  "sheet_name": "{sheet_name}",
  "sheet_type": "data_condition",
  "api_name": "<API name>",
  "endpoint": "<if visible>",
  "parameters": [
    {{
      "name": "<param name>",
      "required": true/false,
      "type": "<data type>",
      "fixed_value": "<if fixed>",
      "description": "<Japanese description>"
    }}
  ],
  "query_conditions": [],
  "pagination": {{}},
  "status_filters": [],
  "notes": [],
  "low_confidence_areas": []
}}

Output ONLY valid JSON."""

    else:  # process_spec, change_log, etc.
        return f"""Based on this analysis of sheet "{sheet_name}" (type: {sheet_type}), produce structured JSON.

Analysis:
{vlm_response[:8000]}

Produce JSON:
{{
  "sheet_name": "{sheet_name}",
  "sheet_type": "{sheet_type}",
  "purpose": "<sheet purpose>",
  "main_content": {{}},
  "process_flow": [],
  "api_calls": [],
  "key_items": [],
  "notes": [],
  "low_confidence_areas": []
}}

Output ONLY valid JSON."""


def process_sheet(wb, sheet_info, start_time):
    """Process a single sheet: extract data + VLM analysis."""
    idx = sheet_info['index']
    name = sheet_info['name']
    safe = sheet_info['safe']
    stype = sheet_info['type']
    max_row = sheet_info['rows']
    max_col = sheet_info['cols']
    
    elapsed = time.time() - start_time
    log(f"[{idx+1:02d}/27] Processing: {name} (type={stype}, {max_row}x{max_col}) [+{elapsed:.0f}s]")
    
    result = {
        "sheet_index": idx,
        "sheet_name": name,
        "safe_name": safe,
        "sheet_type": stype,
        "success": False,
        "error": None,
    }
    
    # Step 1: Extract structured data
    try:
        structured = extract_structured_data(wb, name, max_row, max_col)
        struct_path = f"{OUTPUT_BASE}/structured_data/{safe}.json"
        with open(struct_path, 'w', encoding='utf-8') as f:
            json.dump(structured, f, ensure_ascii=False, indent=2)
        log(f"  Structured: {structured['non_empty_cells_count']} non-empty cells, {len(structured['merged_ranges'])} merges")
    except Exception as e:
        log(f"  WARNING: Structured extraction failed: {e}")
        structured = {"merged_ranges": [], "non_empty_cells_count": 0, "dimensions": f"{max_row}x{max_col}", "header_rows": [], "data_rows": []}
    
    # Step 2: VLM analysis
    img_path = f"{IMG_DIR}/{safe}.png"
    if not os.path.exists(img_path):
        log(f"  SKIP VLM: no image for {safe}")
        result["error"] = "no_image"
        return result
    
    try:
        image_bytes = image_to_bytes(img_path)
        log(f"  Image: {len(image_bytes)//1024}KB")
    except Exception as e:
        log(f"  ERROR loading image: {e}")
        result["error"] = f"image_load: {e}"
        return result
    
    # Build prompt based on sheet type
    prompt = build_mapping_prompt(name, stype, structured)
    
    try:
        vlm_response = call_vlm(image_bytes, prompt, name)
        log(f"  VLM response: {len(vlm_response)} chars")
    except Exception as e:
        log(f"  ERROR VLM call: {e}")
        result["error"] = f"vlm: {e}"
        # Still save structured data results
        save_markdown_from_struct(safe, name, stype, structured, None)
        return result
    
    # Step 3: Generate JSON via second VLM call (text-only)
    json_prompt = build_json_prompt(name, stype, vlm_response, structured)
    
    try:
        json_response = call_vlm_text(json_prompt)
        log(f"  JSON generation: {len(json_response)} chars")
    except Exception as e:
        log(f"  WARNING: JSON generation failed: {e}")
        json_response = None
    
    # Step 4: Save outputs
    save_markdown(safe, name, stype, structured, vlm_response)
    save_json(safe, name, stype, json_response, vlm_response)
    
    result["success"] = True
    
    # Rate limiting
    time.sleep(3)
    return result


def call_vlm_text(prompt):
    """Call Bedrock Claude with text-only prompt (no image)."""
    messages = [
        {
            "role": "user",
            "content": [{"text": prompt}]
        }
    ]
    
    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=messages,
        inferenceConfig={"maxTokens": 12000, "temperature": 0.1}
    )
    
    output_text = ""
    for block in response["output"]["message"]["content"]:
        if "text" in block:
            output_text += block["text"]
    
    return output_text


def save_markdown(safe, name, stype, structured, vlm_response):
    """Save Markdown parsing result."""
    md_path = f"{OUTPUT_BASE}/parsed_md/{safe}.md"
    
    md = f"""# Sheet: {name}

## 1. Sheet Overview

- **Type**: {stype}
- **Dimensions**: {structured['dimensions']}
- **Merged Cells**: {len(structured['merged_ranges'])}
- **Non-empty Cells**: {structured['non_empty_cells_count']}

## 2. Parsing Strategy

- Sheet type classified as: **{stype}**
- LibreOffice PDF rendering → stitched PNG for VLM
- Structured extraction via openpyxl for cell values and merged ranges
- Claude Sonnet VLM multimodal analysis for visual understanding

## 3. VLM Analysis

{vlm_response if vlm_response else "(VLM analysis not available)"}

## 4. Structured Data Summary

### Merged Cell Ranges (first 20)
"""
    for mr in structured['merged_ranges'][:20]:
        md += f"- {mr}\n"
    
    if structured['header_rows']:
        md += "\n### Header Values (first row)\n"
        for cell in structured['header_rows'][0][:20]:
            md += f"- [{cell['row']},{cell['col']}]: {cell['value'][:100]}\n"
    
    md += f"""
## 5. Evidence Files

- Image: `images/{safe}.png`
- PDF: `pdf/{safe}.pdf`
- Structured data: `structured_data/{safe}.json`

## 6. Uncertain or Ambiguous Points

(See VLM analysis above for [UNCERTAIN] markers)
"""
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)


def save_markdown_from_struct(safe, name, stype, structured, vlm_response):
    """Save markdown when VLM failed."""
    save_markdown(safe, name, stype, structured, vlm_response)


def save_json(safe, name, stype, json_response, vlm_response):
    """Save JSON parsing result."""
    json_path = f"{OUTPUT_BASE}/parsed_json/{safe}.json"
    
    parsed_json = None
    if json_response:
        # Try to extract JSON from response
        try:
            # Look for JSON block
            text = json_response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                start = 1
                end = len(lines) - 1
                for i, line in enumerate(lines):
                    if line.strip().startswith("{"):
                        start = i
                        break
                text = "\n".join(lines[start:end])
            
            if "{" in text:
                # Find the JSON object
                start = text.index("{")
                # Find matching closing brace
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            text = text[start:i+1]
                            break
                parsed_json = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            parsed_json = {
                "sheet_name": name,
                "sheet_type": stype,
                "parse_error": f"JSON parse failed: {str(e)[:200]}",
                "raw_response": json_response[:5000]
            }
    
    if parsed_json is None:
        parsed_json = {
            "sheet_name": name,
            "sheet_type": stype,
            "error": "no_json_response",
            "vlm_summary": vlm_response[:3000] if vlm_response else None
        }
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(parsed_json, f, ensure_ascii=False, indent=2)


def main():
    start_time = time.time()
    log(f"=" * 60)
    log(f"Re-parse Pipeline Start: {datetime.now().isoformat()}")
    log(f"Source: {XLSX_PATH}")
    log(f"Output: {OUTPUT_BASE}")
    log(f"Sheets: {len(sheets)}")
    log(f"=" * 60)
    
    # Open workbook once
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    
    results = []
    for sheet_info in sheets:
        try:
            r = process_sheet(wb, sheet_info, start_time)
            results.append(r)
        except Exception as e:
            log(f"  FATAL ERROR on sheet {sheet_info['index']}: {e}")
            traceback.print_exc()
            results.append({
                "sheet_index": sheet_info['index'],
                "sheet_name": sheet_info['name'],
                "safe_name": sheet_info['safe'],
                "sheet_type": sheet_info['type'],
                "success": False,
                "error": str(e),
            })
    
    wb.close()
    
    # Summary
    elapsed = time.time() - start_time
    success = sum(1 for r in results if r['success'])
    failed = sum(1 for r in results if not r['success'])
    
    log(f"\n{'=' * 60}")
    log(f"Pipeline Complete: {elapsed:.0f}s")
    log(f"Success: {success}/27, Failed: {failed}/27")
    if failed > 0:
        for r in results:
            if not r['success']:
                log(f"  FAILED: {r['sheet_name']} - {r.get('error', 'unknown')}")
    log(f"{'=' * 60}")
    
    # Save results summary
    with open(f"{OUTPUT_BASE}/logs/pipeline_results.json", 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
