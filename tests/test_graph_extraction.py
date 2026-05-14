"""Tests for graph/extractor.py — MockGraphExtractor, prompt building, JSON parsing.

All tests use MockGraphExtractor or mocked bedrock_client. No real AWS calls.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from hermes_bedrock_agent.graph.extractor import (
    ExtractionResult,
    ExtractorConfig,
    GraphExtractor,
    MockGraphExtractor,
    build_extraction_prompt,
    parse_llm_json_response,
)
from hermes_bedrock_agent.schemas.chunk import ChunkType, DocumentChunk
from hermes_bedrock_agent.schemas.graph import EntityType, RelationType


def _make_chunk(chunk_id="chunk_001", content="Test content about System A calling Module B", **kwargs):
    """Create a test DocumentChunk."""
    defaults = {
        "chunk_id": chunk_id,
        "document_id": "doc_001",
        "content": content,
        "chunk_index": 0,
        "chunk_type": ChunkType.TEXT,
        "source_uri": "s3://bucket/test.md",
        "page": 1,
        "section_title": "Architecture",
    }
    defaults.update(kwargs)
    return DocumentChunk(**defaults)


class TestBuildExtractionPrompt(unittest.TestCase):
    """Test prompt building."""

    def test_prompt_contains_chunk_text(self):
        chunk = _make_chunk(content="My important text")
        prompt = build_extraction_prompt(chunk)
        self.assertIn("My important text", prompt)

    def test_prompt_contains_source_uri(self):
        chunk = _make_chunk(source_uri="s3://bucket/doc.pdf")
        prompt = build_extraction_prompt(chunk)
        self.assertIn("s3://bucket/doc.pdf", prompt)

    def test_prompt_contains_page(self):
        chunk = _make_chunk(page=5)
        prompt = build_extraction_prompt(chunk)
        self.assertIn("5", prompt)

    def test_prompt_contains_section_title(self):
        chunk = _make_chunk(section_title="Database Design")
        prompt = build_extraction_prompt(chunk)
        self.assertIn("Database Design", prompt)

    def test_prompt_has_json_format_instructions(self):
        chunk = _make_chunk()
        prompt = build_extraction_prompt(chunk)
        self.assertIn("entities", prompt)
        self.assertIn("relations", prompt)
        self.assertIn("JSON", prompt)


class TestParseLlmJsonResponse(unittest.TestCase):
    """Test LLM response parsing with various formats."""

    def test_direct_json(self):
        raw = '{"entities": [{"name": "SystemA"}], "relations": []}'
        result = parse_llm_json_response(raw)
        self.assertEqual(len(result["entities"]), 1)
        self.assertEqual(result["entities"][0]["name"], "SystemA")

    def test_json_code_fence(self):
        raw = '```json\n{"entities": [{"name": "X"}], "relations": []}\n```'
        result = parse_llm_json_response(raw)
        self.assertEqual(result["entities"][0]["name"], "X")

    def test_bare_code_fence(self):
        raw = '```\n{"entities": [], "relations": [{"from_entity": "A", "to_entity": "B"}]}\n```'
        result = parse_llm_json_response(raw)
        self.assertEqual(len(result["relations"]), 1)

    def test_preamble_text_before_json(self):
        raw = 'Here is the extracted data:\n{"entities": [{"name": "Y"}], "relations": []}'
        result = parse_llm_json_response(raw)
        self.assertEqual(result["entities"][0]["name"], "Y")

    def test_trailing_comma_cleanup(self):
        raw = '{"entities": [{"name": "Z",}], "relations": [,]}'
        # After trailing comma removal: [{"name": "Z"}] and []
        result = parse_llm_json_response(raw)
        self.assertEqual(result["entities"][0]["name"], "Z")

    def test_invalid_json_raises(self):
        raw = "This is not JSON at all"
        with self.assertRaises(ValueError):
            parse_llm_json_response(raw)


class TestMockGraphExtractor(unittest.TestCase):
    """Test MockGraphExtractor produces correct structure."""

    def setUp(self):
        self.extractor = MockGraphExtractor()

    def test_extract_chunk_returns_result(self):
        chunk = _make_chunk()
        result = self.extractor.extract_chunk(chunk)
        self.assertIsInstance(result, ExtractionResult)
        self.assertEqual(result.chunk_id, "chunk_001")

    def test_extract_chunk_produces_entities(self):
        chunk = _make_chunk(content="A" * 60)  # > 50 chars for 2 entities
        result = self.extractor.extract_chunk(chunk)
        self.assertGreaterEqual(len(result.entities), 1)

    def test_extract_chunk_produces_relations_for_long_content(self):
        chunk = _make_chunk(content="A" * 60)
        result = self.extractor.extract_chunk(chunk)
        self.assertGreaterEqual(len(result.relations), 1)

    def test_extract_chunk_produces_evidence(self):
        chunk = _make_chunk(content="A" * 60)
        result = self.extractor.extract_chunk(chunk)
        self.assertGreaterEqual(len(result.evidence), 1)

    def test_entities_have_source_chunk_ids(self):
        chunk = _make_chunk(content="A" * 60)
        result = self.extractor.extract_chunk(chunk)
        for entity in result.entities:
            self.assertIn(chunk.chunk_id, entity.source_chunk_ids)

    def test_relations_have_source_chunk_id(self):
        chunk = _make_chunk(content="A" * 60)
        result = self.extractor.extract_chunk(chunk)
        for relation in result.relations:
            self.assertEqual(relation.source_chunk_id, chunk.chunk_id)

    def test_relations_have_confidence(self):
        chunk = _make_chunk(content="A" * 60)
        result = self.extractor.extract_chunk(chunk)
        for relation in result.relations:
            self.assertGreater(relation.confidence, 0.0)
            self.assertLessEqual(relation.confidence, 1.0)

    def test_extract_chunks_batch(self):
        chunks = [_make_chunk(chunk_id=f"chunk_{i}", content="X" * 60) for i in range(3)]
        results = self.extractor.extract_chunks(chunks)
        self.assertEqual(len(results), 3)

    def test_entity_id_stable(self):
        chunk = _make_chunk()
        r1 = self.extractor.extract_chunk(chunk)
        r2 = self.extractor.extract_chunk(chunk)
        self.assertEqual(r1.entities[0].entity_id, r2.entities[0].entity_id)


class TestGraphExtractorWithMockedBedrock(unittest.TestCase):
    """Test GraphExtractor with mocked Bedrock client."""

    def _mock_response(self, json_data):
        """Create mock Bedrock response."""
        return {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(json_data)}]
                }
            }
        }

    def test_extract_chunk_parses_response(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = self._mock_response({
            "entities": [
                {"name": "SystemA", "entity_type": "system", "description": "Main system", "confidence": 0.9}
            ],
            "relations": [
                {
                    "from_entity": "SystemA",
                    "to_entity": "ModuleB",
                    "relation_type": "contains",
                    "description": "SystemA contains ModuleB",
                    "confidence": 0.8,
                    "evidence_text": "SystemA contains ModuleB for processing",
                }
            ],
        })

        extractor = GraphExtractor(bedrock_client=mock_client)
        chunk = _make_chunk()
        result = extractor.extract_chunk(chunk)

        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].name, "SystemA")
        self.assertEqual(result.entities[0].entity_type, EntityType.SYSTEM)
        self.assertEqual(len(result.relations), 1)
        self.assertEqual(result.relations[0].relation_type, RelationType.CONTAINS)

    def test_extract_chunk_handles_empty_response(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": []}}}

        extractor = GraphExtractor(bedrock_client=mock_client)
        chunk = _make_chunk()
        result = extractor.extract_chunk(chunk)

        self.assertEqual(len(result.errors), 1)
        self.assertIn("Empty", result.errors[0])

    def test_extract_chunk_handles_invalid_json(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Not valid JSON"}]}}
        }

        extractor = GraphExtractor(bedrock_client=mock_client)
        chunk = _make_chunk()
        result = extractor.extract_chunk(chunk)

        self.assertEqual(len(result.errors), 1)

    def test_extract_chunk_code_fence_response(self):
        """LLM wraps JSON in code fence — parser handles it."""
        mock_client = MagicMock()
        response_text = '```json\n{"entities": [{"name": "OracleDB", "entity_type": "database", "confidence": 0.9}], "relations": []}\n```'
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": response_text}]}}
        }

        extractor = GraphExtractor(bedrock_client=mock_client)
        chunk = _make_chunk()
        result = extractor.extract_chunk(chunk)

        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0].entity_type, EntityType.DATABASE)

    def test_unknown_entity_type_becomes_unknown(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = self._mock_response({
            "entities": [{"name": "AlienSystem", "entity_type": "alien_type", "confidence": 0.85}],
            "relations": [],
        })

        extractor = GraphExtractor(bedrock_client=mock_client)
        chunk = _make_chunk()
        result = extractor.extract_chunk(chunk)

        self.assertEqual(result.entities[0].entity_type, EntityType.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
