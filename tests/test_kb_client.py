"""Tests for hermes_bedrock_agent.kb_client — BedrockKBClient and MultiKBClient."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from hermes_bedrock_agent.config import KBEntry, Settings
from hermes_bedrock_agent.kb_client import (
    BedrockKBClient,
    KBResult,
    MultiKBClient,
    _retrieve_one,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_settings(*kb_pairs: tuple[str, str]) -> Settings:
    """Create a Settings with the given (label, kb_id) pairs."""
    return Settings(
        aws_region="ap-northeast-1",
        knowledge_bases=[KBEntry(kb_id=kid, label=lbl) for lbl, kid in kb_pairs],
    )


def _raw_response(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a fake bedrock-agent-runtime retrieve() response."""
    return {
        "retrievalResults": [
            {
                "content": {"text": c["text"]},
                "score": c.get("score", 0.5),
                "metadata": c.get("metadata", {}),
                "location": c.get("location", {}),
            }
            for c in chunks
        ]
    }


# ---------------------------------------------------------------------------
# KBResult
# ---------------------------------------------------------------------------

class TestKBResult:
    def test_display_source_uses_label(self):
        r = KBResult(text="x", score=1.0, metadata={}, location={}, kb_id="ID", kb_label="myLabel")
        assert r.display_source == "myLabel"

    def test_display_source_falls_back_to_id(self):
        r = KBResult(text="x", score=1.0, metadata={}, location={}, kb_id="KB123", kb_label="")
        assert r.display_source == "KB123"


# ---------------------------------------------------------------------------
# BedrockKBClient (single-KB back-compat)
# ---------------------------------------------------------------------------

class TestBedrockKBClient:
    def _client(self, boto_mock) -> BedrockKBClient:
        s = _make_settings(("docs", "KB001"))
        c = BedrockKBClient(s)
        c.client = boto_mock
        return c

    def test_retrieve_calls_boto(self):
        mock_boto = MagicMock()
        mock_boto.retrieve.return_value = _raw_response([{"text": "hello", "score": 0.9}])
        client = self._client(mock_boto)
        client.retrieve("what is X?", number_of_results=3)
        mock_boto.retrieve.assert_called_once()
        call_kwargs = mock_boto.retrieve.call_args[1]
        assert call_kwargs["knowledgeBaseId"] == "KB001"
        assert call_kwargs["retrievalQuery"] == {"text": "what is X?"}
        assert call_kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["numberOfResults"] == 3

    def test_retrieve_empty_query_raises(self):
        c = self._client(MagicMock())
        with pytest.raises(ValueError, match="empty"):
            c.retrieve("   ")

    def test_retrieve_invalid_top_k_raises(self):
        c = self._client(MagicMock())
        with pytest.raises(ValueError, match="between 1 and 20"):
            c.retrieve("query", number_of_results=0)
        with pytest.raises(ValueError, match="between 1 and 20"):
            c.retrieve("query", number_of_results=21)


# ---------------------------------------------------------------------------
# _retrieve_one (shared helper)
# ---------------------------------------------------------------------------

class TestRetrieveOne:
    def test_returns_raw_response(self):
        mock_client = MagicMock()
        mock_client.retrieve.return_value = {"retrievalResults": []}
        result = _retrieve_one(mock_client, "KB001", "test", 5)
        assert result == {"retrievalResults": []}

    def test_client_error_raises_runtime_error(self):
        from botocore.exceptions import ClientError
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Not allowed"}}, "Retrieve"
        )
        with pytest.raises(RuntimeError, match="AccessDenied"):
            _retrieve_one(mock_client, "KB001", "query", 5)

    def test_botocore_error_raises_runtime_error(self):
        from botocore.exceptions import BotoCoreError
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = BotoCoreError()
        with pytest.raises(RuntimeError, match="AWS SDK error"):
            _retrieve_one(mock_client, "KB001", "query", 5)


# ---------------------------------------------------------------------------
# MultiKBClient
# ---------------------------------------------------------------------------

class TestMultiKBClient:
    def _make_client(self, *kb_pairs, boto_side_effects=None) -> MultiKBClient:
        settings = _make_settings(*kb_pairs)
        client = MultiKBClient(settings)
        mock_boto = MagicMock()
        if boto_side_effects is not None:
            mock_boto.retrieve.side_effect = boto_side_effects
        client._boto_client = mock_boto
        return client

    # -- construction --------------------------------------------------------

    def test_no_kbs_raises(self):
        s = Settings(aws_region="us-east-1", knowledge_bases=[])
        with pytest.raises(RuntimeError, match="No knowledge bases configured"):
            MultiKBClient(s).retrieve("x")

    def test_unknown_kb_id_raises(self):
        s = _make_settings(("docs", "KB001"))
        with pytest.raises(ValueError, match="not found in settings"):
            MultiKBClient(s, kb_ids=["KB_UNKNOWN"])

    def test_kb_ids_filter(self):
        s = _make_settings(("docs", "KB001"), ("sales", "KB002"), ("support", "KB003"))
        client = MultiKBClient(s, kb_ids=["KB001", "KB003"])
        assert {kb.kb_id for kb in client._kbs} == {"KB001", "KB003"}

    # -- retrieve + merge strategies -----------------------------------------

    def _two_kb_effects(self):
        """Two consecutive boto.retrieve() side-effects: KB001 then KB002."""
        return [
            _raw_response([
                {"text": "doc A", "score": 0.9},
                {"text": "doc B", "score": 0.6},
            ]),
            _raw_response([
                {"text": "sales X", "score": 0.8},
                {"text": "sales Y", "score": 0.4},
            ]),
        ]

    def test_merge_score(self):
        client = self._make_client(
            ("docs", "KB001"), ("sales", "KB002"),
            boto_side_effects=self._two_kb_effects(),
        )
        results = client.retrieve("query", number_of_results=2, merge_strategy="score")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_merge_round_robin(self):
        client = self._make_client(
            ("docs", "KB001"), ("sales", "KB002"),
            boto_side_effects=self._two_kb_effects(),
        )
        results = client.retrieve("query", number_of_results=2, merge_strategy="round_robin")
        # round-robin: KB001[0], KB002[0], KB001[1], KB002[1] — but actual
        # ordering depends on futures completion order; just check we have 4 items
        assert len(results) == 4

    def test_merge_kb_order(self):
        client = self._make_client(
            ("docs", "KB001"), ("sales", "KB002"),
            boto_side_effects=self._two_kb_effects(),
        )
        results = client.retrieve("query", number_of_results=2, merge_strategy="kb_order", deduplicate=False)
        assert len(results) == 4

    def test_invalid_merge_strategy_raises(self):
        client = self._make_client(
            ("docs", "KB001"),
            boto_side_effects=[_raw_response([{"text": "x", "score": 0.5}])],
        )
        with pytest.raises(ValueError, match="Unknown merge_strategy"):
            client.retrieve("query", merge_strategy="invalid")

    # -- deduplication -------------------------------------------------------

    def test_deduplication_removes_duplicates(self):
        # Same text returned by both KBs
        effects = [
            _raw_response([{"text": "same text", "score": 0.9}]),
            _raw_response([{"text": "same text", "score": 0.7}]),
        ]
        client = self._make_client(
            ("a", "KB001"), ("b", "KB002"),
            boto_side_effects=effects,
        )
        results = client.retrieve("query", deduplicate=True)
        assert len(results) == 1
        assert results[0].text == "same text"

    def test_no_dedup_keeps_duplicates(self):
        effects = [
            _raw_response([{"text": "same text", "score": 0.9}]),
            _raw_response([{"text": "same text", "score": 0.7}]),
        ]
        client = self._make_client(
            ("a", "KB001"), ("b", "KB002"),
            boto_side_effects=effects,
        )
        results = client.retrieve("query", deduplicate=False)
        assert len(results) == 2

    # -- error resilience ----------------------------------------------------

    def test_failed_kb_is_skipped_others_returned(self):
        from botocore.exceptions import ClientError
        effects = [
            ClientError({"Error": {"Code": "500", "Message": "boom"}}, "Retrieve"),
            _raw_response([{"text": "ok result", "score": 0.8}]),
        ]
        client = self._make_client(
            ("bad", "KB001"), ("good", "KB002"),
            boto_side_effects=effects,
        )
        results = client.retrieve("query")
        assert len(results) == 1
        assert results[0].text == "ok result"

    # -- retrieve_from -------------------------------------------------------

    def test_retrieve_from_single_kb(self):
        client = self._make_client(
            ("docs", "KB001"), ("sales", "KB002"),
            boto_side_effects=[_raw_response([{"text": "only from KB001", "score": 0.95}])],
        )
        results = client.retrieve_from("KB001", "query", number_of_results=1)
        assert len(results) == 1
        assert results[0].kb_id == "KB001"

    def test_retrieve_from_unknown_id_raises(self):
        client = self._make_client(("docs", "KB001"))
        with pytest.raises(ValueError, match="not in client"):
            client.retrieve_from("KB_UNKNOWN", "query")

    # -- kb_id and kb_label on results ---------------------------------------

    def test_result_carries_kb_metadata(self):
        effects = [
            _raw_response([{"text": "hello", "score": 0.7}]),
        ]
        client = self._make_client(("my-docs", "KB001"), boto_side_effects=effects)
        results = client.retrieve("query")
        assert results[0].kb_id == "KB001"
        assert results[0].kb_label == "my-docs"
        assert results[0].display_source == "my-docs"

    # -- validation ----------------------------------------------------------

    def test_empty_query_raises(self):
        client = self._make_client(("docs", "KB001"))
        with pytest.raises(ValueError, match="empty"):
            client.retrieve("  ")

    def test_top_k_out_of_range_raises(self):
        client = self._make_client(("docs", "KB001"))
        with pytest.raises(ValueError):
            client.retrieve("q", number_of_results=0)
        with pytest.raises(ValueError):
            client.retrieve("q", number_of_results=21)
