"""Logging utilities."""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger."""
    return logging.getLogger(f"flowchart_to_mermaid.{name}")
