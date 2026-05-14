"""Tests for knowledge_store/ — JSONL I/O and artifact management."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from hermes_bedrock_agent.knowledge_store.artifact_store import (
    ArtifactStore,
    ArtifactStoreConfig,
    ArtifactType,
)
from hermes_bedrock_agent.knowledge_store.jsonl_store import (
    append_jsonl,
    count_jsonl,
    ensure_parent_dir,
    iter_jsonl,
    read_jsonl,
    write_jsonl,
)
from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceType
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType


# ---- Test model ----

class SampleModel(BaseModel):
    id: str
    name: str
    score: float = 0.0


# ---- jsonl_store tests ----


class TestWriteJsonl:
    def test_write_pydantic_models(self, tmp_path):
        """Write Pydantic models to JSONL."""
        records = [
            SampleModel(id="a", name="Alice", score=0.9),
            SampleModel(id="b", name="Bob", score=0.8),
        ]
        path = tmp_path / "test.jsonl"
        count = write_jsonl(records, path)

        assert count == 2
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert '"Alice"' in lines[0]

    def test_write_dicts(self, tmp_path):
        """Write plain dicts to JSONL."""
        records = [{"x": 1, "y": "hello"}, {"x": 2, "y": "world"}]
        path = tmp_path / "dicts.jsonl"
        count = write_jsonl(records, path)

        assert count == 2
        loaded = read_jsonl(path)
        assert loaded[0]["x"] == 1
        assert loaded[1]["y"] == "world"

    def test_write_dry_run(self, tmp_path):
        """Dry run does not create file."""
        records = [SampleModel(id="c", name="Charlie")]
        path = tmp_path / "dry.jsonl"
        count = write_jsonl(records, path, dry_run=True)

        assert count == 1
        assert not path.exists()

    def test_write_utf8(self, tmp_path):
        """UTF-8 characters preserved."""
        records = [{"name": "日本語テスト", "desc": "中文内容"}]
        path = tmp_path / "utf8.jsonl"
        write_jsonl(records, path)

        loaded = read_jsonl(path)
        assert loaded[0]["name"] == "日本語テスト"
        assert loaded[0]["desc"] == "中文内容"

    def test_write_creates_parent_dirs(self, tmp_path):
        """Parent directories are created automatically."""
        path = tmp_path / "deep" / "nested" / "dir" / "file.jsonl"
        write_jsonl([{"a": 1}], path)
        assert path.exists()

    def test_write_strips_image_base64_by_default(self, tmp_path):
        """image_base64 is excluded by default."""
        vb = VisualBlock(
            visual_id="vis_001",
            document_id="doc_001",
            page=1,
            image_base64="iVBORw0KGgoAAAANSUhEUg==",
            image_format="png",
            visual_type=VisualType.DIAGRAM,
            visual_summary="Test diagram",
        )
        path = tmp_path / "vblocks.jsonl"
        write_jsonl([vb], path, persist_inline_image_base64=False)

        loaded = read_jsonl(path)
        assert "image_base64" not in loaded[0]
        assert loaded[0]["visual_id"] == "vis_001"

    def test_write_keeps_image_base64_when_configured(self, tmp_path):
        """image_base64 is kept when persist_inline_image_base64=True."""
        vb = VisualBlock(
            visual_id="vis_002",
            document_id="doc_002",
            page=1,
            image_base64="AAAA==",
            image_format="png",
        )
        path = tmp_path / "vblocks_full.jsonl"
        write_jsonl([vb], path, persist_inline_image_base64=True)

        loaded = read_jsonl(path)
        assert loaded[0]["image_base64"] == "AAAA=="


class TestAppendJsonl:
    def test_append_creates_file(self, tmp_path):
        """Append creates file if not exists."""
        path = tmp_path / "append.jsonl"
        append_jsonl([{"x": 1}], path)
        assert path.exists()
        assert count_jsonl(path) == 1

    def test_append_adds_records(self, tmp_path):
        """Append adds to existing file."""
        path = tmp_path / "append2.jsonl"
        write_jsonl([{"x": 1}], path)
        append_jsonl([{"x": 2}, {"x": 3}], path)

        loaded = read_jsonl(path)
        assert len(loaded) == 3
        assert loaded[2]["x"] == 3

    def test_append_dry_run(self, tmp_path):
        """Append dry run does not modify file."""
        path = tmp_path / "append_dry.jsonl"
        write_jsonl([{"x": 1}], path)
        append_jsonl([{"x": 2}], path, dry_run=True)

        assert count_jsonl(path) == 1


class TestReadJsonl:
    def test_read_empty_file(self, tmp_path):
        """Read empty file returns empty list."""
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert read_jsonl(path) == []

    def test_read_nonexistent_file(self, tmp_path):
        """Read nonexistent file returns empty list."""
        assert read_jsonl(tmp_path / "nope.jsonl") == []

    def test_read_with_model(self, tmp_path):
        """Read with Pydantic model validation."""
        records = [
            SampleModel(id="x", name="Xavier", score=0.5),
            SampleModel(id="y", name="Yuki", score=0.7),
        ]
        path = tmp_path / "models.jsonl"
        write_jsonl(records, path)

        loaded = read_jsonl(path, model=SampleModel)
        assert len(loaded) == 2
        assert isinstance(loaded[0], SampleModel)
        assert loaded[0].name == "Xavier"
        assert loaded[1].score == 0.7

    def test_read_skips_malformed_lines(self, tmp_path):
        """Malformed lines are skipped with warning."""
        path = tmp_path / "bad.jsonl"
        path.write_text('{"id": "good", "name": "ok"}\nNOT JSON\n{"id": "also_good", "name": "yes"}\n')

        loaded = read_jsonl(path)
        assert len(loaded) == 2


class TestIterJsonl:
    def test_iter_basic(self, tmp_path):
        """Iterate over records lazily."""
        path = tmp_path / "iter.jsonl"
        write_jsonl([{"i": n} for n in range(10)], path)

        items = list(iter_jsonl(path))
        assert len(items) == 10
        assert items[5]["i"] == 5

    def test_iter_with_model(self, tmp_path):
        """Iterate with model validation."""
        records = [SampleModel(id=str(i), name=f"name_{i}") for i in range(5)]
        path = tmp_path / "iter_model.jsonl"
        write_jsonl(records, path)

        items = list(iter_jsonl(path, model=SampleModel))
        assert all(isinstance(it, SampleModel) for it in items)

    def test_iter_nonexistent(self, tmp_path):
        """Iterate nonexistent file yields nothing."""
        items = list(iter_jsonl(tmp_path / "nope.jsonl"))
        assert items == []


class TestCountJsonl:
    def test_count(self, tmp_path):
        """Count records in file."""
        path = tmp_path / "count.jsonl"
        write_jsonl([{"x": i} for i in range(7)], path)
        assert count_jsonl(path) == 7

    def test_count_empty(self, tmp_path):
        """Count empty file = 0."""
        path = tmp_path / "empty.jsonl"
        path.write_text("\n\n")
        assert count_jsonl(path) == 0

    def test_count_nonexistent(self, tmp_path):
        """Count nonexistent file = 0."""
        assert count_jsonl(tmp_path / "nope.jsonl") == 0


class TestEnsureParentDir:
    def test_creates_dirs(self, tmp_path):
        """Creates nested parent directories."""
        p = ensure_parent_dir(tmp_path / "a" / "b" / "c" / "file.txt")
        assert p.parent.exists()


# ---- artifact_store tests ----


class TestArtifactStore:
    def test_init_creates_dirs(self, tmp_path):
        """Init creates all required directories."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="test_run_001")

        assert store.processed_dir.exists()
        assert store.artifacts_dir.exists()
        assert store.registry_dir.exists()
        assert store.run_id == "test_run_001"

    def test_get_path_run(self, tmp_path):
        """Get artifact path within run directory."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_123")
        path = store.get_path(ArtifactType.CHUNKS)

        assert path == tmp_path / "data" / "processed" / "run_123" / "chunks.jsonl"

    def test_get_path_consolidated(self, tmp_path):
        """Get artifact path in consolidated directory."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_123")
        path = store.get_path(ArtifactType.ENTITIES, use_run=False)

        assert path == tmp_path / "data" / "artifacts" / "entities.jsonl"

    def test_get_path_string(self, tmp_path):
        """Get path by string name."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_x")
        path = store.get_path("custom_output.jsonl")
        assert path.name == "custom_output.jsonl"

    def test_exists(self, tmp_path):
        """Check artifact existence."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_e")
        assert store.exists(ArtifactType.CHUNKS) is False

        # Create the file
        chunks_path = store.get_path(ArtifactType.CHUNKS)
        chunks_path.write_text('{"test": true}\n')
        assert store.exists(ArtifactType.CHUNKS) is True

    def test_artifact_size(self, tmp_path):
        """Get artifact file size."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_s")
        assert store.artifact_size(ArtifactType.CHUNKS) == 0

        path = store.get_path(ArtifactType.CHUNKS)
        path.write_text("x" * 100)
        assert store.artifact_size(ArtifactType.CHUNKS) == 100

    def test_list_run_artifacts(self, tmp_path):
        """List artifacts in current run."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_l")
        store.get_path(ArtifactType.DOCUMENTS).write_text("{}\n")
        store.get_path(ArtifactType.CHUNKS).write_text("{}\n")

        artifacts = store.list_run_artifacts()
        assert "documents.jsonl" in artifacts
        assert "chunks.jsonl" in artifacts

    def test_list_runs(self, tmp_path):
        """List available runs."""
        base = tmp_path / "data"
        ArtifactStore(base_dir=base, run_id="20240101_120000")
        ArtifactStore(base_dir=base, run_id="20240102_120000")
        ArtifactStore(base_dir=base, run_id="20240103_120000")

        store = ArtifactStore(base_dir=base, run_id="latest")
        runs = store.list_runs()
        assert len(runs) == 4  # includes 'latest'
        assert runs[0] == "latest"  # sorted reverse

    def test_get_registry_path(self, tmp_path):
        """Get registry file path."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_r")
        path = store.get_registry_path()
        assert path == tmp_path / "data" / "registry" / "document_registry.jsonl"

    def test_persist_inline_image_base64_config(self, tmp_path):
        """Config controls image_base64 persistence."""
        config = ArtifactStoreConfig(
            base_dir=tmp_path / "data",
            persist_inline_image_base64=False,
        )
        store = ArtifactStore(config=config, run_id="run_img")
        assert store.persist_inline_image_base64 is False

    def test_summary(self, tmp_path):
        """Summary returns artifact status."""
        store = ArtifactStore(base_dir=tmp_path / "data", run_id="run_sum")
        store.get_path(ArtifactType.CHUNKS).write_text('{"x":1}\n')

        summary = store.summary()
        assert summary["run_id"] == "run_sum"
        assert summary["artifacts"]["chunks.jsonl"]["exists"] is True
        assert summary["artifacts"]["entities.jsonl"]["exists"] is False

    def test_no_run_id_mode(self, tmp_path):
        """Disable run_id-based organization."""
        config = ArtifactStoreConfig(base_dir=tmp_path / "data", use_run_id=False)
        store = ArtifactStore(config=config, run_id="ignored")
        path = store.get_path(ArtifactType.CHUNKS)
        assert "ignored" not in str(path)
        assert path == tmp_path / "data" / "processed" / "chunks.jsonl"


class TestArtifactType:
    def test_all_types_defined(self):
        """All expected artifact types are defined."""
        expected = [
            "documents.jsonl", "normalized_documents.jsonl", "visual_blocks.jsonl",
            "chunks.jsonl", "embeddings.jsonl",
            "raw_entities.jsonl", "raw_relations.jsonl", "raw_evidence.jsonl",
            "entities.jsonl", "relations.jsonl", "evidence.jsonl",
            "opensearch_bulk.jsonl", "neptune_import.cypher",
        ]
        actual = [a.value for a in ArtifactType]
        for name in expected:
            assert name in actual, f"Missing ArtifactType: {name}"
