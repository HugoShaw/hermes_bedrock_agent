"""Source file scanner and inventory builder."""
import json
from pathlib import Path
from typing import Any

from ..config import PipelineConfig
from ..io.s3_io import S3IO


EXCEL_EXTENSIONS = [".xlsx", ".xlsm", ".xls"]
MERMAID_EXTENSIONS = [".mmd", ".mermaid"]
ALL_EXTENSIONS = EXCEL_EXTENSIONS + MERMAID_EXTENSIONS + [".md", ".json", ".png", ".jpg"]


def scan_sources(config: PipelineConfig) -> dict:
    """Scan S3 prefix and build source inventory."""
    s3 = S3IO(config.s3_bucket, config.aws_region)

    all_objects = s3.list_objects(config.s3_input_prefix)

    # Classify files
    excel_files = []
    mermaid_files = []
    other_files = []

    for obj in all_objects:
        key = obj["key"]
        lower_key = key.lower()
        if any(lower_key.endswith(ext) for ext in EXCEL_EXTENSIONS):
            obj["file_type"] = "excel"
            excel_files.append(obj)
        elif any(lower_key.endswith(ext) for ext in MERMAID_EXTENSIONS):
            obj["file_type"] = "mermaid"
            mermaid_files.append(obj)
        else:
            obj["file_type"] = "other"
            other_files.append(obj)

    manifest = {
        "source_prefix": f"s3://{config.s3_bucket}/{config.s3_input_prefix}",
        "scan_summary": {
            "total_objects": len(all_objects),
            "excel_files": len(excel_files),
            "mermaid_files": len(mermaid_files),
            "other_files": len(other_files),
        },
        "excel_files": excel_files,
        "mermaid_files": mermaid_files,
        "other_files": other_files,
    }

    return manifest


def download_source_files(config: PipelineConfig, manifest: dict) -> dict:
    """Download all source files locally."""
    s3 = S3IO(config.s3_bucket, config.aws_region)
    downloaded = {}

    for file_list in [manifest["excel_files"], manifest["mermaid_files"]]:
        for obj in file_list:
            key = obj["key"]
            # Create local path preserving relative structure
            relative = key[len(config.s3_input_prefix):].lstrip("/")
            local_path = config.downloads_dir / relative
            s3.download_file(key, local_path)
            downloaded[key] = str(local_path)
            obj["local_path"] = str(local_path)

    return downloaded


def save_manifest(config: PipelineConfig, manifest: dict):
    """Save manifest to output directory."""
    output_path = config.output_dir / "source_files_manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return output_path
