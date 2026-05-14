"""Tests for retrieval/context_builder.py — structured LLM context generation.

No real AWS calls.
"""

from __future__ import annotations

import unittest

from hermes_bedrock_agent.retrieval.context_builder import (
    ContextBuilder,
    ContextBuilderConfig,
)
from hermes_bedrock_agent.schemas.retrieval import (
    FusedContext,
    GraphEvidence,
    RetrievalSource,
    TextEvidence,
)


def _make_text_evidence(chunk_id: str, **kwargs) -> TextEvidence:
    defaults = {
        "evidence_id": f"te_{chunk_id}",
        "chunk_id": chunk_id,
        "document_id": f"doc_{chunk_id}",
        "content": f"Text content from {chunk_id}",
        "source_uri": f"s3://bucket/{chunk_id}.pdf",
        "section_title": "Section A",
        "page": 5,
        "score": 0.8,
        "rank": 0,
    }
    defaults.update(kwargs)
    return TextEvidence(**defaults)


def _make_graph_evidence(entity_id: str, **kwargs) -> GraphEvidence:
    defaults = {
        "evidence_id": f"ge_{entity_id}",
        "entity_id": entity_id,
        "content": f"[system] {entity_id}: A system entity",
        "source_chunk_ids": ["c1", "c2"],
        "score": 0.7,
        "rank": 0,
    }
    defaults.update(kwargs)
    return GraphEvidence(**defaults)


def _make_fused_context(
    text: list[TextEvidence] | None = None,
    graph: list[GraphEvidence] | None = None,
) -> FusedContext:
    t = text or []
    g = graph or []
    return FusedContext(
        query="test query",
        text_evidence=t,
        graph_evidence=g,
        total_evidence_count=len(t) + len(g),
    )


class TestBuildContext(unittest.TestCase):
    """Test full context building."""

    def setUp(self):
        self.builder = ContextBuilder()

    def test_produces_nonempty_string(self):
        fused = _make_fused_context(
            text=[_make_text_evidence("c1")],
            graph=[_make_graph_evidence("e1")],
        )
        result = self.builder.build_context(fused)
        self.assertTrue(len(result) > 0)

    def test_contains_text_evidence_section(self):
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = self.builder.build_context(fused)
        self.assertIn("## Text Evidence", result)
        self.assertIn("[T1]", result)
        self.assertIn("Text content from c1", result)

    def test_contains_graph_context_section(self):
        fused = _make_fused_context(graph=[_make_graph_evidence("e1")])
        result = self.builder.build_context(fused)
        self.assertIn("## Graph Context", result)
        self.assertIn("[G1]", result)

    def test_contains_source_citations(self):
        fused = _make_fused_context(
            text=[_make_text_evidence("c1", source_uri="s3://b/doc.pdf", page=3)],
        )
        result = self.builder.build_context(fused)
        self.assertIn("## Source Citations", result)
        self.assertIn("chunk_id=c1", result)
        self.assertIn("s3://b/doc.pdf", result)
        self.assertIn("page=3", result)

    def test_contains_graph_paths(self):
        graph_ev = _make_graph_evidence(
            "e1", path_description="SystemA --calls--> ModuleB"
        )
        fused = _make_fused_context(graph=[graph_ev])
        result = self.builder.build_context(fused)
        self.assertIn("## Graph Paths", result)
        self.assertIn("SystemA --calls--> ModuleB", result)

    def test_missing_evidence_warning(self):
        fused = _make_fused_context()  # No evidence
        config = ContextBuilderConfig(min_evidence_threshold=1)
        builder = ContextBuilder(config=config)
        result = builder.build_context(fused)
        self.assertIn("Evidence Warning", result)

    def test_no_warning_when_sufficient_evidence(self):
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = self.builder.build_context(fused)
        self.assertNotIn("Evidence Warning", result)


class TestTextSection(unittest.TestCase):
    """Test text evidence section formatting."""

    def setUp(self):
        self.builder = ContextBuilder()

    def test_multiple_text_items(self):
        text = [_make_text_evidence("c1"), _make_text_evidence("c2")]
        fused = _make_fused_context(text=text)
        result = self.builder.build_context(fused)
        self.assertIn("[T1]", result)
        self.assertIn("[T2]", result)

    def test_includes_source_uri(self):
        text = [_make_text_evidence("c1", source_uri="s3://bucket/file.md")]
        fused = _make_fused_context(text=text)
        result = self.builder.build_context(fused)
        self.assertIn("s3://bucket/file.md", result)

    def test_includes_page_number(self):
        text = [_make_text_evidence("c1", page=42)]
        fused = _make_fused_context(text=text)
        result = self.builder.build_context(fused)
        self.assertIn("p.42", result)

    def test_includes_section_title(self):
        text = [_make_text_evidence("c1", section_title="Data Model")]
        fused = _make_fused_context(text=text)
        result = self.builder.build_context(fused)
        self.assertIn("Data Model", result)

    def test_truncation_at_max_chars(self):
        config = ContextBuilderConfig(max_text_chars=50)
        builder = ContextBuilder(config=config)
        text = [_make_text_evidence(f"c{i}", content="x" * 100) for i in range(5)]
        fused = _make_fused_context(text=text)
        result = builder.build_context(fused)
        self.assertIn("truncated", result)


class TestGraphSection(unittest.TestCase):
    """Test graph context section formatting."""

    def setUp(self):
        self.builder = ContextBuilder()

    def test_entity_content(self):
        graph = [_make_graph_evidence("e1", content="[module] 仕訳基礎: Journal base")]
        fused = _make_fused_context(graph=graph)
        result = self.builder.build_context(fused)
        self.assertIn("仕訳基礎", result)

    def test_hop_count_shown(self):
        graph = [_make_graph_evidence("e1", hop_count=2)]
        fused = _make_fused_context(graph=graph)
        result = self.builder.build_context(fused)
        self.assertIn("depth: 2", result)

    def test_graph_source_chunks_in_citations(self):
        graph = [_make_graph_evidence("e1", source_chunk_ids=["chunk_x", "chunk_y"])]
        fused = _make_fused_context(graph=graph)
        result = self.builder.build_context(fused)
        self.assertIn("chunk_x", result)


class TestConfigOptions(unittest.TestCase):
    """Test configuration toggles."""

    def test_disable_citations(self):
        config = ContextBuilderConfig(include_citations=False)
        builder = ContextBuilder(config=config)
        fused = _make_fused_context(text=[_make_text_evidence("c1")])
        result = builder.build_context(fused)
        self.assertNotIn("## Source Citations", result)

    def test_disable_graph_paths(self):
        config = ContextBuilderConfig(include_graph_paths=False)
        builder = ContextBuilder(config=config)
        graph = [_make_graph_evidence("e1", path_description="A --> B")]
        fused = _make_fused_context(graph=graph)
        result = builder.build_context(fused)
        self.assertNotIn("## Graph Paths", result)

    def test_disable_missing_warning(self):
        config = ContextBuilderConfig(include_missing_warning=False)
        builder = ContextBuilder(config=config)
        fused = _make_fused_context()  # No evidence
        result = builder.build_context(fused)
        self.assertNotIn("Evidence Warning", result)


if __name__ == "__main__":
    unittest.main()
