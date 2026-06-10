"""Prompt adapters — load extraction prompts via the correct strategy per version.

Each registered prompt version declares an `adapter` field in manifest.yaml:
  - chunk_level: parse XML sections from the prompt file directly
  - document_to_chunk: load manually adapted prompts from experiments/*_prompts.py

This module never silently falls back to a different version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .registry import get_prompt_content, get_version


class PromptAdapterError(Exception):
    """Raised when an adapter cannot load prompts for a version."""


@dataclass
class ExtractionPrompts:
    """Container for the three extraction prompts."""

    system_prompt: str
    node_prompt: str
    edge_prompt: str
    version_id: str
    scope: str
    sha256: str


def _load_chunk_level(version_id: str) -> ExtractionPrompts:
    """Parse <system_prompt>, <node_extraction_prompt>, <edge_extraction_prompt> from file."""
    pv = get_version(version_id)
    content = get_prompt_content(version_id)

    def _extract_section(tag: str) -> str:
        pattern = f"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else ""

    system = _extract_section("system_prompt")
    node = _extract_section("node_extraction_prompt")
    edge = _extract_section("edge_extraction_prompt")

    if not system:
        raise PromptAdapterError(
            f"Prompt version '{version_id}' file is missing <system_prompt> section. "
            f"File: {pv.prompt_file}"
        )
    if not node:
        raise PromptAdapterError(
            f"Prompt version '{version_id}' file is missing <node_extraction_prompt> section. "
            f"File: {pv.prompt_file}"
        )
    if not edge:
        raise PromptAdapterError(
            f"Prompt version '{version_id}' file is missing <edge_extraction_prompt> section. "
            f"File: {pv.prompt_file}"
        )

    return ExtractionPrompts(
        system_prompt=system,
        node_prompt=node,
        edge_prompt=edge,
        version_id=version_id,
        scope=pv.scope,
        sha256=pv.sha256,
    )


_DOCUMENT_TO_CHUNK_MODULES = {
    "baseline": "hermes_bedrock_agent.experiments.baseline_prompts",
    "v4.4": "hermes_bedrock_agent.experiments.v44_prompts",
}

_DOCUMENT_TO_CHUNK_PREFIXES = {
    "baseline": "BASELINE",
    "v4.4": "V44",
}


def _load_document_to_chunk(version_id: str) -> ExtractionPrompts:
    """Load manually adapted prompts from experiments/*_prompts.py modules."""
    import importlib

    pv = get_version(version_id)

    module_name = _DOCUMENT_TO_CHUNK_MODULES.get(version_id)
    if module_name is None:
        raise PromptAdapterError(
            f"No document_to_chunk adapter module registered for version '{version_id}'. "
            f"To add support, create experiments/<version>_prompts.py with "
            f"<PREFIX>_SYSTEM_PROMPT, <PREFIX>_NODE_EXTRACTION_PROMPT, "
            f"<PREFIX>_EDGE_EXTRACTION_PROMPT constants and register it in "
            f"src/hermes_bedrock_agent/prompts/adapters.py."
        )

    prefix = _DOCUMENT_TO_CHUNK_PREFIXES[version_id]

    try:
        mod = importlib.import_module(module_name)
    except ImportError as e:
        raise PromptAdapterError(
            f"Cannot import adapter module '{module_name}' for version '{version_id}': {e}"
        ) from e

    system_attr = f"{prefix}_SYSTEM_PROMPT"
    node_attr = f"{prefix}_NODE_EXTRACTION_PROMPT"
    edge_attr = f"{prefix}_EDGE_EXTRACTION_PROMPT"

    system = getattr(mod, system_attr, None)
    node = getattr(mod, node_attr, None)
    edge = getattr(mod, edge_attr, None)

    if not system:
        raise PromptAdapterError(
            f"Module '{module_name}' missing attribute '{system_attr}'"
        )
    if not node:
        raise PromptAdapterError(
            f"Module '{module_name}' missing attribute '{node_attr}'"
        )
    if not edge:
        raise PromptAdapterError(
            f"Module '{module_name}' missing attribute '{edge_attr}'"
        )

    return ExtractionPrompts(
        system_prompt=system,
        node_prompt=node,
        edge_prompt=edge,
        version_id=version_id,
        scope=pv.scope,
        sha256=pv.sha256,
    )


_ADAPTER_DISPATCH = {
    "chunk_level": _load_chunk_level,
    "document_to_chunk": _load_document_to_chunk,
}


def get_extraction_prompts(version_id: str) -> ExtractionPrompts:
    """Load prompts for the given version via the correct adapter.

    Returns ExtractionPrompts(system_prompt, node_prompt, edge_prompt, version_id, scope, sha256).

    Raises PromptAdapterError if the adapter is not implemented or prompts cannot be loaded.
    Never silently falls back to a different version.
    """
    pv = get_version(version_id)
    adapter_name = pv.adapter

    loader = _ADAPTER_DISPATCH.get(adapter_name)
    if loader is None:
        raise PromptAdapterError(
            f"Unknown adapter '{adapter_name}' for version '{version_id}'. "
            f"Available adapters: {list(_ADAPTER_DISPATCH.keys())}"
        )

    return loader(version_id)
