"""Batch manifest loader and processor for Excel conversion."""
from pathlib import Path
from typing import Optional
import yaml


def load_manifest(manifest_path: str) -> dict:
    """Load batch manifest YAML."""
    with open(manifest_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def validate_manifest(manifest: dict) -> list[str]:
    """Validate manifest structure, return list of errors."""
    errors = []
    jobs = manifest.get("jobs", [])
    if not jobs:
        errors.append("No jobs defined in manifest")
        return errors
    
    for i, job in enumerate(jobs):
        if not job.get("document_id"):
            errors.append(f"Job {i}: missing document_id")
        if not job.get("input_uri"):
            errors.append(f"Job {i}: missing input_uri")
    
    return errors
