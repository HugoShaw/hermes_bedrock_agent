"""Tests for generation/answer_generator.py and generation/prompts.py.

All tests use mock bedrock_client or mock_mode. No real Bedrock calls.
Validates answer generator does NOT access OpenSearch/Neptune directly.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from hermes_bedrock_agent.generation.answer_generator import (
    AnswerGenerator,
    AnswerGeneratorConfig,
)
from hermes_bedrock_agent.generation.prompts import (
    GRAPHRAG_NO_EVIDENCE_PROMPT,
    GRAPHRAG_SYSTEM_PROMPT,
    GRAPHRAG_USER_PROMPT_TEMPLATE,
    build_answer_prompt,
    get_prompt_version,
    get_system_prompt,
)
from hermes_bedrock_agent.schemas.retrieval import (
    FusedContext,
    GraphEvidence,
    RetrievalSource,
    TextEvidence,
)


def _make_text_evidence(chunk_id: str, content: str = "test") -> TextEvidence:
    return TextEvidence(
        evidence_id=f"te_{chunk_id}",
        chunk_id=chunk_id,
        document_id=f"doc_{chunk_id}",
        content=content,
        source_uri=f"s3://b/{chunk_id}.pdf",
        page=1,
        score=0.8,
        rank=0,
    )


def _make_graph_evidence(entity_id: str, content: str = "graph") -> GraphEvidence:
    return GraphEvidence(
        evidence_id=f"ge_{entity_id}",
        entity_id=entity_id,
        content=content,
        source_chunk_ids=["c1"],
        score=0.7,
        rank=0,
    )


def _make_fused_context(
    text: list[TextEvidence] | None = None,
    graph: list[GraphEvidence] | None = None,
) -> FusedContext:
    t = text or []
    g = graph or []
    return FusedContext(
        query="test question",
        text_evidence=t,
        graph_evidence=g,
        total_evidence_count=len(t) + len(g),
    )


# ===========================================================================
# Prompt tests
# ===========================================================================


class TestPrompts(unittest.TestCase):
    """Test prompt template content and structure."""

    def test_system_prompt_has_citation_rules(self):
        self.assertIn("cite", GRAPHRAG_SYSTEM_PROMPT.lower())
        self.assertIn("[T1]", GRAPHRAG_SYSTEM_PROMPT)
        self.assertIn("[G1]", GRAPHRAG_SYSTEM_PROMPT)

    def test_system_prompt_has_no_fabrication_rule(self):
        self.assertIn("NEVER fabricate", GRAPHRAG_SYSTEM_PROMPT)
        self.assertIn("NEVER invent", GRAPHRAG_SYSTEM_PROMPT)

    def test_system_prompt_has_insufficient_evidence_rule(self):
        # Must mention what to do when evidence is insufficient
        prompt_lower = GRAPHRAG_SYSTEM_PROMPT.lower()
        self.assertTrue(
            "insufficient" in prompt_lower or "確認" in GRAPHRAG_SYSTEM_PROMPT
            or "确认" in GRAPHRAG_SYSTEM_PROMPT
        )

    def test_user_prompt_template_has_placeholders(self):
        self.assertIn("{question}", GRAPHRAG_USER_PROMPT_TEMPLATE)
        self.assertIn("{context}", GRAPHRAG_USER_PROMPT_TEMPLATE)

    def test_no_evidence_prompt_has_placeholder(self):
        self.assertIn("{question}", GRAPHRAG_NO_EVIDENCE_PROMPT)

    def test_build_answer_prompt_with_context(self):
        sys_p, user_p = build_answer_prompt("What is X?", "## Text Evidence\n...")
        self.assertEqual(sys_p, GRAPHRAG_SYSTEM_PROMPT)
        self.assertIn("What is X?", user_p)
        self.assertIn("Text Evidence", user_p)

    def test_build_answer_prompt_empty_context(self):
        sys_p, user_p = build_answer_prompt("What is X?", "")
        self.assertIn("No relevant evidence", user_p)
        self.assertNotIn("{question}", user_p)  # Placeholder substituted

    def test_get_prompt_version(self):
        version = get_prompt_version()
        self.assertTrue(len(version) > 0)
        self.assertIn("graphrag", version)

    def test_get_system_prompt(self):
        self.assertEqual(get_system_prompt(), GRAPHRAG_SYSTEM_PROMPT)


# ===========================================================================
# Answer generator tests
# ===========================================================================


class TestAnswerGeneratorMockMode(unittest.TestCase):
    """Test answer generator in mock mode (no Bedrock calls)."""

    def setUp(self):
        config = AnswerGeneratorConfig(mock_mode=True)
        self.generator = AnswerGenerator(config=config)

    def test_generates_answer(self):
        fused = _make_fused_context(text=[_make_text_evidence("c1", "some content")])
        result = self.generator.generate_answer("What is X?", fused)
        self.assertTrue(len(result.answer) > 0)

    def test_answer_result_fields(self):
        fused = _make_fused_context(
            text=[_make_text_evidence("c1")],
            graph=[_make_graph_evidence("e1")],
        )
        result = self.generator.generate_answer("Q?", fused)
        self.assertEqual(result.query, "Q?")
        self.assertEqual(result.text_evidence_used, 1)
        self.assertEqual(result.graph_evidence_used, 1)
        self.assertIsNotNone(result.generation_time_ms)
        self.assertTrue(len(result.prompt_template) > 0)

    def test_mock_includes_evidence_refs(self):
        fused = _make_fused_context(
            text=[_make_text_evidence("c1", "important info")],
            graph=[_make_graph_evidence("e1", "graph info")],
        )
        result = self.generator.generate_answer("Q?", fused)
        self.assertIn("[T1]", result.answer)
        self.assertIn("[G1]", result.answer)

    def test_mock_no_evidence_message(self):
        fused = _make_fused_context()
        result = self.generator.generate_answer("Q?", fused)
        self.assertIn("confirmation", result.answer.lower())

    def test_no_bedrock_client_needed(self):
        # Mock mode works without bedrock_client
        config = AnswerGeneratorConfig(mock_mode=True)
        gen = AnswerGenerator(config=config)
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = gen.generate_answer("Q?", fused)
        self.assertTrue(len(result.answer) > 0)


class TestAnswerGeneratorWithClient(unittest.TestCase):
    """Test answer generator with mock bedrock_client."""

    def setUp(self):
        self.mock_client = MagicMock()
        config = AnswerGeneratorConfig(mock_mode=False)
        self.generator = AnswerGenerator(
            bedrock_client=self.mock_client, config=config
        )

    def test_calls_invoke_model(self):
        self.mock_client.invoke_model.return_value = {
            "content": [{"text": "Answer based on [T1] evidence."}]
        }
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = self.generator.generate_answer("Q?", fused)
        self.mock_client.invoke_model.assert_called_once()
        self.assertIn("evidence", result.answer)

    def test_passes_model_id(self):
        config = AnswerGeneratorConfig(
            model_id="anthropic.claude-sonnet-4-20250514-v1:0", mock_mode=False
        )
        gen = AnswerGenerator(bedrock_client=self.mock_client, config=config)
        self.mock_client.invoke_model.return_value = {"content": [{"text": "ok"}]}
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        gen.generate_answer("Q?", fused)
        _, kwargs = self.mock_client.invoke_model.call_args
        self.assertEqual(kwargs["model_id"], "anthropic.claude-sonnet-4-20250514-v1:0")

    def test_handles_invoke_error(self):
        self.mock_client.invoke_model.side_effect = Exception("Throttled")
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = self.generator.generate_answer("Q?", fused)
        # Should not crash, returns error message
        self.assertIn("失敗", result.answer)

    def test_invoke_body_has_system_prompt(self):
        self.mock_client.invoke_model.return_value = {"content": [{"text": "ok"}]}
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        self.generator.generate_answer("Q?", fused)
        call_kwargs = self.mock_client.invoke_model.call_args[1]
        body = call_kwargs["body"]
        self.assertIn("system", body)
        self.assertIn("NEVER fabricate", body["system"])


class TestAnswerGeneratorNoDirectAccess(unittest.TestCase):
    """Verify answer generator does NOT access OpenSearch/Neptune."""

    def test_does_not_import_opensearch(self):
        import hermes_bedrock_agent.generation.answer_generator as mod
        source = open(mod.__file__).read()
        # Check import statements, not docstrings/comments
        self.assertNotIn("from hermes_bedrock_agent.clients.opensearch_client", source)
        self.assertNotIn("from hermes_bedrock_agent.clients.neptune_client", source)

    def test_only_receives_fused_context(self):
        """Generator signature only accepts FusedContext, not raw clients."""
        import inspect
        sig = inspect.signature(AnswerGenerator.generate_answer)
        params = list(sig.parameters.keys())
        # Only self, question, fused_context
        self.assertIn("question", params)
        self.assertIn("fused_context", params)
        self.assertNotIn("opensearch_client", params)
        self.assertNotIn("neptune_client", params)


class TestCitationExtraction(unittest.TestCase):
    """Test citation extraction from answer text."""

    def setUp(self):
        self.mock_client = MagicMock()
        config = AnswerGeneratorConfig(mock_mode=False)
        self.generator = AnswerGenerator(
            bedrock_client=self.mock_client, config=config
        )

    def test_extracts_text_citations(self):
        answer = "According to [T1], the system handles batch. See also [T2]."
        self.mock_client.invoke_model.return_value = {
            "content": [{"text": answer}]
        }
        fused = _make_fused_context(
            text=[
                _make_text_evidence("c1", "batch processing"),
                _make_text_evidence("c2", "more info"),
            ]
        )
        result = self.generator.generate_answer("Q?", fused)
        self.assertEqual(len(result.citations), 2)
        self.assertEqual(result.citations[0].chunk_id, "c1")
        self.assertEqual(result.citations[1].chunk_id, "c2")

    def test_extracts_graph_citations(self):
        answer = "The graph shows [G1] is connected."
        self.mock_client.invoke_model.return_value = {
            "content": [{"text": answer}]
        }
        fused = _make_fused_context(
            graph=[_make_graph_evidence("e1", "entity info")]
        )
        result = self.generator.generate_answer("Q?", fused)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].citation_type, RetrievalSource.NEPTUNE_GRAPH)

    def test_no_citations_when_none_referenced(self):
        answer = "I don't have enough information."
        self.mock_client.invoke_model.return_value = {
            "content": [{"text": answer}]
        }
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = self.generator.generate_answer("Q?", fused)
        self.assertEqual(len(result.citations), 0)


class TestConfidenceEstimation(unittest.TestCase):
    """Test answer confidence scoring."""

    def setUp(self):
        config = AnswerGeneratorConfig(mock_mode=True)
        self.generator = AnswerGenerator(config=config)

    def test_zero_confidence_no_evidence(self):
        fused = _make_fused_context()
        result = self.generator.generate_answer("Q?", fused)
        self.assertEqual(result.confidence, 0.0)

    def test_higher_confidence_with_more_evidence(self):
        fused_low = _make_fused_context(text=[_make_text_evidence("c1")])
        fused_high = _make_fused_context(
            text=[_make_text_evidence(f"c{i}") for i in range(5)],
            graph=[_make_graph_evidence(f"e{i}") for i in range(3)],
        )
        result_low = self.generator.generate_answer("Q?", fused_low)
        result_high = self.generator.generate_answer("Q?", fused_high)
        self.assertGreater(result_high.confidence, result_low.confidence)

    def test_confidence_bounded(self):
        fused = _make_fused_context(
            text=[_make_text_evidence(f"c{i}") for i in range(20)]
        )
        result = self.generator.generate_answer("Q?", fused)
        self.assertLessEqual(result.confidence, 1.0)
        self.assertGreaterEqual(result.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
