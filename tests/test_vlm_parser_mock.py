"""Tests for VlmParser — fully mocked, no real AWS calls.

Tests both mock mode and mocked bedrock_client mode.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_bedrock_agent.parsers.vlm_parser import VlmParser, VLM_SYSTEM_PROMPT
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType


class TestVlmParserMockMode:
    """Tests using VlmParser's built-in mock mode."""

    def test_mock_mode_basic(self):
        """Mock mode returns a valid VisualBlock."""
        parser = VlmParser(mock_mode=True)
        result = parser.parse_image(
            image_base64="iVBORw0KGgoAAAANSUhEUg==",
            image_format="png",
            document_id="doc_test123",
            source_uri="s3://bucket/arch.png",
            page=1,
            image_id="fig_1",
        )

        assert isinstance(result, VisualBlock)
        assert result.visual_id.startswith("vis_")
        assert result.document_id == "doc_test123"
        assert result.source_uri == "s3://bucket/arch.png"
        assert result.page == 1
        assert result.image_id == "fig_1"
        assert result.confidence == 0.85
        assert "mock" in result.model_name.lower()

    def test_mock_mode_default_response(self):
        """Mock mode has sensible default VLM output."""
        parser = VlmParser(mock_mode=True)
        result = parser.parse_image(
            image_base64="AAAA",
            image_format="png",
            document_id="doc_001",
            source_uri="s3://b/img.png",
        )

        assert result.visual_summary == "Mock VLM analysis result"
        assert result.extracted_text == "Mock extracted text from image"
        assert result.diagram_nodes == ["NodeA", "NodeB"]
        assert result.diagram_edges == ["NodeA -> NodeB"]
        assert result.detected_entities == ["SystemA", "ModuleB"]

    def test_mock_mode_custom_response(self):
        """Mock mode with custom response."""
        custom = {
            "visual_type": "table",
            "visual_summary": "Employee salary table",
            "extracted_text": "Name, Salary\nAlice, $100k",
            "table_markdown": "| Name | Salary |\n|---|---|\n| Alice | $100k |",
            "diagram_nodes": [],
            "diagram_edges": [],
            "detected_entities": ["Alice"],
            "confidence": 0.95,
        }
        parser = VlmParser(mock_mode=True, mock_response=custom)
        result = parser.parse_image(
            image_base64="AAAA",
            image_format="png",
            document_id="doc_table",
            source_uri="s3://b/table.png",
        )

        assert result.visual_type == VisualType.TABLE
        assert result.visual_summary == "Employee salary table"
        assert result.table_markdown == "| Name | Salary |\n|---|---|\n| Alice | $100k |"
        assert result.detected_entities == ["Alice"]
        assert result.confidence == 0.95

    def test_mock_mode_visual_id_stable(self):
        """Mock mode produces stable visual IDs."""
        parser = VlmParser(mock_mode=True)
        r1 = parser.parse_image(
            image_base64="AAA", image_format="png",
            document_id="doc_x", source_uri="s3://b/x.png", page=3, image_id="fig2"
        )
        r2 = parser.parse_image(
            image_base64="BBB", image_format="png",
            document_id="doc_x", source_uri="s3://b/x.png", page=3, image_id="fig2"
        )
        assert r1.visual_id == r2.visual_id

    def test_mock_mode_different_pages(self):
        """Different pages produce different visual IDs."""
        parser = VlmParser(mock_mode=True)
        r1 = parser.parse_image(
            image_base64="AAA", image_format="png",
            document_id="doc_x", source_uri="s3://b/x.png", page=1,
        )
        r2 = parser.parse_image(
            image_base64="AAA", image_format="png",
            document_id="doc_x", source_uri="s3://b/x.png", page=2,
        )
        assert r1.visual_id != r2.visual_id


class TestVlmParserWithMockedClient:
    """Tests using a mocked bedrock_client."""

    def _mock_bedrock_response(self, json_content: str) -> dict:
        """Build a mock Bedrock response structure."""
        return {
            "content": [
                {"type": "text", "text": json_content}
            ]
        }

    def test_invoke_model_called(self):
        """Verify bedrock_client.invoke_model is called correctly."""
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = self._mock_bedrock_response(
            '{"visual_type": "architecture", "visual_summary": "System arch", '
            '"extracted_text": "API Gateway -> Lambda", "table_markdown": "", '
            '"diagram_nodes": ["API Gateway", "Lambda"], '
            '"diagram_edges": ["API Gateway -> Lambda"], '
            '"detected_entities": ["API Gateway", "Lambda"], "confidence": 0.9}'
        )

        parser = VlmParser(bedrock_client=mock_client, model_id="anthropic.claude-sonnet-4-20250514-v1:0")
        result = parser.parse_image(
            image_base64="iVBORw0KGgo=",
            image_format="png",
            document_id="doc_arch",
            source_uri="s3://b/arch.png",
            page=1,
        )

        mock_client.invoke_model.assert_called_once()
        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["model_id"] == "anthropic.claude-sonnet-4-20250514-v1:0"
        body = call_kwargs["body"]
        assert body["system"] == VLM_SYSTEM_PROMPT
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"][0]["type"] == "image"

        # Verify result
        assert result.visual_type == VisualType.ARCHITECTURE
        assert result.visual_summary == "System arch"
        assert result.diagram_nodes == ["API Gateway", "Lambda"]
        assert result.confidence == 0.9
        assert result.model_name == "anthropic.claude-sonnet-4-20250514-v1:0"

    def test_json_in_code_block(self):
        """Handle VLM response wrapped in ```json code block."""
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = self._mock_bedrock_response(
            '```json\n{"visual_type": "table", "visual_summary": "Data table", '
            '"extracted_text": "col1, col2", "table_markdown": "| a | b |", '
            '"diagram_nodes": [], "diagram_edges": [], '
            '"detected_entities": [], "confidence": 0.88}\n```'
        )

        parser = VlmParser(bedrock_client=mock_client)
        result = parser.parse_image(
            image_base64="AAAA", image_format="jpeg",
            document_id="doc_t", source_uri="s3://b/t.jpg",
        )

        assert result.visual_type == VisualType.TABLE
        assert result.table_markdown == "| a | b |"
        assert result.confidence == 0.88

    def test_invalid_json_fallback(self):
        """Gracefully handle non-JSON VLM response."""
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = self._mock_bedrock_response(
            "This image shows a network diagram with multiple services connected."
        )

        parser = VlmParser(bedrock_client=mock_client)
        result = parser.parse_image(
            image_base64="AAAA", image_format="png",
            document_id="doc_bad", source_uri="s3://b/bad.png",
        )

        # Should fallback gracefully
        assert "network diagram" in result.visual_summary
        assert result.confidence == 0.3  # Low confidence on fallback

    def test_no_client_raises(self):
        """Raise RuntimeError if no bedrock_client and not mock mode."""
        parser = VlmParser(mock_mode=False, bedrock_client=None)
        with pytest.raises(RuntimeError, match="requires a bedrock_client"):
            parser.parse_image(
                image_base64="AAA", image_format="png",
                document_id="doc_x", source_uri="s3://b/x.png",
            )

    def test_context_hint_included(self):
        """Context hint is included in the user message."""
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = self._mock_bedrock_response(
            '{"visual_type": "flowchart", "visual_summary": "deploy flow", '
            '"extracted_text": "", "table_markdown": "", '
            '"diagram_nodes": [], "diagram_edges": [], '
            '"detected_entities": [], "confidence": 0.7}'
        )

        parser = VlmParser(bedrock_client=mock_client)
        parser.parse_image(
            image_base64="AAAA", image_format="png",
            document_id="doc_ctx", source_uri="s3://b/flow.png",
            context_hint="This is a CI/CD deployment pipeline diagram",
        )

        call_body = mock_client.invoke_model.call_args[1]["body"]
        user_text = call_body["messages"][0]["content"][1]["text"]
        assert "CI/CD deployment pipeline" in user_text


class TestVlmParserBatch:
    """Tests for batch VLM processing."""

    def test_batch_parse(self):
        """Batch parse enriches multiple VisualBlocks."""
        parser = VlmParser(mock_mode=True)
        blocks = [
            VisualBlock(
                visual_id=f"vis_page{i}",
                document_id="doc_batch",
                source_uri="s3://b/doc.pdf",
                page=i,
                image_base64="iVBORw0KGgo=",
                image_format="png",
            )
            for i in range(1, 4)
        ]

        results = parser.parse_batch(blocks, "doc_batch", "s3://b/doc.pdf")
        assert len(results) == 3
        for r in results:
            assert r.visual_summary != ""
            assert r.confidence > 0

    def test_batch_skips_empty_base64(self):
        """Batch skips blocks without image_base64."""
        parser = VlmParser(mock_mode=True)
        blocks = [
            VisualBlock(
                visual_id="vis_noimgp1",
                document_id="doc_batch2",
                page=1,
                image_base64="",  # Empty
            ),
            VisualBlock(
                visual_id="vis_hasimgp2",
                document_id="doc_batch2",
                page=2,
                image_base64="iVBORw0KGgo=",
                image_format="png",
            ),
        ]

        results = parser.parse_batch(blocks, "doc_batch2", "s3://b/doc.pdf")
        assert len(results) == 2
        # First block unchanged (no image)
        assert results[0].visual_summary == ""
        # Second block enriched
        assert results[1].visual_summary != ""
