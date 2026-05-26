"""Base LLM client interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):
    """Abstract interface for LLM text/vision calls."""

    @abstractmethod
    def invoke_text(self, prompt: str, system: str = "") -> str:
        """Send a text prompt and return the response text."""
        ...

    @abstractmethod
    def invoke_vision(self, prompt: str, image_bytes: bytes, media_type: str = "image/png") -> str:
        """Send a prompt + image and return the response text."""
        ...

    @abstractmethod
    def invoke_structured(self, prompt: str, schema: dict[str, Any], system: str = "") -> dict[str, Any]:
        """Send a prompt expecting structured JSON output conforming to schema."""
        ...
