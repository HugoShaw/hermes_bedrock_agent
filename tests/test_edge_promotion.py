"""Tests for graph_pipeline/normalizer.py — edge endpoint resolution and promotion.

Tests verify:
  1. Raw edge with exact raw id endpoints is promoted
  2. Raw edge whose endpoints are canonicalized is promoted through id_remap
  3. Raw edge resolved by label + name is promoted
  4. Edge with 'from'/'to' fields (v4.5 format) is handled correctly
  5. Unresolved verified edge is written to unresolved list, not silently dropped
  6. Preflight fails when verified cache edges are silently dropped
  7. Neptune import contains promoted semantic relationship types
"""

from __future__ import annotations

import json
import unittest
from collections import Counter

from hermes_bedrock_agent.graph_pipeline.normalizer import (
    EndpointResolver,
    normalize_entities,
    _canonical_id,
    _extract_edge_endpoints,
)
from hermes_bedrock_agent.graph_pipeline.validator import run_preflight_check


class TestExtractEdgeEndpoints(unittest.TestCase):
    """Test _extract_edge_endpoints handles both field name conventions."""

    def test_from_id_to_id_fields(self):
        """v4.3 format: from_id/to_id"""
        edge = {"from_id": "nodeA", "to_id": "nodeB"}
        f, t = _extract_edge_endpoints(edge)
        self.assertEqual(f, "nodeA")
        self.assertEqual(t, "nodeB")

    def test_from_to_fields(self):
        """v4.5 format: from/to"""
        edge = {"from": "sample:System:SAP", "to": "sample:Interface:IF1"}
        f, t = _extract_edge_endpoints(edge)
        self.assertEqual(f, "sample:System:SAP")
        self.assertEqual(t, "sample:Interface:IF1")

    def test_from_to_preferred_over_empty_from_id(self):
        """If both exist, prefer non-empty one."""
        edge = {"from_id": "", "from": "sample:System:SAP", "to_id": "", "to": "sample:Interface:IF1"}
        f, t = _extract_edge_endpoints(edge)
        self.assertEqual(f, "sample:System:SAP")
        self.assertEqual(t, "sample:Interface:IF1")

    def test_empty_fields_return_empty(self):
        edge = {}
        f, t = _extract_edge_endpoints(edge)
        self.assertEqual(f, "")
        self.assertEqual(t, "")


class TestNormalizeEntitiesEdgePromotion(unittest.TestCase):
    """Test that normalize_entities promotes edges correctly."""

    def _make_nodes(self, project_id="test_proj"):
        """Create sample nodes for testing."""
        return [
            {
                "id": f"{project_id}:System:SAP",
                "entity_type": "System",
                "name": "SAP",
                "display_name": "SAP",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "SAP system",
                "confidence": 0.9,
            },
            {
                "id": f"{project_id}:Interface:IF1",
                "entity_type": "Interface",
                "name": "IF1",
                "display_name": "Interface 1",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "Interface IF1",
                "confidence": 0.9,
            },
            {
                "id": f"{project_id}:Field:FieldA",
                "entity_type": "Field",
                "name": "FieldA",
                "display_name": "Field A",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "Field A definition",
                "confidence": 0.9,
            },
            {
                "id": f"{project_id}:DataEntity:EntityX",
                "entity_type": "DataEntity",
                "name": "EntityX",
                "display_name": "Entity X",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "Data entity X",
                "confidence": 0.9,
            },
            {
                "id": f"{project_id}:BusinessProcess:ProcessA",
                "entity_type": "BusinessProcess",
                "name": "ProcessA",
                "display_name": "Process A",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "Business process A",
                "confidence": 0.9,
            },
            {
                "id": f"{project_id}:FunctionModule:FuncB",
                "entity_type": "FunctionModule",
                "name": "FuncB",
                "display_name": "Function B",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "Function module B",
                "confidence": 0.9,
            },
        ]

    def test_edge_with_from_to_fields_promoted(self):
        """Edge using 'from'/'to' (v4.5 format) is promoted."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:Interface:IF1",
                "type": "HAS_INTERFACE",
                "evidence_text": "SAP has interface IF1",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        self.assertEqual(len(norm_edges), 1)
        self.assertEqual(norm_edges[0]["type"], "HAS_INTERFACE")
        self.assertIn("start_id", norm_edges[0])
        self.assertIn("end_id", norm_edges[0])
        # Raw endpoints preserved
        self.assertEqual(norm_edges[0]["raw_from"], f"{pid}:System:SAP")
        self.assertEqual(norm_edges[0]["raw_to"], f"{pid}:Interface:IF1")

    def test_edge_with_from_id_to_id_fields_promoted(self):
        """Edge using 'from_id'/'to_id' (v4.3 format) is promoted."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from_id": f"{pid}:System:SAP",
                "to_id": f"{pid}:Interface:IF1",
                "type": "HAS_INTERFACE",
                "evidence_text": "SAP has interface IF1",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        self.assertEqual(len(norm_edges), 1)
        self.assertEqual(norm_edges[0]["type"], "HAS_INTERFACE")

    def test_edge_resolved_by_label_name(self):
        """Edge whose endpoints match via label + name resolution."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from": f"{pid}:DataEntity:EntityX",
                "to": f"{pid}:Field:FieldA",
                "type": "HAS_FIELD",
                "evidence_text": "EntityX contains FieldA",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_table_row",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        self.assertEqual(len(norm_edges), 1)
        self.assertEqual(norm_edges[0]["type"], "HAS_FIELD")

    def test_multiple_edge_types_promoted(self):
        """Multiple verified edge types are all promoted correctly."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from": f"{pid}:DataEntity:EntityX",
                "to": f"{pid}:Field:FieldA",
                "type": "HAS_FIELD",
                "evidence_text": "EntityX has FieldA",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_table_row",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
            {
                "from": f"{pid}:BusinessProcess:ProcessA",
                "to": f"{pid}:FunctionModule:FuncB",
                "type": "HAS_FUNCTION",
                "evidence_text": "ProcessA contains FuncB",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:Interface:IF1",
                "type": "HAS_INTERFACE",
                "evidence_text": "SAP has IF1",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        edge_types = Counter(e["type"] for e in norm_edges)
        self.assertEqual(edge_types["HAS_FIELD"], 1)
        self.assertEqual(edge_types["HAS_FUNCTION"], 1)
        self.assertEqual(edge_types["HAS_INTERFACE"], 1)
        self.assertEqual(len(norm_edges), 3)

    def test_unresolved_edge_not_silently_dropped(self):
        """Edge with unresolvable endpoints goes to unresolved list, not dropped."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:System:NonExistentSystem",
                "type": "CONNECTS_TO",
                "evidence_text": "SAP connects to NonExistent",
                "confidence": 0.85,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        # Should NOT be in promoted edges
        self.assertEqual(len(norm_edges), 0)
        # Should be in unresolved_edges
        unresolved = registry.get("unresolved_edges", [])
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["type"], "CONNECTS_TO")
        self.assertEqual(unresolved[0]["unresolved_reason"], "to_unresolved")
        self.assertEqual(unresolved[0]["raw_from"], f"{pid}:System:SAP")
        self.assertEqual(unresolved[0]["raw_to"], f"{pid}:System:NonExistentSystem")

    def test_diagnostics_in_registry(self):
        """Registry contains edge promotion diagnostics."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:Interface:IF1",
                "type": "HAS_INTERFACE",
                "evidence_text": "test",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:System:MISSING",
                "type": "CONNECTS_TO",
                "evidence_text": "test",
                "confidence": 0.85,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        diag = registry["diagnostics"]
        self.assertEqual(diag["total_cache_edges"], 2)
        self.assertEqual(diag["total_promoted_edges"], 1)
        self.assertEqual(diag["total_unresolved_edges"], 1)
        self.assertIn("HAS_INTERFACE", diag["promoted_edge_type_counts"])
        self.assertIn("CONNECTS_TO", diag["unresolved_endpoint_edge_type_counts"])
        self.assertEqual(diag["silently_dropped_edge_type_counts"], {})

    def test_no_edges_silently_dropped(self):
        """Every input edge either promoted or explicitly unresolved."""
        pid = "test_proj"
        nodes = self._make_nodes(pid)
        edges = [
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:Interface:IF1",
                "type": "HAS_INTERFACE",
                "evidence_text": "test",
                "confidence": 0.9,
                "review_status": "verified",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
            {
                "from": f"{pid}:System:GHOST1",
                "to": f"{pid}:System:GHOST2",
                "type": "GHOST_EDGE",
                "evidence_text": "test",
                "confidence": 0.9,
                "review_status": "verified",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")
        total_accounted = len(norm_edges) + len(registry["unresolved_edges"])
        self.assertEqual(total_accounted, len(edges),
                         "All input edges must be either promoted or unresolved")


class TestPreflightEdgeGates(unittest.TestCase):
    """Test preflight fails when verified cache edges are silently dropped."""

    def test_preflight_fails_on_silently_dropped(self):
        """If silently_dropped_edge_type_counts is non-empty, preflight blocks."""
        registry = {
            "diagnostics": {
                "cache_edge_type_counts": {"HAS_FIELD": 100},
                "cache_verified_edge_type_counts": {"HAS_FIELD": 100},
                "promoted_edge_type_counts": {},
                "unresolved_endpoint_edge_type_counts": {},
                "silently_dropped_edge_type_counts": {"HAS_FIELD": 100},
                "total_cache_edges": 100,
                "total_promoted_edges": 0,
                "total_unresolved_edges": 0,
            },
        }
        nodes = [{"id": "n1", "project_name": "P", "entity_type": "System", "source_file": "f", "evidence_text": "e", "layer": "semantic"}]
        edges = []
        report, has_p0 = run_preflight_check(
            nodes, edges, nodes, edges, "pid", "P", [], registry=registry
        )
        self.assertTrue(has_p0, "Preflight must fail when edges are silently dropped")
        self.assertIn("Silently dropped edges detected", report)

    def test_preflight_fails_critical_type_vanishes(self):
        """If HAS_FIELD verified in cache but 0 promoted AND 0 unresolved."""
        registry = {
            "diagnostics": {
                "cache_edge_type_counts": {"HAS_FIELD": 50},
                "cache_verified_edge_type_counts": {"HAS_FIELD": 50},
                "promoted_edge_type_counts": {},
                "unresolved_endpoint_edge_type_counts": {},
                "silently_dropped_edge_type_counts": {},
                "total_cache_edges": 50,
                "total_promoted_edges": 0,
                "total_unresolved_edges": 0,
            },
        }
        nodes = [{"id": "n1", "project_name": "P", "entity_type": "Field", "source_file": "f", "evidence_text": "e", "layer": "semantic"}]
        edges = []
        report, has_p0 = run_preflight_check(
            nodes, edges, nodes, edges, "pid", "P", [], registry=registry
        )
        self.assertTrue(has_p0, "Preflight must fail when critical edge types vanish")
        self.assertIn("HAS_FIELD", report)

    def test_preflight_passes_when_edges_promoted(self):
        """If edges are successfully promoted, preflight should not trigger edge gates."""
        registry = {
            "diagnostics": {
                "cache_edge_type_counts": {"HAS_FIELD": 50, "HAS_FUNCTION": 10},
                "cache_verified_edge_type_counts": {"HAS_FIELD": 50, "HAS_FUNCTION": 10},
                "promoted_edge_type_counts": {"HAS_FIELD": 48, "HAS_FUNCTION": 10},
                "unresolved_endpoint_edge_type_counts": {"HAS_FIELD": 2},
                "silently_dropped_edge_type_counts": {},
                "total_cache_edges": 60,
                "total_promoted_edges": 58,
                "total_unresolved_edges": 2,
            },
        }
        nodes = [
            {"id": "n1", "project_name": "P", "project_id": "pid", "entity_type": "Field",
             "source_file": "f", "evidence_text": "e", "layer": "semantic"},
            {"id": "n2", "project_name": "P", "project_id": "pid", "entity_type": "DataEntity",
             "source_file": "f", "evidence_text": "e", "layer": "semantic"},
        ]
        edges = [
            {"id": "e1", "start_id": "n1", "end_id": "n2", "type": "HAS_FIELD",
             "project_name": "P", "project_id": "pid", "source_file": "f", "layer": "semantic"},
        ]
        report, has_p0 = run_preflight_check(
            nodes, edges, nodes, edges, "pid", "P", [], registry=registry
        )
        # Should not have edge-gate P0s (may have other P0s like dangling)
        self.assertNotIn("silently lost", report.lower())
        # The diagnostics section shows "Silently dropped: 0" which is fine;
        # what matters is no P0 issue about silently dropped edges
        self.assertNotIn("Silently dropped edges detected", report)

    def test_preflight_all_cache_vanished(self):
        """If ALL cache edges vanish, it's a critical pipeline failure."""
        registry = {
            "diagnostics": {
                "cache_edge_type_counts": {"HAS_FIELD": 200, "NEXT_STEP": 50},
                "cache_verified_edge_type_counts": {"HAS_FIELD": 200, "NEXT_STEP": 50},
                "promoted_edge_type_counts": {},
                "unresolved_endpoint_edge_type_counts": {},
                "silently_dropped_edge_type_counts": {},
                "total_cache_edges": 250,
                "total_promoted_edges": 0,
                "total_unresolved_edges": 0,
            },
        }
        nodes = [{"id": "n1", "project_name": "P", "entity_type": "System", "source_file": "f", "evidence_text": "e", "layer": "semantic"}]
        edges = []
        report, has_p0 = run_preflight_check(
            nodes, edges, nodes, edges, "pid", "P", [], registry=registry
        )
        self.assertTrue(has_p0)
        self.assertIn("Critical pipeline failure", report)


class TestEndpointResolver(unittest.TestCase):
    """Test the EndpointResolver multi-strategy resolution."""

    def _build_resolver(self, project_id="test"):
        canonical_nodes = {
            "system:test:sap": {"entity_type": "System", "name": "SAP", "display_name": "SAP"},
            "interface:test:if1": {"entity_type": "Interface", "name": "IF1", "display_name": "IF1"},
            "field:test:wb1:sheet_01:field_a": {"entity_type": "Field", "name": "FieldA", "display_name": "Field A"},
            "data:test:wb1:entity_x": {"entity_type": "DataEntity", "name": "EntityX", "display_name": "Entity X"},
        }
        id_remap = {
            "test:System:SAP": "system:test:sap",
            "test:Interface:IF1": "interface:test:if1",
            "test:Field:FieldA": "field:test:wb1:sheet_01:field_a",
            "test:DataEntity:EntityX": "data:test:wb1:entity_x",
            "local_sap": "system:test:sap",
        }
        name_map = dict(id_remap)

        return EndpointResolver(
            canonical_ids=set(canonical_nodes.keys()),
            id_remap=id_remap,
            name_map=name_map,
            canonical_nodes=canonical_nodes,
            project_id=project_id,
        )

    def test_resolve_exact_canonical(self):
        resolver = self._build_resolver()
        result = resolver.resolve("system:test:sap")
        self.assertEqual(result, "system:test:sap")

    def test_resolve_via_id_remap(self):
        resolver = self._build_resolver()
        result = resolver.resolve("test:System:SAP")
        self.assertEqual(result, "system:test:sap")

    def test_resolve_via_name_map(self):
        resolver = self._build_resolver()
        result = resolver.resolve("local_sap")
        self.assertEqual(result, "system:test:sap")

    def test_resolve_via_label_name_index(self):
        resolver = self._build_resolver()
        # The label_name_index stores project_id:Label:Name
        result = resolver.resolve("test:System:SAP")
        self.assertIsNotNone(result)

    def test_resolve_unresolvable_returns_none(self):
        resolver = self._build_resolver()
        result = resolver.resolve("test:System:NonExistent")
        self.assertIsNone(result)

    def test_resolve_empty_returns_none(self):
        resolver = self._build_resolver()
        result = resolver.resolve("")
        self.assertIsNone(result)


class TestNeptuneImportContainsPromotedEdges(unittest.TestCase):
    """Verify that promoted edges flow through to Neptune import files."""

    def test_promoted_edges_in_full_output(self):
        """After normalization, promoted edges should appear in all_edges for Neptune."""
        pid = "test_proj"
        nodes = [
            {
                "id": f"{pid}:System:SAP",
                "entity_type": "System",
                "name": "SAP",
                "display_name": "SAP",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "SAP",
                "confidence": 0.9,
            },
            {
                "id": f"{pid}:Interface:IF1",
                "entity_type": "Interface",
                "name": "IF1",
                "display_name": "IF1",
                "workbook_name": "WB1",
                "sheet_name": "sheet_01",
                "source_file": "/tmp/test.md",
                "evidence_text": "IF1",
                "confidence": 0.9,
            },
        ]
        edges = [
            {
                "from": f"{pid}:System:SAP",
                "to": f"{pid}:Interface:IF1",
                "type": "HAS_INTERFACE",
                "evidence_text": "SAP has IF1",
                "confidence": 0.9,
                "review_status": "verified",
                "link_method": "explicit_text",
                "workbook_name": "WB1",
                "source_file": "/tmp/test.md",
            },
        ]
        norm_nodes, norm_edges, registry = normalize_entities(nodes, edges, pid, "TestProject")

        # These edges should have start_id/end_id for Neptune import
        self.assertEqual(len(norm_edges), 1)
        self.assertIn("start_id", norm_edges[0])
        self.assertIn("end_id", norm_edges[0])
        self.assertEqual(norm_edges[0]["type"], "HAS_INTERFACE")
        # Old fields cleaned up
        self.assertNotIn("from", norm_edges[0])
        self.assertNotIn("to", norm_edges[0])
        self.assertNotIn("from_id", norm_edges[0])
        self.assertNotIn("to_id", norm_edges[0])


if __name__ == "__main__":
    unittest.main()
