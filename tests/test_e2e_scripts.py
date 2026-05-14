"""Tests for scripts/query_demo.py and scripts/export_mermaid.py — mock-only."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestExportMermaid:
    """Test export_mermaid.py helper functions."""

    def _get_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "export_mermaid",
            Path(__file__).resolve().parent.parent / "scripts" / "export_mermaid.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_filter_by_center_bfs(self):
        module = self._get_module()

        entities = [
            {"entity_id": "e1", "name": "PaymentService", "canonical_name": "paymentservice"},
            {"entity_id": "e2", "name": "OrderService", "canonical_name": "orderservice"},
            {"entity_id": "e3", "name": "UserService", "canonical_name": "userservice"},
            {"entity_id": "e4", "name": "Isolated", "canonical_name": "isolated"},
        ]
        relations = [
            {"source_entity_id": "e1", "target_entity_id": "e2", "relation_type": "calls"},
            {"source_entity_id": "e2", "target_entity_id": "e3", "relation_type": "calls"},
        ]

        # BFS depth=1 from PaymentService should find e1, e2
        filtered_e, filtered_r = module._filter_by_center(entities, relations, "Payment", 1)
        filtered_ids = {e["entity_id"] for e in filtered_e}
        assert "e1" in filtered_ids
        assert "e2" in filtered_ids
        assert "e4" not in filtered_ids  # Isolated

        # BFS depth=2 from PaymentService should find e1, e2, e3
        filtered_e2, _ = module._filter_by_center(entities, relations, "Payment", 2)
        filtered_ids2 = {e["entity_id"] for e in filtered_e2}
        assert "e3" in filtered_ids2

    def test_filter_no_match_returns_limited(self):
        module = self._get_module()
        entities = [{"entity_id": "e1", "name": "X", "canonical_name": "x"}]
        relations = []
        filtered_e, filtered_r = module._filter_by_center(entities, relations, "NOMATCH", 2)
        # Should return all entities (limited to 30) when no center found
        assert len(filtered_e) == 1

    def test_build_from_artifacts(self):
        module = self._get_module()
        tmpdir = tempfile.mkdtemp()
        artifact_dir = Path(tmpdir) / "test_run" / "artifacts"
        artifact_dir.mkdir(parents=True)

        # Write mock entities/relations
        entities = [
            {"entity_id": "e1", "name": "仕訳基礎", "entity_type": "table", "description": "Journal base table"},
            {"entity_id": "e2", "name": "付款申請", "entity_type": "business_process", "description": "Payment request"},
        ]
        relations = [
            {"relation_id": "r1", "source_entity_id": "e1", "target_entity_id": "e2",
             "relation_type": "used_by", "description": "Referenced by"},
        ]

        with open(artifact_dir / "entities.jsonl", "w") as f:
            for e in entities:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(artifact_dir / "relations.jsonl", "w") as f:
            for r in relations:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # Build args mock
        args = MagicMock()
        args.artifact_base = Path(tmpdir)
        args.run_id = "test_run"
        args.center_entity = None
        args.entity_types = None
        args.depth = 2
        args.max_nodes = 30

        subgraph = module._build_from_artifacts(args)
        assert len(subgraph.nodes) == 2
        assert len(subgraph.edges) == 1
        assert subgraph.nodes[0].label == "仕訳基礎"

    def test_load_jsonl(self):
        module = self._get_module()
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / "test.jsonl"
        with open(path, "w") as f:
            f.write('{"id": "1"}\n')
            f.write('{"id": "2"}\n')

        records = module._load_jsonl(path)
        assert len(records) == 2
        assert records[0]["id"] == "1"
