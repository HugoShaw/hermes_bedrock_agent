"""Tests for graph/quality_review.py — validation, confidence filtering, rejection rules.

No real AWS calls.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_bedrock_agent.graph.quality_review import (
    GraphQualityReviewer,
    QualityConfig,
    ReviewResult,
    load_graph_schema,
)
from hermes_bedrock_agent.schemas.graph import (
    EntityType,
    EvidenceRecord,
    GraphEntity,
    GraphRelation,
    RelationType,
)


def _make_entity(entity_id="ent_001", confidence=0.8, entity_type=EntityType.SYSTEM, **kwargs):
    defaults = {
        "entity_id": entity_id,
        "name": "TestEntity",
        "canonical_name": "testentity",
        "entity_type": entity_type,
        "source_chunk_ids": ["chunk_001"],
        "confidence": confidence,
    }
    defaults.update(kwargs)
    return GraphEntity(**defaults)


def _make_relation(
    relation_id="rel_001",
    source_entity_id="ent_001",
    target_entity_id="ent_002",
    confidence=0.8,
    source_chunk_id="chunk_001",
    relation_type=RelationType.DEPENDS_ON,
    **kwargs,
):
    defaults = {
        "relation_id": relation_id,
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "relation_type": relation_type,
        "confidence": confidence,
        "source_chunk_id": source_chunk_id,
        "source_chunk_ids": [source_chunk_id] if source_chunk_id else [],
    }
    defaults.update(kwargs)
    return GraphRelation(**defaults)


def _make_evidence(evidence_id="ev_001", relation_id="rel_001", **kwargs):
    defaults = {
        "evidence_id": evidence_id,
        "relation_id": relation_id,
        "source_chunk_id": "chunk_001",
        "document_id": "doc_001",
        "evidence_text": "Supporting text",
    }
    defaults.update(kwargs)
    return EvidenceRecord(**defaults)


class TestQualityConfigFromYaml(unittest.TestCase):
    """Test loading graph schema from YAML."""

    def test_load_existing_config(self):
        schema_path = Path(__file__).parent.parent / "configs" / "graph_schema.yaml"
        if schema_path.exists():
            config = load_graph_schema(schema_path)
            self.assertGreater(len(config.allowed_node_labels), 0)
            self.assertGreater(len(config.allowed_relation_types), 0)
            self.assertEqual(config.min_confidence, 0.5)

    def test_load_nonexistent_uses_defaults(self):
        config = load_graph_schema(Path("/nonexistent/path.yaml"))
        self.assertGreater(len(config.allowed_node_labels), 0)
        self.assertIn("system", config.allowed_node_labels)


class TestEntityValidation(unittest.TestCase):
    """Test entity validation rules."""

    def setUp(self):
        self.reviewer = GraphQualityReviewer(config=QualityConfig(
            allowed_node_labels=["system", "module", "table", "concept"],
            allowed_relation_types=["depends_on", "contains", "calls"],
            min_confidence=0.5,
            pending_min=0.3,
        ))

    def test_valid_entity_accepted(self):
        entity = _make_entity(confidence=0.8)
        issues = self.reviewer.validate_entity(entity)
        self.assertEqual(issues, [])

    def test_unknown_entity_type_rejected(self):
        entity = _make_entity(entity_type=EntityType.UNKNOWN)
        # If "unknown" not in allowed list
        reviewer = GraphQualityReviewer(config=QualityConfig(
            allowed_node_labels=["system", "module"],
            min_confidence=0.5,
            pending_min=0.3,
        ))
        issues = reviewer.validate_entity(entity)
        self.assertTrue(any("entity_type" in i.lower() or "Unknown" in i for i in issues))

    def test_low_confidence_entity_rejected(self):
        entity = _make_entity(confidence=0.1)
        issues = self.reviewer.validate_entity(entity)
        self.assertTrue(any("confidence" in i.lower() or "Confidence" in i for i in issues))

    def test_empty_canonical_name_rejected(self):
        entity = _make_entity(canonical_name="")
        issues = self.reviewer.validate_entity(entity)
        self.assertTrue(any("canonical_name" in i.lower() or "Empty" in i for i in issues))


class TestRelationValidation(unittest.TestCase):
    """Test relation validation rules."""

    def setUp(self):
        self.reviewer = GraphQualityReviewer(config=QualityConfig(
            allowed_node_labels=["system", "module"],
            allowed_relation_types=["depends_on", "contains", "calls"],
            min_confidence=0.5,
            pending_min=0.3,
        ))

    def test_valid_relation_no_issues(self):
        rel = _make_relation()
        issues = self.reviewer.validate_relation(rel)
        self.assertEqual(issues, [])

    def test_missing_source_chunk_id_rejected(self):
        rel = _make_relation(source_chunk_id="")
        issues = self.reviewer.validate_relation(rel)
        self.assertTrue(any("source_chunk_id" in i for i in issues))

    def test_self_loop_rejected(self):
        rel = _make_relation(source_entity_id="ent_001", target_entity_id="ent_001")
        issues = self.reviewer.validate_relation(rel)
        self.assertTrue(any("self-loop" in i.lower() or "Self-loop" in i for i in issues))

    def test_unknown_relation_type_rejected(self):
        rel = _make_relation(relation_type=RelationType.CUSTOM)
        issues = self.reviewer.validate_relation(rel)
        self.assertTrue(any("relation_type" in i.lower() for i in issues))

    def test_low_confidence_below_pending_rejected(self):
        rel = _make_relation(confidence=0.1)
        issues = self.reviewer.validate_relation(rel)
        self.assertTrue(any("confidence" in i.lower() or "Confidence" in i for i in issues))


class TestConfidenceFiltering(unittest.TestCase):
    """Test confidence-based classification."""

    def setUp(self):
        self.reviewer = GraphQualityReviewer(config=QualityConfig(
            allowed_node_labels=[e.value for e in EntityType],
            allowed_relation_types=[r.value for r in RelationType],
            min_confidence=0.5,
            pending_min=0.3,
            pending_max=0.5,
        ))

    def test_high_confidence_accepted(self):
        rel = _make_relation(confidence=0.8)
        accepted, pending, rejected = self.reviewer.filter_by_confidence([rel])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(pending), 0)
        self.assertEqual(len(rejected), 0)

    def test_pending_confidence_pending(self):
        rel = _make_relation(confidence=0.4)
        accepted, pending, rejected = self.reviewer.filter_by_confidence([rel])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(rejected), 0)

    def test_low_confidence_rejected(self):
        rel = _make_relation(confidence=0.1)
        accepted, pending, rejected = self.reviewer.filter_by_confidence([rel])
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(pending), 0)
        self.assertEqual(len(rejected), 1)

    def test_boundary_min_confidence_accepted(self):
        rel = _make_relation(confidence=0.5)
        accepted, pending, rejected = self.reviewer.filter_by_confidence([rel])
        self.assertEqual(len(accepted), 1)


class TestSelfLoopDetection(unittest.TestCase):
    """Test self-loop detection."""

    def setUp(self):
        self.reviewer = GraphQualityReviewer()

    def test_detect_self_loop(self):
        rel = _make_relation(source_entity_id="X", target_entity_id="X")
        loops = self.reviewer.detect_self_loop([rel])
        self.assertEqual(len(loops), 1)

    def test_normal_relation_not_self_loop(self):
        rel = _make_relation(source_entity_id="A", target_entity_id="B")
        loops = self.reviewer.detect_self_loop([rel])
        self.assertEqual(len(loops), 0)


class TestMissingEvidenceDetection(unittest.TestCase):
    """Test missing evidence detection."""

    def setUp(self):
        self.reviewer = GraphQualityReviewer()

    def test_relation_without_evidence(self):
        rel = _make_relation(relation_id="rel_orphan")
        evidence = [_make_evidence(relation_id="rel_other")]
        missing = self.reviewer.detect_missing_evidence([rel], evidence)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].relation_id, "rel_orphan")

    def test_relation_with_evidence(self):
        rel = _make_relation(relation_id="rel_001")
        evidence = [_make_evidence(relation_id="rel_001")]
        missing = self.reviewer.detect_missing_evidence([rel], evidence)
        self.assertEqual(len(missing), 0)


class TestFullReview(unittest.TestCase):
    """Test the full review() pipeline."""

    def setUp(self):
        self.reviewer = GraphQualityReviewer(config=QualityConfig(
            allowed_node_labels=["system", "module", "concept"],
            allowed_relation_types=["depends_on", "contains"],
            min_confidence=0.5,
            pending_min=0.3,
        ))

    def test_review_classifies_entities(self):
        entities = [
            _make_entity("ent_1", confidence=0.8),  # accepted
            _make_entity("ent_2", confidence=0.4),  # pending
            _make_entity("ent_3", confidence=0.1),  # rejected
        ]
        result = self.reviewer.review(entities, [], [])
        self.assertEqual(len(result.accepted_entities), 1)
        self.assertEqual(len(result.pending_entities), 1)
        self.assertEqual(len(result.rejected_entities), 1)

    def test_review_classifies_relations(self):
        relations = [
            _make_relation("rel_1", confidence=0.8),   # accepted
            _make_relation("rel_2", confidence=0.4),   # pending
            _make_relation("rel_3", confidence=0.1),   # rejected (below pending_min)
        ]
        result = self.reviewer.review([], relations, [])
        self.assertEqual(len(result.accepted_relations), 1)
        self.assertEqual(len(result.pending_relations), 1)
        self.assertEqual(len(result.rejected_relations), 1)

    def test_review_rejects_self_loop(self):
        rel = _make_relation("rel_loop", source_entity_id="X", target_entity_id="X", confidence=0.9)
        result = self.reviewer.review([], [rel], [])
        self.assertEqual(len(result.rejected_relations), 1)
        self.assertIn("rel_loop", result.rejection_reasons)

    def test_review_rejects_missing_source_chunk_id(self):
        rel = _make_relation("rel_no_chunk", source_chunk_id="", confidence=0.9)
        result = self.reviewer.review([], [rel], [])
        self.assertEqual(len(result.rejected_relations), 1)

    def test_review_rejects_unknown_relation_type(self):
        rel = _make_relation("rel_custom", relation_type=RelationType.CUSTOM, confidence=0.9)
        result = self.reviewer.review([], [rel], [])
        self.assertEqual(len(result.rejected_relations), 1)

    def test_review_passes_evidence_for_accepted(self):
        rel = _make_relation("rel_good", confidence=0.8)
        ev = _make_evidence("ev_1", relation_id="rel_good")
        result = self.reviewer.review([], [rel], [ev])
        self.assertEqual(len(result.accepted_evidence), 1)

    def test_review_returns_rejection_reasons(self):
        rel = _make_relation("rel_bad", source_chunk_id="", confidence=0.9)
        result = self.reviewer.review([], [rel], [])
        self.assertIn("rel_bad", result.rejection_reasons)
        reasons = result.rejection_reasons["rel_bad"]
        self.assertTrue(any("source_chunk_id" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
