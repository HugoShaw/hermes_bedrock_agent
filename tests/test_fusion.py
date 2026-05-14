"""Tests for retrieval/fusion.py — evidence merging and deduplication.

No real AWS/OpenSearch/Neptune calls.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from hermes_bedrock_agent.retrieval.fusion import (
    FusionConfig,
    FusionStrategy,
    fuse_evidence,
    _deduplicate_text_evidence,
    _deduplicate_graph_evidence,
)
from hermes_bedrock_agent.schemas.retrieval import (
    GraphEvidence,
    RetrievalSource,
    TextEvidence,
)


def _make_text_evidence(chunk_id: str, score: float = 0.8, **kwargs) -> TextEvidence:
    defaults = {
        "evidence_id": f"te_{chunk_id}",
        "chunk_id": chunk_id,
        "document_id": f"doc_{chunk_id}",
        "content": f"Content for {chunk_id}",
        "source_uri": f"s3://bucket/{chunk_id}.pdf",
        "score": score,
        "rank": 0,
    }
    defaults.update(kwargs)
    return TextEvidence(**defaults)


def _make_graph_evidence(
    entity_id: str = "ent_001", score: float = 0.7, **kwargs
) -> GraphEvidence:
    defaults = {
        "evidence_id": f"ge_{entity_id}",
        "entity_id": entity_id,
        "content": f"Entity {entity_id} description",
        "source_chunk_ids": ["c1", "c2"],
        "score": score,
        "rank": 0,
    }
    defaults.update(kwargs)
    return GraphEvidence(**defaults)


class TestFuseEvidence(unittest.TestCase):
    """Test main fusion function."""

    def test_basic_fusion(self):
        text = [_make_text_evidence("c1")]
        graph = [_make_graph_evidence("e1")]
        result = fuse_evidence(text, graph, query="test query")
        self.assertEqual(result.query, "test query")
        self.assertEqual(len(result.text_evidence), 1)
        self.assertEqual(len(result.graph_evidence), 1)
        self.assertEqual(result.total_evidence_count, 2)

    def test_empty_inputs(self):
        result = fuse_evidence([], [], query="empty")
        self.assertEqual(result.total_evidence_count, 0)
        self.assertEqual(result.text_evidence, [])
        self.assertEqual(result.graph_evidence, [])

    def test_kb_evidence_merged_into_text(self):
        text = [_make_text_evidence("c1")]
        kb = [_make_text_evidence("kb1", source=RetrievalSource.BEDROCK_KB)]
        result = fuse_evidence(text, [], kb_evidence=kb)
        # KB evidence added to text_evidence
        self.assertEqual(len(result.text_evidence), 2)

    def test_strategy_rrf(self):
        config = FusionConfig(strategy=FusionStrategy.RRF)
        text = [_make_text_evidence("c1", 0.8), _make_text_evidence("c2", 0.6)]
        result = fuse_evidence(text, [], config=config)
        self.assertEqual(result.fusion_strategy, "rrf")

    def test_strategy_weighted(self):
        config = FusionConfig(strategy=FusionStrategy.WEIGHTED)
        text = [_make_text_evidence("c1", 0.8)]
        graph = [_make_graph_evidence("e1", 0.9)]
        result = fuse_evidence(text, graph, config=config)
        self.assertEqual(result.fusion_strategy, "weighted")
        # Weighted: text score * 0.6
        self.assertAlmostEqual(result.text_evidence[0].score, 0.48, places=2)
        # Weighted: graph score * 0.4
        self.assertAlmostEqual(result.graph_evidence[0].score, 0.36, places=2)

    def test_max_evidence_limit(self):
        config = FusionConfig(max_text_evidence=2, max_graph_evidence=1)
        text = [_make_text_evidence(f"c{i}") for i in range(5)]
        graph = [_make_graph_evidence(f"e{i}") for i in range(5)]
        result = fuse_evidence(text, graph, config=config)
        self.assertEqual(len(result.text_evidence), 2)
        self.assertEqual(len(result.graph_evidence), 1)

    def test_ranks_updated(self):
        text = [_make_text_evidence("c1"), _make_text_evidence("c2")]
        result = fuse_evidence(text, [])
        self.assertEqual(result.text_evidence[0].rank, 0)
        self.assertEqual(result.text_evidence[1].rank, 1)

    def test_token_estimate_computed(self):
        text = [_make_text_evidence("c1")]  # "Content for c1" = 14 chars
        result = fuse_evidence(text, [])
        self.assertGreater(result.total_token_estimate, 0)


class TestDeduplicateTextEvidence(unittest.TestCase):
    """Test text evidence deduplication."""

    def test_dedup_same_chunk_id(self):
        ev1 = _make_text_evidence("c1", 0.8)
        ev2 = _make_text_evidence("c1", 0.9)  # Same chunk_id, higher score
        result = _deduplicate_text_evidence([ev1, ev2])
        self.assertEqual(len(result), 1)
        # Keeps higher score
        self.assertAlmostEqual(result[0].score, 0.9)

    def test_different_chunk_ids_kept(self):
        ev1 = _make_text_evidence("c1")
        ev2 = _make_text_evidence("c2")
        result = _deduplicate_text_evidence([ev1, ev2])
        self.assertEqual(len(result), 2)

    def test_dedup_by_source_uri_and_page(self):
        # No chunk_id, same source_uri + page
        ev1 = _make_text_evidence("", source_uri="s3://b/f.pdf", page=3, score=0.5)
        ev2 = _make_text_evidence("", source_uri="s3://b/f.pdf", page=3, score=0.7)
        result = _deduplicate_text_evidence([ev1, ev2])
        self.assertEqual(len(result), 1)

    def test_sorted_by_score(self):
        evidence = [
            _make_text_evidence("c1", 0.3),
            _make_text_evidence("c2", 0.9),
            _make_text_evidence("c3", 0.6),
        ]
        result = _deduplicate_text_evidence(evidence)
        scores = [e.score for e in result]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestDeduplicateGraphEvidence(unittest.TestCase):
    """Test graph evidence deduplication."""

    def test_dedup_same_entity_id(self):
        ev1 = _make_graph_evidence("e1", 0.8)
        ev2 = _make_graph_evidence("e1", 0.9)
        result = _deduplicate_graph_evidence([ev1, ev2])
        self.assertEqual(len(result), 1)

    def test_different_entities_kept(self):
        ev1 = _make_graph_evidence("e1")
        ev2 = _make_graph_evidence("e2")
        result = _deduplicate_graph_evidence([ev1, ev2])
        self.assertEqual(len(result), 2)

    def test_preserves_graph_paths(self):
        """Graph paths with unique descriptions are preserved."""
        ev1 = _make_graph_evidence("e1", path_description="A --calls--> B")
        ev2 = _make_graph_evidence("e1", path_description="A --reads--> C")
        result = _deduplicate_graph_evidence([ev1, ev2])
        # Both paths preserved (different descriptions)
        self.assertEqual(len(result), 2)

    def test_dedup_same_path_description(self):
        ev1 = _make_graph_evidence("e1", path_description="A --calls--> B")
        ev2 = _make_graph_evidence("e2", path_description="A --calls--> B")
        result = _deduplicate_graph_evidence([ev1, ev2])
        self.assertEqual(len(result), 1)


class TestFusionWithDeduplication(unittest.TestCase):
    """Integration: fusion deduplicates across sources."""

    def test_same_chunk_from_text_and_kb(self):
        text = [_make_text_evidence("c1", 0.8)]
        kb = [_make_text_evidence("c1", 0.6, source=RetrievalSource.BEDROCK_KB)]
        result = fuse_evidence(text, [], kb_evidence=kb)
        # Deduplicated: only one entry for c1
        self.assertEqual(len(result.text_evidence), 1)

    def test_graph_paths_preserved_in_fusion(self):
        graph = [
            _make_graph_evidence("e1", path_description="A --calls--> B"),
            _make_graph_evidence("e2", path_description="B --reads--> C"),
        ]
        result = fuse_evidence([], graph)
        self.assertEqual(len(result.graph_evidence), 2)

    def test_no_dedup_when_disabled(self):
        config = FusionConfig(deduplicate=False)
        ev1 = _make_text_evidence("c1", 0.8)
        ev2 = _make_text_evidence("c1", 0.6)
        result = fuse_evidence([ev1, ev2], [], config=config)
        self.assertEqual(len(result.text_evidence), 2)


if __name__ == "__main__":
    unittest.main()
