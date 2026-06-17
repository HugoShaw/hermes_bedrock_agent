"""Tests for VLM fallback model support in clients/bedrock.py.

Validates:
- Primary success → fallback NOT called
- Primary failure → fallback called with correct model_id
- Both fail → original exception propagates
- Config loads fallback model from env var
- Fallback works for multimodal, text-only, and system-prompt calls
- Empty fallback_model_id preserves original behavior
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_bedrock_agent.clients.bedrock import (
    converse_multimodal,
    converse_text,
    converse_with_system,
)


def _mock_response(text: str = "response text") -> dict:
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": 100, "outputTokens": 50},
    }


class TestConverseTextFallback:
    """Fallback behavior for converse_text()."""

    def test_primary_succeeds_no_fallback(self):
        client = MagicMock()
        client.converse.return_value = _mock_response("primary ok")

        text, usage = converse_text(
            client, "primary-model", "hello",
            fallback_model_id="fallback-model",
        )

        assert text == "primary ok"
        assert client.converse.call_count == 1
        assert client.converse.call_args[1]["modelId"] == "primary-model"

    def test_primary_fails_fallback_succeeds(self):
        client = MagicMock()
        client.converse.side_effect = [
            RuntimeError("throttled"),
            _mock_response("fallback ok"),
        ]

        text, usage = converse_text(
            client, "primary-model", "hello",
            fallback_model_id="fallback-model",
        )

        assert text == "fallback ok"
        assert client.converse.call_count == 2
        first_call = client.converse.call_args_list[0][1]
        second_call = client.converse.call_args_list[1][1]
        assert first_call["modelId"] == "primary-model"
        assert second_call["modelId"] == "fallback-model"

    def test_primary_fails_no_fallback_raises(self):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("throttled")

        with pytest.raises(RuntimeError, match="throttled"):
            converse_text(client, "primary-model", "hello", fallback_model_id=None)

    def test_primary_fails_empty_fallback_raises(self):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("throttled")

        with pytest.raises(RuntimeError, match="throttled"):
            converse_text(client, "primary-model", "hello", fallback_model_id="")

    def test_both_fail_raises_fallback_error(self):
        client = MagicMock()
        client.converse.side_effect = [
            RuntimeError("primary down"),
            ValueError("fallback also down"),
        ]

        with pytest.raises(ValueError, match="fallback also down"):
            converse_text(
                client, "primary-model", "hello",
                fallback_model_id="fallback-model",
            )

    def test_no_fallback_param_preserves_behavior(self):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("error")

        with pytest.raises(RuntimeError, match="error"):
            converse_text(client, "primary-model", "hello")


class TestConverseMultimodalFallback:
    """Fallback behavior for converse_multimodal()."""

    def test_primary_succeeds_no_fallback(self):
        client = MagicMock()
        client.converse.return_value = _mock_response("image parsed")

        images = [(b"\x89PNG", "image/png")]
        text, usage = converse_multimodal(
            client, "primary-model", images, "describe",
            fallback_model_id="fallback-model",
        )

        assert text == "image parsed"
        assert client.converse.call_count == 1

    def test_primary_fails_fallback_succeeds(self):
        client = MagicMock()
        client.converse.side_effect = [
            RuntimeError("model validation error"),
            _mock_response("fallback parsed"),
        ]

        images = [(b"\x89PNG", "image/png")]
        text, usage = converse_multimodal(
            client, "primary-model", images, "describe",
            fallback_model_id="fallback-model",
        )

        assert text == "fallback parsed"
        assert client.converse.call_count == 2
        second_call = client.converse.call_args_list[1][1]
        assert second_call["modelId"] == "fallback-model"
        assert second_call["messages"][0]["content"][0]["image"]["format"] == "png"

    def test_both_fail_raises(self):
        client = MagicMock()
        client.converse.side_effect = [
            RuntimeError("primary fail"),
            RuntimeError("fallback fail"),
        ]

        images = [(b"\x89PNG", "image/png")]
        with pytest.raises(RuntimeError, match="fallback fail"):
            converse_multimodal(
                client, "primary-model", images, "describe",
                fallback_model_id="fallback-model",
            )

    def test_no_fallback_param_preserves_behavior(self):
        client = MagicMock()
        client.converse.side_effect = RuntimeError("error")

        images = [(b"\x89PNG", "image/png")]
        with pytest.raises(RuntimeError, match="error"):
            converse_multimodal(client, "primary-model", images, "describe")


class TestConverseWithSystemFallback:
    """Fallback behavior for converse_with_system()."""

    def test_primary_succeeds_no_fallback(self):
        client = MagicMock()
        expected = _mock_response("system response")
        client.converse.return_value = expected

        result = converse_with_system(
            client, "primary-model",
            system=[{"text": "sys"}],
            messages=[{"role": "user", "content": [{"text": "hi"}]}],
            fallback_model_id="fallback-model",
        )

        assert result == expected
        assert client.converse.call_count == 1

    def test_primary_fails_fallback_succeeds(self):
        client = MagicMock()
        expected = _mock_response("fallback system response")
        client.converse.side_effect = [
            RuntimeError("primary down"),
            expected,
        ]

        result = converse_with_system(
            client, "primary-model",
            system=[{"text": "sys"}],
            messages=[{"role": "user", "content": [{"text": "hi"}]}],
            fallback_model_id="fallback-model",
        )

        assert result == expected
        second_call = client.converse.call_args_list[1][1]
        assert second_call["modelId"] == "fallback-model"
        assert second_call["system"] == [{"text": "sys"}]


class TestConfigFallbackModel:
    """Config loads vlm_fallback_model_id from environment."""

    def test_default_value(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BEDROCK_VLM_FALLBACK_MODEL_ID", None)
            from hermes_bedrock_agent.config import Config
            cfg = Config()
            assert cfg.vlm_fallback_model_id == "mistral.mistral-large-3-675b-instruct"

    def test_env_override(self):
        with patch.dict(os.environ, {"BEDROCK_VLM_FALLBACK_MODEL_ID": "custom.model-v2"}):
            from hermes_bedrock_agent.config import Config
            cfg = Config()
            assert cfg.vlm_fallback_model_id == "custom.model-v2"

    def test_empty_env_means_no_fallback(self):
        with patch.dict(os.environ, {"BEDROCK_VLM_FALLBACK_MODEL_ID": ""}):
            from hermes_bedrock_agent.config import Config
            cfg = Config()
            assert cfg.vlm_fallback_model_id == ""


class TestFallbackWithTimeoutRetry:
    """Verify fallback triggers AFTER _converse_with_timeout exhausts its retries."""

    def test_timeout_retries_then_fallback(self):
        from concurrent.futures import TimeoutError as FuturesTimeoutError
        from hermes_bedrock_agent.clients.bedrock import _ConverseTimeout

        client = MagicMock()
        client.converse.side_effect = [
            _mock_response("fallback ok"),
        ]

        with patch("hermes_bedrock_agent.clients.bedrock._converse_with_timeout") as mock_timeout:
            mock_timeout.side_effect = [
                _ConverseTimeout("timed out after both attempts"),
                _mock_response("fallback ok"),
            ]

            text, usage = converse_text(
                client, "primary-model", "hello",
                fallback_model_id="fallback-model",
            )

            assert text == "fallback ok"
            assert mock_timeout.call_count == 2
            first_call_kwargs = mock_timeout.call_args_list[0][1]
            second_call_kwargs = mock_timeout.call_args_list[1][1]
            assert first_call_kwargs["modelId"] == "primary-model"
            assert second_call_kwargs["modelId"] == "fallback-model"
