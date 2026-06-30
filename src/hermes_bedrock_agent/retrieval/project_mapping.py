"""Centralized project ID ↔ Neptune project name mapping.

Single source of truth for project identifier resolution,
replacing duplicated inline maps in graph_expansion.py.
"""
from __future__ import annotations


# ── Canonical mapping tables ────────────────────────────────────────────────────

PROJECT_ID_TO_NEPTUNE_NAME: dict[str, str] = {
    "sample_20260519": "サンプル20260519",
    "saimu_bugyo_cloud": "14_債務奉行クラウド",
}

PROJECT_NEPTUNE_NAME_TO_ID: dict[str, str] = {
    v: k for k, v in PROJECT_ID_TO_NEPTUNE_NAME.items()
}


def to_neptune_project_alias(project_id: str) -> str:
    """Convert a LanceDB/internal project_id to the Neptune-stored project name.

    Returns the Japanese-style project name that Neptune uses for project_id
    or source_project_key fields.

    If project_id is not in the map, returns project_id unchanged (identity fallback).
    """
    if not project_id:
        return project_id
    return PROJECT_ID_TO_NEPTUNE_NAME.get(project_id, project_id)


def to_lancedb_project_id(project_name_or_id: str) -> str:
    """Convert a Neptune project name or any identifier to the canonical LanceDB project_id.

    If the input is already a valid project_id, returns it unchanged.
    If it's a known Neptune name, returns the corresponding project_id.
    Otherwise returns the input unchanged (identity fallback).
    """
    if not project_name_or_id:
        return project_name_or_id
    # Check if it's already a project_id
    if project_name_or_id in PROJECT_ID_TO_NEPTUNE_NAME:
        return project_name_or_id
    # Check if it's a Neptune name
    return PROJECT_NEPTUNE_NAME_TO_ID.get(project_name_or_id, project_name_or_id)
