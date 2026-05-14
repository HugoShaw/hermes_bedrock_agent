"""Tests for graph/neptune_loader.py — parameterized queries, inline Cypher, Neptune loading.

All tests use mock Neptune client. No real Neptune calls.
Phase 6.5: validates two modes (load vs export) and label/type mappers.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call

from hermes_bedrock_agent.graph.neptune_loader import (
    _escape_cypher_string,
    _escape_label,
    build_edge_cypher,
    build_edge_query_and_params,
    build_import_cypher,
    build_node_cypher,
    build_node_query_and_params,
    entity_type_to_label,
    load_edges_to_neptune,
    load_nodes_to_neptune,
    load_to_neptune,
    relation_type_to_cypher_type,
    serialize_property_value,
    write_neptune_import_cypher,
)
from hermes_bedrock_agent.schemas.graph import (
    EntityType,
    GraphEntity,
    GraphRelation,
    RelationType,
)


def _make_entity(entity_id="ent_001", **kwargs):
    defaults = {
        "entity_id": entity_id,
        "name": "TestSystem",
        "canonical_name": "testsystem",
        "entity_type": EntityType.SYSTEM,
        "description": "A test system",
        "source_chunk_ids": ["chunk_001", "chunk_002"],
        "confidence": 0.9,
        "acl": ["team-a"],
    }
    defaults.update(kwargs)
    return GraphEntity(**defaults)


def _make_relation(relation_id="rel_001", **kwargs):
    defaults = {
        "relation_id": relation_id,
        "source_entity_id": "ent_001",
        "target_entity_id": "ent_002",
        "relation_type": RelationType.DEPENDS_ON,
        "description": "System depends on module",
        "source_chunk_id": "chunk_001",
        "source_chunk_ids": ["chunk_001"],
        "evidence_id": "ev_001",
        "confidence": 0.85,
        "acl": ["team-a"],
    }
    defaults.update(kwargs)
    return GraphRelation(**defaults)


# ===========================================================================
# Label / Type mappers
# ===========================================================================


class TestEntityTypeToLabel(unittest.TestCase):
    """Test entity_type → PascalCase label mapping."""

    def test_simple_type(self):
        self.assertEqual(entity_type_to_label("module"), "Module")
        self.assertEqual(entity_type_to_label("system"), "System")
        self.assertEqual(entity_type_to_label("table"), "Table")

    def test_compound_type(self):
        self.assertEqual(entity_type_to_label("business_process"), "BusinessProcess")
        self.assertEqual(entity_type_to_label("process_step"), "ProcessStep")
        self.assertEqual(entity_type_to_label("data_source"), "DataSource")

    def test_unknown_type(self):
        self.assertEqual(entity_type_to_label("unknown"), "Unknown")

    def test_already_capitalized(self):
        # Should still work (lowercases first)
        self.assertEqual(entity_type_to_label("Module"), "Module")

    def test_empty_string(self):
        self.assertEqual(entity_type_to_label(""), "Unknown")


class TestRelationTypeToCypherType(unittest.TestCase):
    """Test relation_type → UPPER_SNAKE edge type mapping."""

    def test_simple_types(self):
        self.assertEqual(relation_type_to_cypher_type("belongs_to"), "BELONGS_TO")
        self.assertEqual(relation_type_to_cypher_type("calls"), "CALLS")
        self.assertEqual(relation_type_to_cypher_type("reads"), "READS")

    def test_compound_types(self):
        self.assertEqual(relation_type_to_cypher_type("implemented_by"), "IMPLEMENTED_BY")
        self.assertEqual(relation_type_to_cypher_type("reads_from"), "READS_FROM")
        self.assertEqual(relation_type_to_cypher_type("depends_on"), "DEPENDS_ON")

    def test_already_upper(self):
        self.assertEqual(relation_type_to_cypher_type("BELONGS_TO"), "BELONGS_TO")


# ===========================================================================
# Serialize property value
# ===========================================================================


class TestSerializePropertyValue(unittest.TestCase):
    """Test list/value serialization for Neptune properties."""

    def test_string_passthrough(self):
        self.assertEqual(serialize_property_value("hello"), "hello")

    def test_int_passthrough(self):
        self.assertEqual(serialize_property_value(42), 42)

    def test_float_passthrough(self):
        self.assertEqual(serialize_property_value(0.85), 0.85)

    def test_bool_passthrough(self):
        self.assertEqual(serialize_property_value(True), True)
        self.assertEqual(serialize_property_value(False), False)

    def test_list_to_comma_string(self):
        result = serialize_property_value(["a", "b", "c"])
        self.assertEqual(result, "a, b, c")

    def test_empty_list(self):
        self.assertEqual(serialize_property_value([]), "")

    def test_list_with_mixed_types(self):
        result = serialize_property_value(["chunk_001", 42, True])
        self.assertEqual(result, "chunk_001, 42, True")


# ===========================================================================
# Parameterized queries (LOAD MODE)
# ===========================================================================


class TestBuildNodeQueryAndParams(unittest.TestCase):
    """Test parameterized node MERGE query generation."""

    def test_returns_query_and_params_tuple(self):
        entity = _make_entity()
        result = build_node_query_and_params(entity)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_query_uses_dollar_params(self):
        entity = _make_entity()
        query, params = build_node_query_and_params(entity)
        self.assertIn("$entity_id", query)
        self.assertIn("$props", query)
        # No inline entity values in query
        self.assertNotIn("ent_001", query)
        self.assertNotIn("TestSystem", query)
        self.assertNotIn("testsystem", query)

    def test_query_has_merge_and_set(self):
        entity = _make_entity()
        query, _ = build_node_query_and_params(entity)
        self.assertIn("MERGE", query)
        self.assertIn("SET n +=", query)

    def test_label_is_pascal_case(self):
        entity = _make_entity(entity_type=EntityType.SYSTEM)
        query, _ = build_node_query_and_params(entity)
        self.assertIn("`System`", query)

    def test_params_contain_entity_id(self):
        entity = _make_entity(entity_id="ent_xyz")
        _, params = build_node_query_and_params(entity)
        self.assertEqual(params["entity_id"], "ent_xyz")

    def test_params_contain_props_dict(self):
        entity = _make_entity()
        _, params = build_node_query_and_params(entity)
        self.assertIn("props", params)
        props = params["props"]
        self.assertEqual(props["entity_id"], "ent_001")
        self.assertEqual(props["canonical_name"], "testsystem")
        self.assertEqual(props["confidence"], 0.9)

    def test_params_lists_serialized(self):
        entity = _make_entity(source_chunk_ids=["c1", "c2", "c3"])
        _, params = build_node_query_and_params(entity)
        # Lists become comma-separated strings for Neptune
        self.assertEqual(params["props"]["source_chunk_ids"], "c1, c2, c3")

    def test_no_inline_interpolation_for_special_chars(self):
        # Injection attempt — should NOT appear in query text
        entity = _make_entity(
            entity_id="ent_001",
            description="'); DROP ALL; //",
        )
        query, params = build_node_query_and_params(entity)
        # The malicious string is only in params, never in query
        self.assertNotIn("DROP ALL", query)
        self.assertIn("DROP ALL", params["props"]["description"])

    def test_query_returns_id(self):
        entity = _make_entity()
        query, _ = build_node_query_and_params(entity)
        self.assertIn("RETURN", query)


class TestBuildEdgeQueryAndParams(unittest.TestCase):
    """Test parameterized edge MERGE query generation."""

    def test_returns_query_and_params_tuple(self):
        rel = _make_relation()
        result = build_edge_query_and_params(rel)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_query_uses_dollar_params(self):
        rel = _make_relation()
        query, params = build_edge_query_and_params(rel)
        self.assertIn("$from_id", query)
        self.assertIn("$to_id", query)
        self.assertIn("$props", query)
        # No inline relation values in query
        self.assertNotIn("ent_001", query)
        self.assertNotIn("ent_002", query)

    def test_query_has_match_merge_set(self):
        rel = _make_relation()
        query, _ = build_edge_query_and_params(rel)
        self.assertIn("MATCH", query)
        self.assertIn("MERGE", query)
        self.assertIn("SET r +=", query)

    def test_edge_type_is_upper_snake(self):
        rel = _make_relation(relation_type=RelationType.DEPENDS_ON)
        query, _ = build_edge_query_and_params(rel)
        self.assertIn("`DEPENDS_ON`", query)

    def test_params_contain_from_to_ids(self):
        rel = _make_relation(source_entity_id="ent_A", target_entity_id="ent_B")
        _, params = build_edge_query_and_params(rel)
        self.assertEqual(params["from_id"], "ent_A")
        self.assertEqual(params["to_id"], "ent_B")

    def test_params_contain_props(self):
        rel = _make_relation(confidence=0.85, evidence_id="ev_xyz")
        _, params = build_edge_query_and_params(rel)
        props = params["props"]
        self.assertEqual(props["confidence"], 0.85)
        self.assertEqual(props["evidence_id"], "ev_xyz")
        self.assertEqual(props["source_chunk_id"], "chunk_001")

    def test_no_inline_interpolation_for_special_chars(self):
        rel = _make_relation(description="'); MATCH (x) DELETE x; //")
        query, params = build_edge_query_and_params(rel)
        self.assertNotIn("DELETE", query)
        self.assertIn("DELETE", params["props"]["description"])


# ===========================================================================
# Load mode — uses parameterized queries
# ===========================================================================


class TestLoadToNeptuneParameterized(unittest.TestCase):
    """Test load_to_neptune uses parameterized queries (not inline Cypher)."""

    def test_calls_execute_query_with_parameters_kwarg(self):
        mock_client = MagicMock()
        mock_client.execute_query.return_value = None
        entities = [_make_entity()]
        load_to_neptune(mock_client, entities, [])
        # Must be called with parameters= keyword argument
        args, kwargs = mock_client.execute_query.call_args
        self.assertIn("parameters", kwargs)
        self.assertIsInstance(kwargs["parameters"], dict)

    def test_query_text_has_no_entity_values(self):
        mock_client = MagicMock()
        mock_client.execute_query.return_value = None
        entity = _make_entity(
            entity_id="ent_secret",
            description="sensitive data here",
        )
        load_to_neptune(mock_client, [entity], [])
        query_arg = mock_client.execute_query.call_args[0][0]
        # Query text must not contain entity values
        self.assertNotIn("ent_secret", query_arg)
        self.assertNotIn("sensitive data", query_arg)

    def test_dry_run_no_calls(self):
        mock_client = MagicMock()
        entities = [_make_entity()]
        relations = [_make_relation()]
        result = load_to_neptune(mock_client, entities, relations, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["nodes_loaded"], 0)
        self.assertEqual(result["edges_loaded"], 0)
        mock_client.execute_query.assert_not_called()

    def test_loads_nodes_and_edges(self):
        mock_client = MagicMock()
        mock_client.execute_query.return_value = None
        entities = [_make_entity("e1"), _make_entity("e2")]
        relations = [_make_relation("r1")]
        result = load_to_neptune(mock_client, entities, relations)
        self.assertEqual(result["nodes_loaded"], 2)
        self.assertEqual(result["edges_loaded"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(mock_client.execute_query.call_count, 3)

    def test_handles_node_error(self):
        mock_client = MagicMock()
        mock_client.execute_query.side_effect = Exception("Neptune error")
        entities = [_make_entity()]
        result = load_to_neptune(mock_client, entities, [])
        self.assertEqual(result["nodes_loaded"], 0)
        self.assertEqual(result["errors"], 1)

    def test_handles_edge_error(self):
        mock_client = MagicMock()
        mock_client.execute_query.side_effect = [None, Exception("Edge error")]
        entities = [_make_entity()]
        relations = [_make_relation()]
        result = load_to_neptune(mock_client, entities, relations)
        self.assertEqual(result["nodes_loaded"], 1)
        self.assertEqual(result["edges_loaded"], 0)
        self.assertEqual(result["errors"], 1)

    def test_batch_size_respected(self):
        mock_client = MagicMock()
        mock_client.execute_query.return_value = None
        entities = [_make_entity(f"e_{i}") for i in range(10)]
        result = load_to_neptune(mock_client, entities, [], batch_size=3)
        self.assertEqual(result["nodes_loaded"], 10)


class TestLoadNodesToNeptune(unittest.TestCase):
    """Test load_nodes_to_neptune independently."""

    def test_returns_loaded_and_errors(self):
        mock_client = MagicMock()
        mock_client.execute_query.return_value = None
        loaded, errors = load_nodes_to_neptune(mock_client, [_make_entity()])
        self.assertEqual(loaded, 1)
        self.assertEqual(errors, 0)

    def test_error_counted(self):
        mock_client = MagicMock()
        mock_client.execute_query.side_effect = Exception("fail")
        loaded, errors = load_nodes_to_neptune(mock_client, [_make_entity()])
        self.assertEqual(loaded, 0)
        self.assertEqual(errors, 1)


class TestLoadEdgesToNeptune(unittest.TestCase):
    """Test load_edges_to_neptune independently."""

    def test_returns_loaded_and_errors(self):
        mock_client = MagicMock()
        mock_client.execute_query.return_value = None
        loaded, errors = load_edges_to_neptune(mock_client, [_make_relation()])
        self.assertEqual(loaded, 1)
        self.assertEqual(errors, 0)


# ===========================================================================
# EXPORT MODE: inline escaped Cypher (for human review / dry-run artifacts)
# ===========================================================================


class TestCypherStringEscaping(unittest.TestCase):
    """Test Cypher string escaping for export mode."""

    def test_escape_single_quote(self):
        result = _escape_cypher_string("it's a test")
        self.assertEqual(result, "it\\'s a test")
        self.assertNotIn("'", result.replace("\\'", ""))

    def test_escape_backslash(self):
        result = _escape_cypher_string("path\\to\\file")
        self.assertEqual(result, "path\\\\to\\\\file")

    def test_escape_newline(self):
        result = _escape_cypher_string("line1\nline2")
        self.assertIn("\\n", result)
        self.assertNotIn("\n", result)

    def test_escape_tab(self):
        result = _escape_cypher_string("col1\tcol2")
        self.assertIn("\\t", result)

    def test_normal_string_unchanged(self):
        result = _escape_cypher_string("normal text 123")
        self.assertEqual(result, "normal text 123")

    def test_japanese_characters(self):
        result = _escape_cypher_string("システム管理")
        self.assertEqual(result, "システム管理")

    def test_injection_attempt(self):
        malicious = "'); DROP ALL; //"
        result = _escape_cypher_string(malicious)
        self.assertIn("\\'", result)
        # After removing escaped quotes, no bare ' remains
        stripped = result.replace("\\'", "")
        self.assertNotIn("'", stripped)


class TestLabelEscaping(unittest.TestCase):
    """Test label sanitization for inline Cypher."""

    def test_normal_label(self):
        self.assertEqual(_escape_label("system"), "system")

    def test_special_chars_replaced(self):
        self.assertEqual(_escape_label("my-label"), "my_label")
        self.assertEqual(_escape_label("my.label"), "my_label")

    def test_starts_with_number(self):
        result = _escape_label("123abc")
        self.assertTrue(result[0].isalpha())

    def test_empty_string(self):
        self.assertEqual(_escape_label(""), "Unknown")


class TestBuildNodeCypher(unittest.TestCase):
    """Test inline node MERGE statement generation (export mode)."""

    def test_basic_node_cypher(self):
        entity = _make_entity()
        cypher = build_node_cypher(entity)
        self.assertIn("MERGE", cypher)
        self.assertIn("SET n +=", cypher)
        self.assertIn("entity_id:", cypher)
        self.assertIn("ent_001", cypher)

    def test_node_label_pascal_case(self):
        entity = _make_entity(entity_type=EntityType.MODULE)
        cypher = build_node_cypher(entity)
        self.assertIn("`Module`", cypher)

    def test_node_includes_confidence(self):
        entity = _make_entity(confidence=0.9)
        cypher = build_node_cypher(entity)
        self.assertIn("confidence:", cypher)
        self.assertIn("0.9", cypher)

    def test_node_includes_acl(self):
        entity = _make_entity(acl=["team-a", "team-b"])
        cypher = build_node_cypher(entity)
        self.assertIn("acl:", cypher)
        self.assertIn("team-a", cypher)

    def test_node_escapes_special_chars(self):
        entity = _make_entity(description="It's a 'special' system")
        cypher = build_node_cypher(entity)
        self.assertIn("\\'", cypher)


class TestBuildEdgeCypher(unittest.TestCase):
    """Test inline edge MERGE statement generation (export mode)."""

    def test_basic_edge_cypher(self):
        rel = _make_relation()
        cypher = build_edge_cypher(rel)
        self.assertIn("MATCH", cypher)
        self.assertIn("MERGE", cypher)
        self.assertIn("SET r +=", cypher)

    def test_edge_relation_type_upper(self):
        rel = _make_relation(relation_type=RelationType.CALLS)
        cypher = build_edge_cypher(rel)
        self.assertIn("`CALLS`", cypher)

    def test_edge_includes_source_chunk_id(self):
        rel = _make_relation(source_chunk_id="chunk_xyz")
        cypher = build_edge_cypher(rel)
        self.assertIn("chunk_xyz", cypher)

    def test_edge_includes_evidence_id(self):
        rel = _make_relation(evidence_id="ev_abc")
        cypher = build_edge_cypher(rel)
        self.assertIn("ev_abc", cypher)

    def test_edge_includes_confidence(self):
        rel = _make_relation(confidence=0.85)
        cypher = build_edge_cypher(rel)
        self.assertIn("0.85", cypher)

    def test_edge_references_from_to_ids(self):
        rel = _make_relation(source_entity_id="ent_A", target_entity_id="ent_B")
        cypher = build_edge_cypher(rel)
        self.assertIn("ent_A", cypher)
        self.assertIn("ent_B", cypher)


class TestBuildImportCypher(unittest.TestCase):
    """Test full inline import script generation."""

    def test_import_contains_nodes_and_edges(self):
        entities = [_make_entity("ent_1"), _make_entity("ent_2")]
        relations = [_make_relation("rel_1")]
        cypher = build_import_cypher(entities, relations)
        self.assertIn("Nodes (2)", cypher)
        self.assertIn("Edges (1)", cypher)

    def test_import_with_header_comment(self):
        cypher = build_import_cypher([], [], header_comment="Test import")
        self.assertIn("// Test import", cypher)

    def test_empty_import(self):
        cypher = build_import_cypher([], [])
        self.assertIn("Nodes (0)", cypher)
        self.assertIn("Edges (0)", cypher)


class TestWriteNeptuneImportCypher(unittest.TestCase):
    """Test writing inline Cypher to file (export mode)."""

    def test_write_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "import.cypher"
            entities = [_make_entity()]
            relations = [_make_relation()]
            count = write_neptune_import_cypher(entities, relations, path)
            self.assertEqual(count, 2)  # 1 node + 1 edge
            self.assertTrue(path.exists())
            content = path.read_text()
            self.assertIn("MERGE", content)

    def test_dry_run_writes_count_but_not_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "import.cypher"
            count = write_neptune_import_cypher([_make_entity()], [], path, dry_run=True)
            # dry_run still reports the count of WOULD-BE statements
            self.assertEqual(count, 1)
            self.assertFalse(path.exists())

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "dir" / "import.cypher"
            write_neptune_import_cypher([_make_entity()], [], path)
            self.assertTrue(path.exists())

    def test_dry_run_still_generates_inline_cypher_format(self):
        """Verify export mode produces inline Cypher (not parameterized)."""
        entity = _make_entity()
        cypher = build_node_cypher(entity)
        # Inline mode has actual values in the Cypher text
        self.assertIn("ent_001", cypher)
        self.assertIn("testsystem", cypher)
        # NOT parameterized ($entity_id)
        self.assertNotIn("$entity_id", cypher)
        self.assertNotIn("$props", cypher)


# ===========================================================================
# Cross-mode safety: no unescaped inline values in load mode
# ===========================================================================


class TestNoInlineValuesInLoadMode(unittest.TestCase):
    """Ensure load mode never interpolates user data into query strings."""

    def test_node_query_safe_from_injection(self):
        """Even with malicious entity values, query text stays clean."""
        entity = _make_entity(
            entity_id="x'); MATCH (n) DETACH DELETE n; //",
            name="<script>alert('xss')</script>",
            description="'); DROP ALL; //",
        )
        query, params = build_node_query_and_params(entity)
        # Query must not contain any of these dangerous strings
        self.assertNotIn("DETACH DELETE", query)
        self.assertNotIn("DROP ALL", query)
        self.assertNotIn("<script>", query)
        # They should be safely in params
        self.assertIn("DETACH DELETE", params["entity_id"])
        self.assertIn("DROP ALL", params["props"]["description"])

    def test_edge_query_safe_from_injection(self):
        """Even with malicious relation values, query text stays clean."""
        rel = _make_relation(
            source_entity_id="x'); MATCH (n) DELETE n; //",
            target_entity_id="y'); RETURN null; //",
            description="malicious text",
        )
        query, params = build_edge_query_and_params(rel)
        self.assertNotIn("DELETE", query)
        self.assertNotIn("RETURN null", query)
        # Values safe in params
        self.assertIn("DELETE", params["from_id"])


if __name__ == "__main__":
    unittest.main()
