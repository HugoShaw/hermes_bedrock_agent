#!/usr/bin/env python3
"""Call Claude VLM via Bedrock to analyze key Excel sheet images."""

import json, os, sys, base64, time
import boto3
from botocore.config import Config

def load_env():
    """Load .env file."""
    env_path = "/home/ubuntu/projects/hermes_bedrock_agent/.env"
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

load_env()

run_id = open("/tmp/current_run_id.txt").read().strip()
output_dir = open("/tmp/current_output_dir.txt").read().strip()

# Bedrock client
config = Config(
    region_name="ap-northeast-1",
    read_timeout=600,
    connect_timeout=30,
    retries={'max_attempts': 3}
)
client = boto3.client('bedrock-runtime', config=config)
MODEL_ID = os.environ.get("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")

def call_claude_vlm(prompt, images=None, max_tokens=8000):
    """Call Claude via Bedrock converse API with optional images."""
    content = []
    
    if images:
        for img_path in images:
            with open(img_path, "rb") as f:
                img_data = f.read()
            
            # Determine format
            if img_path.endswith('.png'):
                media_type = "image/png"
            elif img_path.endswith('.jpg') or img_path.endswith('.jpeg'):
                media_type = "image/jpeg"
            else:
                media_type = "image/png"
            
            content.append({
                "image": {
                    "format": media_type.split("/")[1],
                    "source": {"bytes": img_data}
                }
            })
    
    content.append({"text": prompt})
    
    response = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1}
    )
    
    result_text = ""
    for block in response["output"]["message"]["content"]:
        if "text" in block:
            result_text += block["text"]
    
    return result_text


def analyze_flowchart_sheet():
    """Analyze the flowchart sheet using VLM."""
    print("=== Analyzing Flowchart Sheet ===")
    
    # Load drawing extraction data
    drawings_path = os.path.join(output_dir, "drawings/flowchart/フローチャート.drawings.json")
    with open(drawings_path) as f:
        drawings = json.load(f)
    
    # Prepare summary of shapes for context
    shape_summary = "Extracted shapes from Excel XML:\n"
    for s in drawings["shapes"][:40]:
        shape_summary += f"- ID:{s['shape_id']} type={s['shape_type']} role={s['possible_role']} text=\"{s['text'][:60]}\" row_range={s['from_row']}-{s['to_row']}\n"
    
    connector_summary = "\nExtracted connectors:\n"
    for c in drawings["connectors"][:40]:
        connector_summary += f"- ID:{c['connector_id']} from_shape={c['from_shape_id']} to_shape={c['to_shape_id']} label=\"{c['label']}\" conf={c['direction_confidence']}\n"
    
    # Use first few flowchart pages
    img_dir = os.path.join(output_dir, "images/flowchart")
    # Page 1 is 概要, pages 2-60 are the flowchart (it's very tall)
    # Let's use pages 2, 3, 4 for a good overview
    images = []
    for i in [1, 2, 3, 4, 5]:
        p = os.path.join(img_dir, f"page-{i:02d}.png")
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            images.append(p)
    
    prompt = f"""You are analyzing an enterprise Excel workbook: M社様_DSSスクリプト改修概要_フローチャート.xlsx

This workbook contains a flowchart describing a DataSpider (DSS) script modification for M社 (Murata).

I've provided:
1. Rendered page images from the Excel PDF
2. Extracted shape and connector information from the Excel XML

{shape_summary}
{connector_summary}

Please analyze and produce:

1. **Sheet Purpose**: What business process does this flowchart describe?
2. **Business Process Summary**: Describe the overall data flow
3. **Key Process Nodes**: List the major process steps with their roles
4. **Decision Points**: What branching logic exists?
5. **API Interactions**: Which APIs are called and when?
6. **Error Handling**: How are errors handled?
7. **Systems Involved**: What systems participate?
8. **Data Objects**: What data files/formats are processed?
9. **Mermaid Flowchart**: Generate a Mermaid diagram representing the main flow
10. **GraphRAG Entities**: List entities suitable for a knowledge graph
11. **GraphRAG Relationships**: List relationships between entities
12. **Uncertain Points**: What is ambiguous or requires human review?

Output as structured JSON with these sections.
Preserve Japanese names exactly.
If connector direction is uncertain, mark it."""

    print(f"  Calling Claude VLM with {len(images)} images...")
    start = time.time()
    result = call_claude_vlm(prompt, images=images)
    elapsed = time.time() - start
    print(f"  Response received in {elapsed:.1f}s ({len(result)} chars)")
    
    # Save outputs
    report_dir = os.path.join(output_dir, "claude_sheet_reports/flowchart")
    os.makedirs(report_dir, exist_ok=True)
    
    with open(os.path.join(report_dir, "フローチャート.md"), "w") as f:
        f.write(f"# Claude VLM Analysis: フローチャート\n\n")
        f.write(f"Model: {MODEL_ID}\n")
        f.write(f"Images analyzed: {len(images)}\n")
        f.write(f"Response time: {elapsed:.1f}s\n\n")
        f.write(result)
    
    # Try to parse as JSON for structured output
    try:
        # Try to extract JSON from response
        json_match = result
        if "```json" in result:
            json_match = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_match = result.split("```")[1].split("```")[0]
        parsed = json.loads(json_match)
        with open(os.path.join(report_dir, "フローチャート.json"), "w") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, IndexError):
        # Save raw as JSON wrapper
        with open(os.path.join(report_dir, "フローチャート.json"), "w") as f:
            json.dump({"raw_response": result}, f, indent=2, ensure_ascii=False)
    
    return result


def analyze_mapping_overview():
    """Analyze the mapping workbook overview using VLM."""
    print("\n=== Analyzing Mapping Workbook Overview ===")
    
    # Use first few mapping pages (API flow chart page, DataSpider spec)
    img_dir = os.path.join(output_dir, "images/mapping")
    images = []
    for i in [1, 2, 3]:
        p = os.path.join(img_dir, f"page-{i:02d}.png")
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            images.append(p)
    
    # Load cell data for context
    cell_dir = os.path.join(output_dir, "cell_json/mapping")
    
    # Load DataSpider spec
    ds_path = os.path.join(cell_dir, "DataSpider開発仕様.cells.json")
    ds_cells = []
    if os.path.exists(ds_path):
        with open(ds_path) as f:
            ds_data = json.load(f)
            ds_cells = ds_data.get("cells", [])
    
    ds_summary = "DataSpider Development Spec cells (first 50):\n"
    for c in ds_cells[:50]:
        ds_summary += f"  {c['coordinate']}: {str(c['value'])[:60]}\n"
    
    # Load API call order
    api_path = os.path.join(cell_dir, "API呼出順序.cells.json")
    api_cells = []
    if os.path.exists(api_path):
        with open(api_path) as f:
            api_data = json.load(f)
            api_cells = api_data.get("cells", [])
    
    api_summary = "\nAPI Call Order cells (first 30):\n"
    for c in api_cells[:30]:
        api_summary += f"  {c['coordinate']}: {str(c['value'])[:60]}\n"
    
    prompt = f"""You are analyzing an enterprise IF mapping workbook: MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx

This workbook defines the interface mapping for 発注情報 (Purchase Order Information) including registration, modification, and cancellation flows between SAP and Andpad systems via DataSpider.

Context data:
{ds_summary}
{api_summary}

Please analyze and produce:

1. **Workbook Purpose**: What is the business purpose?
2. **Interface Direction**: What systems are connected and in what direction?
3. **Processing Overview**: How does DataSpider process the data?
4. **API Call Sequence**: What APIs are called and in what order?
5. **Data Flow**: Describe the complete data flow from SAP to Andpad
6. **Processing Units**: What are the main processing steps?
7. **Error Handling**: How are errors handled?
8. **Key Business Rules**: What business rules govern the transformation?
9. **Systems Involved**: List all systems
10. **GraphRAG Entities**: List entities for knowledge graph
11. **GraphRAG Relationships**: List relationships
12. **Uncertain Points**: What needs human clarification?

Output as structured JSON. Preserve Japanese names exactly."""

    print(f"  Calling Claude VLM with {len(images)} images...")
    start = time.time()
    result = call_claude_vlm(prompt, images=images)
    elapsed = time.time() - start
    print(f"  Response received in {elapsed:.1f}s ({len(result)} chars)")
    
    report_dir = os.path.join(output_dir, "claude_sheet_reports/mapping")
    os.makedirs(report_dir, exist_ok=True)
    
    with open(os.path.join(report_dir, "overview.md"), "w") as f:
        f.write(f"# Claude VLM Analysis: Mapping Workbook Overview\n\n")
        f.write(f"Model: {MODEL_ID}\n")
        f.write(f"Response time: {elapsed:.1f}s\n\n")
        f.write(result)
    
    try:
        json_match = result
        if "```json" in result:
            json_match = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_match = result.split("```")[1].split("```")[0]
        parsed = json.loads(json_match)
        with open(os.path.join(report_dir, "overview.json"), "w") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, IndexError):
        with open(os.path.join(report_dir, "overview.json"), "w") as f:
            json.dump({"raw_response": result}, f, indent=2, ensure_ascii=False)
    
    return result


def analyze_key_mapping_sheet():
    """Analyze the SAP→中間F mapping sheet with VLM."""
    print("\n=== Analyzing SAP→中間F Mapping Sheet ===")
    
    # Use relevant mapping pages 
    img_dir = os.path.join(output_dir, "images/mapping")
    # The SAP→中間F sheet is typically pages 4-5 in the PDF
    images = []
    for i in [4, 5, 6]:
        p = os.path.join(img_dir, f"page-{i:02d}.png")
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            images.append(p)
    
    # Load extracted mapping data
    map_path = os.path.join(output_dir, "mappings/mapping/マッピングシート（SAP→中間F）.mapping.jsonl")
    mapping_records = []
    if os.path.exists(map_path):
        with open(map_path) as f:
            for line in f:
                mapping_records.append(json.loads(line))
    
    map_summary = f"Extracted {len(mapping_records)} mapping records. Key examples:\n"
    for rec in mapping_records[:10]:
        src = ", ".join([f"No.{s['source_no']}({s['source_field_name'][:10]})" for s in rec["source_fields"]]) or "none"
        map_summary += f"  Target {rec['target_field_no']}.{rec['target_field_name'][:15]} ← {src} [{rec['mapping_type']}]\n"
    
    prompt = f"""You are analyzing the mapping sheet マッピングシート（SAP→中間F）from the IF mapping workbook.

This sheet maps SAP EDI source fields to an intermediate format (中間フォーマット).

Extracted data:
{map_summary}

The sheet has:
- Left side (columns A-AO): SAP source fields (48 fields)
- Right side (columns BK-CQ): Target intermediate format fields (49 fields)
- Mapping column (DP): マッピング元 - references source field numbers
- Edit rules (DY): 編集内容 - transformation logic
- DataSpider rules (EN): 編集内容（DataSpider用）- implementation details

Please provide:
1. **Sheet Purpose**: Interface mapping from SAP to intermediate format
2. **Key Mappings**: Identify the most important/complex mappings
3. **Transformation Patterns**: What types of transformations are used?
4. **Business Rules**: What business logic governs the mapping?
5. **Complex Fields**: Which fields have complex conditional logic?
6. **Validation Rules**: Any validation or quality rules?
7. **Uncertain Mappings**: Which mappings need human verification?

Output as structured JSON."""

    print(f"  Calling Claude VLM with {len(images)} images...")
    start = time.time()
    result = call_claude_vlm(prompt, images=images)
    elapsed = time.time() - start
    print(f"  Response received in {elapsed:.1f}s ({len(result)} chars)")
    
    report_dir = os.path.join(output_dir, "claude_sheet_reports/mapping")
    os.makedirs(report_dir, exist_ok=True)
    
    with open(os.path.join(report_dir, "マッピングシート（SAP→中間F）.md"), "w") as f:
        f.write(f"# Claude VLM Analysis: マッピングシート（SAP→中間F）\n\n")
        f.write(f"Model: {MODEL_ID}\n")
        f.write(f"Response time: {elapsed:.1f}s\n\n")
        f.write(result)
    
    try:
        json_match = result
        if "```json" in result:
            json_match = result.split("```json")[1].split("```")[0]
        parsed = json.loads(json_match)
        with open(os.path.join(report_dir, "マッピングシート（SAP→中間F）.json"), "w") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, IndexError):
        with open(os.path.join(report_dir, "マッピングシート（SAP→中間F）.json"), "w") as f:
            json.dump({"raw_response": result}, f, indent=2, ensure_ascii=False)
    
    return result


if __name__ == "__main__":
    print(f"Using model: {MODEL_ID}")
    print(f"Run ID: {run_id}")
    print(f"Output: {output_dir}")
    print()
    
    r1 = analyze_flowchart_sheet()
    time.sleep(3)
    
    r2 = analyze_mapping_overview()
    time.sleep(3)
    
    r3 = analyze_key_mapping_sheet()
    
    print("\n=== All Claude VLM analyses complete ===")
