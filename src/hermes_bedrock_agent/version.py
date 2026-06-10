"""Version tracking for reproducible experiments."""

from __future__ import annotations

import subprocess
from importlib.metadata import version as pkg_version


def get_code_version() -> str:
    """Get version from git tag if available, else pyproject.toml."""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return tag
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            return pkg_version("hermes_bedrock_agent")
        except Exception:
            return "unknown"
