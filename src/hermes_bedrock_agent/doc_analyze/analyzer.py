"""Core analysis logic: download S3 files, send to Bedrock, return structured result."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import boto3

from hermes_bedrock_agent.graphrag.extractor import extract_text, SUPPORTED_FILE_TYPES
from hermes_bedrock_agent.graphrag.s3_reader import list_files, download_file


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    id: str
    name: str
    type: str  # company|subsidiary|department|system|module|team|other
    description: str


@dataclass
class Relationship:
    from_id: str
    to_id: str
    type: str  # hierarchy|integration|data_flow|business_process|other
    label: str
    direction: str  # uni|bi


@dataclass
class AnalysisResult:
    summary: str
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    raw_response: str = ""
    parse_error: str = ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_JSON_SCHEMA = """{
  "summary": "brief text summary of what was found",
  "entities": [
    {"id": "unique_id", "name": "display name", "type": "company|subsidiary|department|system|module|team|other", "description": "brief description"}
  ],
  "relationships": [
    {"from_id": "entity_id", "to_id": "entity_id", "type": "hierarchy|integration|data_flow|business_process|other", "label": "relationship label", "direction": "uni|bi"}
  ]
}"""


def _build_prompt(file_contents: dict[str, str]) -> str:
    sections: list[str] = []
    for filename, text in file_contents.items():
        sections.append(f"=== FILE: {filename} ===\n{text}\n=== END: {filename} ===")

    files_block = "\n\n".join(sections)

    return f"""You are an expert enterprise architect analyzing company documents.

Below are the contents of {len(file_contents)} document(s). Analyze ALL of them together to identify:
1. Hierarchical relationships: organizational hierarchy (company/subsidiary/department/team), system hierarchy (parent system/subsystem/module), ownership chains
2. Cross-system / cross-subsidiary relationships: data flows, integrations, API connections, shared resources, business processes that span entities

Return ONLY raw JSON (no markdown, no explanation, no code blocks) that strictly follows this schema:
{_JSON_SCHEMA}

Be thorough — identify ALL relationships visible in the documents. Use concise but descriptive labels.

DOCUMENTS:
{files_block}"""


# ---------------------------------------------------------------------------
# JSON parsing with fallbacks
# ---------------------------------------------------------------------------

def _parse_json_robust(text: str) -> tuple[dict, str]:
    """Try multiple strategies to extract JSON from *text*. Returns (data, error)."""
    # 1. Direct parse
    try:
        return json.loads(text), ""
    except json.JSONDecodeError:
        pass

    # 2. Strip ```json ... ``` or ``` ... ``` blocks
    for pattern in (r"```json\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip()), ""
            except json.JSONDecodeError:
                pass

    # 3. Find first { ... last }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first:last + 1]), ""
        except json.JSONDecodeError:
            pass

    return {}, f"Could not parse JSON from LLM response (length={len(text)})"


# ---------------------------------------------------------------------------
# Bedrock call
# ---------------------------------------------------------------------------

def _call_bedrock(prompt: str, model_id: str, region: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=region)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    })
    try:
        response = client.invoke_model(modelId=model_id, body=body)
        response_body = json.loads(response["body"].read())
        return response_body["content"][0]["text"]
    except Exception as exc:
        raise RuntimeError(f"Bedrock invoke_model failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_directory(
    bucket: str,
    prefix: str,
    region: str,
    model_id: str,
    max_chars_per_file: int = 8000,
) -> AnalysisResult:
    """List S3 files under *prefix*, extract text, call Bedrock, return AnalysisResult."""

    # 1. List files
    all_files = list_files(bucket, prefix, region)
    supported = [
        f for f in all_files
        if f["key"].rsplit(".", 1)[-1].lower() in SUPPORTED_FILE_TYPES  # type: ignore[operator]
        and not str(f["key"]).endswith("/")
    ]

    if not supported:
        raise RuntimeError(
            f"No supported documents found in s3://{bucket}/{prefix}. "
            f"Supported types: {sorted(SUPPORTED_FILE_TYPES)}. "
            f"Total objects found: {len(all_files)}."
        )

    # 2. Download and extract text
    file_contents: dict[str, str] = {}
    for obj in supported:
        s3_key = str(obj["key"])
        filename = s3_key.split("/")[-1]
        file_type = s3_key.rsplit(".", 1)[-1].lower()
        try:
            content_bytes = download_file(bucket, s3_key, region)
            text = extract_text(content_bytes, file_type)
            file_contents[filename] = text[:max_chars_per_file]
        except Exception as exc:
            import warnings
            warnings.warn(f"Skipping {s3_key}: {exc}")

    if not file_contents:
        raise RuntimeError("All files failed to download or extract. Check S3 permissions and file formats.")

    # 3. Build prompt and call Bedrock
    prompt = _build_prompt(file_contents)
    raw_response = _call_bedrock(prompt, model_id, region)

    # 4. Parse JSON
    data, parse_error = _parse_json_robust(raw_response)

    if parse_error:
        return AnalysisResult(
            summary="Failed to parse LLM response.",
            raw_response=raw_response,
            parse_error=parse_error,
        )

    # 5. Build typed result
    entities = [
        Entity(
            id=e.get("id", ""),
            name=e.get("name", ""),
            type=e.get("type", "other"),
            description=e.get("description", ""),
        )
        for e in data.get("entities", [])
    ]
    relationships = [
        Relationship(
            from_id=r.get("from_id", ""),
            to_id=r.get("to_id", ""),
            type=r.get("type", "other"),
            label=r.get("label", ""),
            direction=r.get("direction", "uni"),
        )
        for r in data.get("relationships", [])
    ]

    return AnalysisResult(
        summary=data.get("summary", ""),
        entities=entities,
        relationships=relationships,
        raw_response=raw_response,
    )
