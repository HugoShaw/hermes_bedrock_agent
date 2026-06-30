"""Prompt version registry — loads versions from prompts/graph_extraction/manifest.yaml."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml


_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "graph_extraction"
_MANIFEST_PATH = _PROMPTS_DIR / "manifest.yaml"


@dataclass
class PromptVersion:
    """Metadata about a registered prompt version."""

    version: str
    name: str
    description: str
    prompt_file: Path
    sha256: str
    scope: str
    created_at: str
    adapter: str
    status: str


def _load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found: {_MANIFEST_PATH}")
    return yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _compute_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def list_versions() -> list[PromptVersion]:
    """List all registered prompt versions."""
    manifest = _load_manifest()
    versions = []
    for vid, meta in manifest.get("versions", {}).items():
        prompt_file = _PROMPTS_DIR / meta["file"]
        versions.append(PromptVersion(
            version=vid,
            name=meta["name"],
            description=meta["description"],
            prompt_file=prompt_file,
            sha256=_compute_sha256(prompt_file),
            scope=meta.get("scope", "chunk"),
            created_at=meta.get("created_at", ""),
            adapter=meta.get("adapter", "chunk_level"),
            status=meta.get("status", "experimental"),
        ))
    return versions


def get_version(version_id: str) -> PromptVersion:
    """Get a specific prompt version by ID."""
    manifest = _load_manifest()
    versions = manifest.get("versions", {})
    if version_id not in versions:
        available = ", ".join(versions.keys())
        raise KeyError(f"Unknown prompt version '{version_id}'. Available: {available}")
    meta = versions[version_id]
    prompt_file = _PROMPTS_DIR / meta["file"]
    return PromptVersion(
        version=version_id,
        name=meta["name"],
        description=meta["description"],
        prompt_file=prompt_file,
        sha256=_compute_sha256(prompt_file),
        scope=meta.get("scope", "chunk"),
        created_at=meta.get("created_at", ""),
        adapter=meta.get("adapter", "chunk_level"),
        status=meta.get("status", "experimental"),
    )


def get_prompt_content(version_id: str) -> str:
    """Load the full prompt text for a version."""
    pv = get_version(version_id)
    if not pv.prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {pv.prompt_file}")
    return pv.prompt_file.read_text(encoding="utf-8")


def get_current_version() -> str:
    """Get the currently active prompt version from env or manifest default."""
    env_version = os.getenv("GRAPH_PROMPT_VERSION", "")
    if env_version:
        return env_version
    manifest = _load_manifest()
    return manifest.get("default", "v4.3")


def get_code_version() -> str:
    """Get the current code version from git tag or pyproject.toml."""
    from ..version import get_code_version as _get_code_version
    return _get_code_version()


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _get_git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _get_git_tag() -> str:
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def get_experiment_metadata(version_id: str) -> dict:
    """Return full experiment metadata dict for saving in output files."""
    pv = get_version(version_id)
    return {
        "git_commit": _get_git_commit(),
        "git_branch": _get_git_branch(),
        "git_tag": _get_git_tag(),
        "code_version": get_code_version(),
        "graph_prompt_version": pv.version,
        "graph_prompt_scope": pv.scope,
        "graph_prompt_adapter": pv.adapter,
        "graph_prompt_file_path": str(pv.prompt_file),
        "graph_prompt_sha256": pv.sha256,
        "created_at": pv.created_at,
    }
