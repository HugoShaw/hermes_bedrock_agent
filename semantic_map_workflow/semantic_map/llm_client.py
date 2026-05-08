"""
AWS Bedrock LLM client for the semantic map workflow.

Wraps the Bedrock ``InvokeModel`` API for Claude models.  All prompts and raw
responses are persisted to disk for auditability and offline replay.  Rate
limiting is handled with exponential backoff.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional boto3
# ---------------------------------------------------------------------------
try:
    import boto3  # type: ignore
    import botocore.exceptions  # type: ignore
    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore
    _BOTO3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class LLMUnavailableError(RuntimeError):
    """Raised when the Bedrock endpoint cannot be reached or is not configured."""


class LLMResponseError(RuntimeError):
    """Raised when the LLM returns an unexpected or unparseable response."""


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2.0
_BACKOFF_MULTIPLIER = 2.0

# Bedrock throttling error codes
_THROTTLE_CODES = frozenset(
    {
        "ThrottlingException",
        "ServiceUnavailableException",
        "TooManyRequestsException",
        "ModelStreamErrorException",
    }
)


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient:
    """Synchronous client for invoking Claude via AWS Bedrock.

    Parameters
    ----------
    aws_region:
        AWS region where Bedrock is available (e.g. ``"us-east-1"``).
    model_id:
        Bedrock model identifier.
    output_dir:
        Base directory for persisting prompts and raw LLM outputs.  Pass
        ``None`` to disable persistence.
    """

    def __init__(
        self,
        aws_region: str,
        model_id: str = "anthropic.claude-3-haiku-20240307-v1:0",
        output_dir: Optional[str] = None,
    ) -> None:
        if not _BOTO3_AVAILABLE:
            raise LLMUnavailableError(
                "boto3 is required for LLMClient. Install it with: pip install boto3"
            )

        self.aws_region = aws_region
        self.model_id = model_id
        self.output_dir = Path(output_dir) if output_dir else None

        if self.output_dir:
            (self.output_dir / "prompts").mkdir(parents=True, exist_ok=True)
            (self.output_dir / "raw_llm_outputs").mkdir(parents=True, exist_ok=True)

        try:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.aws_region,
            )
        except Exception as exc:
            raise LLMUnavailableError(
                f"Failed to create Bedrock client in {aws_region}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, prompt: str, max_tokens: int = 4096) -> str:
        """Invoke the Bedrock model with *prompt* and return the response text.

        The prompt and raw response are saved to disk when *output_dir* was
        provided.  Throttling errors trigger exponential backoff (up to
        :data:`_MAX_RETRIES` attempts).

        Parameters
        ----------
        prompt:
            The full prompt string sent to the model.
        max_tokens:
            Maximum number of tokens in the model response.

        Returns
        -------
        str
            The model's text response.

        Raises
        ------
        LLMUnavailableError
            When the Bedrock service is unreachable or credentials are missing.
        LLMResponseError
            When the response cannot be parsed.
        """
        body = self._build_request_body(prompt, max_tokens)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prompt_hash = self._short_hash(prompt)
        file_stem = f"{timestamp}_{prompt_hash}"

        if self.output_dir:
            self._save_prompt(prompt, file_stem)

        response_body = self._invoke_with_retry(body, file_stem)
        text = self._extract_text(response_body)

        if self.output_dir:
            self._save_output({"prompt_hash": prompt_hash, "response": response_body}, file_stem)

        return text

    def invoke_with_schema(self, prompt: str, schema_example: dict) -> dict:
        """Invoke the model and parse the first JSON object from the response.

        A ``schema_example`` is appended to the prompt as a formatting hint
        so the model knows the expected output structure.

        Parameters
        ----------
        prompt:
            Base prompt.  The schema hint is appended automatically.
        schema_example:
            A representative dict that shows the expected JSON shape.

        Returns
        -------
        dict
            Parsed JSON response.

        Raises
        ------
        LLMResponseError
            When no valid JSON object is found in the response.
        """
        schema_hint = (
            "\n\nRespond ONLY with a valid JSON object matching this structure:\n"
            + json.dumps(schema_example, indent=2, ensure_ascii=False)
        )
        full_prompt = prompt + schema_hint
        raw = self.invoke(full_prompt)
        return self._parse_json(raw)

    def is_available(self) -> bool:
        """Return ``True`` when the Bedrock endpoint responds to a minimal probe.

        Uses a very short prompt to minimise cost and latency.
        """
        try:
            body = self._build_request_body("Hi", max_tokens=16)
            self._client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            return True
        except Exception as exc:
            logger.warning("LLMClient.is_available: Bedrock probe failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_request_body(self, prompt: str, max_tokens: int) -> dict:
        """Build the Bedrock InvokeModel request body for Anthropic Claude."""
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

    def _invoke_with_retry(self, body: dict, file_stem: str) -> dict:
        """Call Bedrock with exponential backoff on throttling errors."""
        last_exc: Optional[Exception] = None
        backoff = _BASE_BACKOFF_SECONDS

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                raw_body = response["body"].read()
                return json.loads(raw_body)

            except Exception as exc:
                error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
                is_throttle = error_code in _THROTTLE_CODES or "throttl" in str(exc).lower()

                if is_throttle and attempt < _MAX_RETRIES:
                    logger.warning(
                        "Bedrock throttling on attempt %d/%d; backing off %.1fs",
                        attempt,
                        _MAX_RETRIES,
                        backoff,
                    )
                    time.sleep(backoff)
                    backoff *= _BACKOFF_MULTIPLIER
                    last_exc = exc
                    continue

                # Non-throttle or final attempt
                logger.error(
                    "Bedrock invoke failed on attempt %d/%d: %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                if "credentials" in str(exc).lower() or "auth" in str(exc).lower():
                    raise LLMUnavailableError(
                        f"Bedrock authentication failed: {exc}"
                    ) from exc
                raise LLMUnavailableError(f"Bedrock invoke error: {exc}") from exc

        raise LLMUnavailableError(
            f"Bedrock invoke failed after {_MAX_RETRIES} retries"
        ) from last_exc

    def _extract_text(self, response_body: dict) -> str:
        """Extract the assistant text from the Bedrock/Anthropic response body."""
        # Anthropic Messages API response format
        content = response_body.get("content", [])
        if isinstance(content, list):
            texts = [block.get("text", "") for block in content if block.get("type") == "text"]
            return "\n".join(texts)

        # Older completion-style format (fallback)
        completion = response_body.get("completion", "")
        if completion:
            return completion

        raise LLMResponseError(
            f"Cannot extract text from response body keys: {list(response_body.keys())}"
        )

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract the first JSON object found in *text*."""
        # 1. Try direct parse
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # 2. Try to find a JSON block in markdown code fences
        fence_match = re.search(r"```(?:json)?\s*(\{.*?})\s*```", stripped, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Find first { ... } spanning the text
        brace_match = re.search(r"\{.*}", stripped, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        raise LLMResponseError(
            f"No valid JSON object found in LLM response (first 200 chars): {text[:200]!r}"
        )

    def _save_prompt(self, prompt: str, file_stem: str) -> None:
        dest = self.output_dir / "prompts" / f"{file_stem}.txt"  # type: ignore[operator]
        try:
            dest.write_text(prompt, encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save prompt to %s: %s", dest, exc)

    def _save_output(self, payload: dict, file_stem: str) -> None:
        dest = self.output_dir / "raw_llm_outputs" / f"{file_stem}.json"  # type: ignore[operator]
        try:
            dest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Could not save LLM output to %s: %s", dest, exc)

    @staticmethod
    def _short_hash(text: str, length: int = 8) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]
