"""Parse plan generator using LLM/VLM.

Generates a workbook-specific parse plan by analyzing the structural atlas.
The LLM infers semantic roles from physical facts - the code never hardcodes
business-specific concepts.
"""
import json
import logging
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig

from ..config import PipelineConfig

logger = logging.getLogger(__name__)


PARSE_PLAN_SYSTEM_PROMPT = """You are an expert at analyzing enterprise Excel design documents.
You will receive structural data about an Excel workbook (cell values, positions, styles, regions).
Your job is to infer the SEMANTIC ROLES of each region and produce a parse plan.

You must identify:
1. What type of workbook this is (e.g., mapping specification, flowchart, overview, etc.)
2. What type each sheet is
3. What logical regions exist in each sheet
4. For table-like regions: which rows are headers, which contain data, what role each column plays
5. How regions relate to each other (e.g., source table maps to target table)
6. What extraction strategy to use for each region
7. What is uncertain and needs human review

Use these semantic roles for regions:
- source_table: defines source system fields
- target_table: defines target system fields
- mapping_table: maps source to target with transformation rules
- transformation_rule_table: conversion/transformation logic
- condition_table: conditions or branching logic
- note_block: notes, descriptions, metadata
- flowchart_area: visual flow/process diagram
- metadata_block: document header/version info
- unknown: cannot determine

Use these column roles:
- field_number: sequential ID or number
- field_name: name of a field/item
- data_type: data type specification
- length: field length/size
- required_flag: required/optional indicator
- source_reference: reference to source field
- target_reference: reference to target field
- transformation_rule: transformation/conversion rule
- condition: condition or logic
- note: note/remark/description
- unknown: cannot determine

Respond ONLY with valid JSON matching the parse plan schema."""


PARSE_PLAN_USER_PROMPT_TEMPLATE = """Analyze this workbook structure and generate a parse plan.

## Workbook Info
- Name: {workbook_name}
- Sheets: {sheet_names}
- Total sheets: {sheet_count}

## Sheet Details
{sheet_details}

## Detected Regions
{region_details}

## Instructions
Based on the structural data above (cell values, positions, styles, regions),
generate a complete parse plan JSON with:
1. workbook_type classification
2. Per-sheet type classification
3. Per-region semantic role assignment
4. Column role assignment for table-like regions
5. Extraction strategy for each region
6. Relationships between regions
7. Confidence scores (0.0-1.0)
8. Uncertainties list

Output ONLY valid JSON matching the parse plan schema."""


def generate_parse_plan(
    workbook_atlas: dict,
    regions_by_sheet: dict,
    config: PipelineConfig,
) -> dict:
    """Generate a parse plan for a workbook using LLM."""
    
    # Build context from atlas
    sheet_details = _format_sheet_details(workbook_atlas)
    region_details = _format_region_details(regions_by_sheet)

    prompt = PARSE_PLAN_USER_PROMPT_TEMPLATE.format(
        workbook_name=workbook_atlas["workbook_name"],
        sheet_names=", ".join(workbook_atlas["sheet_names"]),
        sheet_count=workbook_atlas["sheet_count"],
        sheet_details=sheet_details,
        region_details=region_details,
    )

    # Call Bedrock
    try:
        response_text = _call_bedrock(prompt, config)
        parse_plan = _parse_response(response_text, workbook_atlas, regions_by_sheet)
    except Exception as e:
        logger.error(f"LLM parse plan generation failed: {e}")
        # Fallback: generate a basic plan from structural signals
        parse_plan = _generate_fallback_plan(workbook_atlas, regions_by_sheet)

    # Always add metadata
    parse_plan["workbook_id"] = workbook_atlas["workbook_id"]
    parse_plan["workbook_name"] = workbook_atlas["workbook_name"]
    parse_plan["source_file"] = workbook_atlas.get("source_file", "")

    return parse_plan


def _format_sheet_details(atlas: dict) -> str:
    """Format sheet details for LLM context.
    
    For large workbooks (many sheets), limit detail per sheet to fit LLM context.
    """
    parts = []
    sheet_count = len(atlas.get("sheets", []))
    # Adaptive: fewer cells per sheet if many sheets
    max_cells_per_sheet = 50 if sheet_count <= 5 else (20 if sheet_count <= 15 else 10)
    
    for sheet in atlas["sheets"]:
        part = f"\n### Sheet: {sheet['sheet_name']}\n"
        part += f"- Used range: {sheet['used_range']}\n"
        part += f"- Dimensions: {sheet['dimensions']['total_rows']} rows x {sheet['dimensions']['total_cols']} cols\n"
        part += f"- Non-empty cells: {sheet['non_empty_cell_count']}\n"
        part += f"- Merged cells: {len(sheet['merged_cells'])}\n"

        # Include sample cell values (adaptive limit)
        sample_cells = sheet.get("cells", [])[:max_cells_per_sheet]
        if sample_cells:
            part += "\nSample cells:\n"
            for cell in sample_cells:
                val_str = str(cell.get("value", ""))[:80]
                style = ""
                if cell.get("font", {}).get("bold"):
                    style += "[bold]"
                if cell.get("fill_color"):
                    style += "[fill]"
                part += f"  {cell['coordinate']}: {val_str} {style}\n"

        parts.append(part)

    return "\n".join(parts)


def _format_region_details(regions_by_sheet: dict) -> str:
    """Format region details for LLM context."""
    parts = []
    for sheet_name, regions in regions_by_sheet.items():
        part = f"\n### Regions in sheet: {sheet_name}\n"
        for region in regions:
            part += f"\n#### Region: {region.get('region_id', 'unknown')}\n"
            part += f"- Range: {region['range']}\n"
            part += f"- Size: {region['row_count']} rows x {region['col_count']} cols\n"
            part += f"- Density: {region['density']}\n"
            part += f"- Table-like: {region['is_table_like']}\n"
            part += f"- Header candidates: rows {region['header_row_candidates']}\n"
            part += f"- Has borders: {region['has_borders']}\n"
            part += f"- Has fills: {region['has_fills']}\n"

            # Sample values
            samples = region.get("sample_values", [])[:15]
            if samples:
                part += "- Sample values:\n"
                for s in samples:
                    part += f"    {s['coordinate']}: {s['value'][:60]}\n"

        parts.append(part)

    return "\n".join(parts)


def _call_bedrock(prompt: str, config: PipelineConfig) -> str:
    """Call Bedrock Claude for parse plan generation."""
    client = boto3.client(
        "bedrock-runtime",
        region_name=config.aws_region,
        config=BotoConfig(read_timeout=config.read_timeout),
    )

    messages = [{"role": "user", "content": [{"text": prompt}]}]

    response = client.converse(
        modelId=config.bedrock_text_model,
        messages=messages,
        system=[{"text": PARSE_PLAN_SYSTEM_PROMPT}],
        inferenceConfig={
            "maxTokens": config.max_tokens,
            "temperature": config.temperature,
        },
    )

    # Extract text from response
    output = response.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])

    text = ""
    for block in content_blocks:
        if "text" in block:
            text += block["text"]

    return text


def _parse_response(text: str, atlas: dict, regions_by_sheet: dict = None) -> dict:
    """Parse LLM response into parse plan structure."""
    if regions_by_sheet is None:
        regions_by_sheet = {}
    # Strip potential markdown code fences
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        plan = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse LLM JSON response: {e}")
        # Try to extract JSON from the response
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                plan = json.loads(match.group())
            except json.JSONDecodeError:
                plan = _generate_fallback_plan(atlas, regions_by_sheet)
        else:
            plan = _generate_fallback_plan(atlas, regions_by_sheet)

    return plan


def _generate_fallback_plan(atlas: dict, regions_by_sheet: dict) -> dict:
    """Generate a basic parse plan from structural signals when LLM fails."""
    sheets = []

    for sheet in atlas.get("sheets", []):
        sheet_name = sheet["sheet_name"]
        regions = regions_by_sheet.get(sheet_name, [])

        # Heuristic: classify based on size and structure
        sheet_type = "unknown"
        if sheet["dimensions"]["total_rows"] > 20 and sheet["dimensions"]["total_cols"] > 5:
            sheet_type = "mapping_spec"
        elif sheet["dimensions"]["total_rows"] < 10:
            sheet_type = "overview"

        region_plans = []
        for region in regions:
            role = "unknown"
            if region.get("is_table_like"):
                role = "mapping_table"

            region_plans.append({
                "region_id": region.get("region_id", ""),
                "range": region.get("range", ""),
                "semantic_role": role,
                "layout_role_reason": "fallback_heuristic",
                "header_rows": region.get("header_row_candidates", []),
                "data_start_row": (region["header_row_candidates"][-1] + 1) if region.get("header_row_candidates") else region.get("row_span", [1, 1])[0],
                "data_end_row": region.get("row_span", [1, 1])[1],
                "columns": [],
                "related_regions": [],
                "extraction_strategy": {
                    "type": "table_rows" if region.get("is_table_like") else "note_text",
                    "join_strategy": "unknown",
                },
                "uncertainties": ["fallback_plan_needs_review"],
            })

        sheets.append({
            "sheet_name": sheet_name,
            "sheet_index": sheet.get("sheet_index", 0),
            "sheet_type": sheet_type,
            "used_range": sheet.get("used_range", ""),
            "regions": region_plans,
        })

    return {
        "workbook_type": "enterprise_excel_design_document",
        "confidence": 0.3,
        "sheets": sheets,
        "global_uncertainties": ["parse_plan_generated_by_fallback"],
        "human_review_required": ["entire_workbook"],
    }


def save_parse_plan(plan: dict, output_dir: Path) -> Path:
    """Save parse plan to output directory."""
    plan_dir = output_dir / "parse_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)

    # Main plan
    plan_path = plan_dir / "workbook_parse_plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2, default=str)

    # Sheet plans as JSONL
    sheet_plans_path = plan_dir / "sheet_parse_plans.jsonl"
    with open(sheet_plans_path, "w", encoding="utf-8") as f:
        for sheet in plan.get("sheets", []):
            f.write(json.dumps(sheet, ensure_ascii=False, default=str) + "\n")

    # Region plans as JSONL
    region_plans_path = plan_dir / "region_parse_plans.jsonl"
    with open(region_plans_path, "w", encoding="utf-8") as f:
        for sheet in plan.get("sheets", []):
            for region in sheet.get("regions", []):
                record = {"sheet_name": sheet["sheet_name"], **region}
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    return plan_path


def generate_plan_review(plan: dict, output_dir: Path) -> Path:
    """Generate a human-readable review of the parse plan."""
    plan_dir = output_dir / "parse_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    review_path = plan_dir / "parse_plan_review.md"

    lines = [
        f"# Parse Plan Review: {plan.get('workbook_name', 'unknown')}",
        f"\n## Workbook Type: {plan.get('workbook_type', 'unknown')}",
        f"## Confidence: {plan.get('confidence', 0.0)}",
        f"\n## Sheets ({len(plan.get('sheets', []))})",
    ]

    for sheet in plan.get("sheets", []):
        lines.append(f"\n### {sheet['sheet_name']} (type: {sheet.get('sheet_type', 'unknown')})")
        for region in sheet.get("regions", []):
            lines.append(f"\n  - Region: {region.get('region_id', '')} [{region.get('range', '')}]")
            lines.append(f"    Role: {region.get('semantic_role', 'unknown')}")
            lines.append(f"    Reason: {region.get('layout_role_reason', '')}")
            if region.get("uncertainties"):
                lines.append(f"    ⚠️ Uncertainties: {', '.join(region['uncertainties'])}")

    if plan.get("global_uncertainties"):
        lines.append(f"\n## Global Uncertainties")
        for u in plan["global_uncertainties"]:
            lines.append(f"  - {u}")

    if plan.get("human_review_required"):
        lines.append(f"\n## Requires Human Review")
        for h in plan["human_review_required"]:
            lines.append(f"  - {h}")

    with open(review_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return review_path
