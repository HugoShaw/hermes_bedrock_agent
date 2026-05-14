"""Tests for graph/normalizer.py — name normalization, deduplication, alias merging.

No real AWS calls.
"""

from __future__ import annotations

import unittest

from hermes_bedrock_agent.graph.normalizer import (
    EntityNormalizer,
    NormalizerConfig,
    build_entity_id,
    merge_aliases,
    normalize_name,
)
from hermes_bedrock_agent.schemas.graph import EntityType, GraphEntity


def _make_entity(name: str, entity_type=EntityType.SYSTEM, **kwargs):
    """Create a test GraphEntity."""
    defaults = {
        "entity_id": f"ent_test_{name.lower()[:8]}",
        "name": name,
        "canonical_name": name.lower(),
        "entity_type": entity_type,
        "source_chunk_ids": ["chunk_001"],
        "confidence": 0.8,
    }
    defaults.update(kwargs)
    return GraphEntity(**defaults)


class TestNormalizeName(unittest.TestCase):
    """Test normalize_name function."""

    def test_lowercase(self):
        self.assertEqual(normalize_name("SystemA"), "systema")

    def test_strip_whitespace(self):
        self.assertEqual(normalize_name("  hello  "), "hello")

    def test_collapse_spaces(self):
        self.assertEqual(normalize_name("multi   space  name"), "multi space name")

    def test_strip_quotes(self):
        self.assertEqual(normalize_name('"QuotedName"'), "quotedname")

    def test_strip_trailing_punctuation(self):
        self.assertEqual(normalize_name("name."), "name")
        self.assertEqual(normalize_name("name,"), "name")
        self.assertEqual(normalize_name("name;"), "name")

    def test_no_lowercase_when_disabled(self):
        config = NormalizerConfig(lowercase_names=False)
        self.assertEqual(normalize_name("SystemA", config=config), "SystemA")

    def test_empty_string(self):
        self.assertEqual(normalize_name(""), "")


class TestBuildEntityId(unittest.TestCase):
    """Test stable entity_id generation."""

    def test_deterministic(self):
        id1 = build_entity_id("system", "systema")
        id2 = build_entity_id("system", "systema")
        self.assertEqual(id1, id2)

    def test_different_types_different_ids(self):
        id1 = build_entity_id("system", "myentity")
        id2 = build_entity_id("module", "myentity")
        self.assertNotEqual(id1, id2)

    def test_prefix(self):
        eid = build_entity_id("system", "test")
        self.assertTrue(eid.startswith("ent_"))

    def test_length(self):
        eid = build_entity_id("system", "test")
        # ent_ + 16 hex chars
        self.assertEqual(len(eid), 20)


class TestMergeAliases(unittest.TestCase):
    """Test alias merging."""

    def test_merge_unique(self):
        result = merge_aliases(["A", "B"], ["C", "D"])
        self.assertEqual(result, ["A", "B", "C", "D"])

    def test_deduplicate(self):
        result = merge_aliases(["A", "B"], ["B", "C"])
        self.assertEqual(result, ["A", "B", "C"])

    def test_case_insensitive_dedup(self):
        result = merge_aliases(["SystemA"], ["systema", "New"])
        # "systema" is same as "SystemA" case-insensitively
        self.assertEqual(len(result), 2)
        self.assertIn("SystemA", result)
        self.assertIn("New", result)

    def test_empty_inputs(self):
        self.assertEqual(merge_aliases([], []), [])

    def test_strips_empty_strings(self):
        result = merge_aliases(["A", ""], ["", "B"])
        self.assertEqual(result, ["A", "B"])


class TestEntityNormalizerSingle(unittest.TestCase):
    """Test normalizing individual entities."""

    def setUp(self):
        self.normalizer = EntityNormalizer()

    def test_normalize_sets_canonical_name(self):
        entity = _make_entity("SystemA")
        result = self.normalizer.normalize_entity(entity)
        self.assertEqual(result.canonical_name, "systema")

    def test_normalize_rebuilds_entity_id(self):
        entity = _make_entity("SystemA")
        result = self.normalizer.normalize_entity(entity)
        expected_id = build_entity_id("system", "systema")
        self.assertEqual(result.entity_id, expected_id)

    def test_normalize_sets_is_normalized(self):
        entity = _make_entity("Test")
        result = self.normalizer.normalize_entity(entity)
        self.assertTrue(result.is_normalized)

    def test_normalize_preserves_aliases(self):
        entity = _make_entity("SystemA", aliases=["SA", "SysA"])
        result = self.normalizer.normalize_entity(entity)
        # Original aliases preserved
        self.assertIn("SA", result.aliases)
        self.assertIn("SysA", result.aliases)


class TestEntityNormalizerDedup(unittest.TestCase):
    """Test entity deduplication (merging same type+canonical_name)."""

    def setUp(self):
        self.normalizer = EntityNormalizer()

    def test_merge_same_canonical_name_and_type(self):
        e1 = _make_entity("SystemA", source_chunk_ids=["chunk_001"])
        e2 = _make_entity("systema", source_chunk_ids=["chunk_002"])
        result = self.normalizer.deduplicate_entities([e1, e2])
        self.assertEqual(len(result), 1)

    def test_merged_entity_has_all_chunk_ids(self):
        e1 = _make_entity("SystemA", source_chunk_ids=["chunk_001"])
        e2 = _make_entity("systema", source_chunk_ids=["chunk_002"])
        result = self.normalizer.deduplicate_entities([e1, e2])
        merged = result[0]
        self.assertIn("chunk_001", merged.source_chunk_ids)
        self.assertIn("chunk_002", merged.source_chunk_ids)

    def test_merged_entity_takes_max_confidence(self):
        e1 = _make_entity("SystemA", confidence=0.7)
        e2 = _make_entity("systema", confidence=0.9)
        result = self.normalizer.deduplicate_entities([e1, e2])
        self.assertEqual(result[0].confidence, 0.9)

    def test_merged_entity_takes_longest_description(self):
        e1 = _make_entity("SystemA", description="Short")
        e2 = _make_entity("systema", description="A much longer description of the system")
        result = self.normalizer.deduplicate_entities([e1, e2])
        self.assertEqual(result[0].description, "A much longer description of the system")

    def test_merged_entity_sums_extraction_count(self):
        e1 = _make_entity("SystemA", extraction_count=3)
        e2 = _make_entity("systema", extraction_count=2)
        result = self.normalizer.deduplicate_entities([e1, e2])
        self.assertEqual(result[0].extraction_count, 5)

    def test_different_types_not_merged(self):
        e1 = _make_entity("Process", entity_type=EntityType.PROCESS)
        e2 = _make_entity("Process", entity_type=EntityType.MODULE)
        result = self.normalizer.deduplicate_entities([e1, e2])
        self.assertEqual(len(result), 2)

    def test_aliases_merged(self):
        e1 = _make_entity("SystemA", aliases=["SA"])
        e2 = _make_entity("systema", aliases=["SysA"])
        result = self.normalizer.deduplicate_entities([e1, e2])
        aliases = result[0].aliases
        self.assertIn("SA", aliases)
        self.assertIn("SysA", aliases)

    def test_no_duplicates_single_entity(self):
        e1 = _make_entity("UniqueEntity")
        result = self.normalizer.deduplicate_entities([e1])
        self.assertEqual(len(result), 1)

    def test_empty_input(self):
        result = self.normalizer.deduplicate_entities([])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
