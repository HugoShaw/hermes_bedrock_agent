"""Tests for the new configs/settings.py module.

Tests pydantic-settings configuration loading, defaults, env var override,
and sub-settings construction.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from hermes_bedrock_agent.configs.settings import (
    AWSSettings,
    AppSettings,
    ChunkingSettings,
    EmbeddingSettings,
    GraphSettings,
    IngestionSettings,
    LLMSettings,
    NeptuneSettings,
    OpenSearchSettings,
    RetrievalSettings,
    S3Settings,
    get_settings,
)


# ---------------------------------------------------------------------------
# Sub-settings unit tests
# ---------------------------------------------------------------------------


class TestAWSSettings:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            s = AWSSettings()
            assert s.region == "ap-northeast-1"

    def test_env_override(self):
        with patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=False):
            s = AWSSettings()
            assert s.region == "us-west-2"


class TestS3Settings:
    def test_defaults(self):
        s = S3Settings()
        assert s.bucket == "s3-hulftchina-rd"
        assert s.prefix == ""

    def test_env_override(self):
        with patch.dict(os.environ, {"S3_BUCKET": "my-bucket", "S3_PREFIX": "docs/"}, clear=False):
            s = S3Settings()
            assert s.bucket == "my-bucket"
            assert s.prefix == "docs/"


class TestNeptuneSettings:
    def test_defaults(self):
        with patch.dict(os.environ, {"NEPTUNE_GRAPH_ID": "", "NEPTUNE_ANALYTICS_GRAPH_ID": ""}, clear=False):
            s = NeptuneSettings()
            assert s.is_configured is False

    def test_configured(self):
        with patch.dict(os.environ, {"NEPTUNE_GRAPH_ID": "g-test123"}, clear=False):
            s = NeptuneSettings()
            assert s.graph_id == "g-test123"
            assert s.is_configured is True


class TestOpenSearchSettings:
    def test_defaults(self):
        s = OpenSearchSettings()
        assert s.index_name == "enterprise-graphrag"
        assert s.use_serverless is True
        assert s.is_configured is False

    def test_configured(self):
        with patch.dict(os.environ, {"OPENSEARCH_ENDPOINT": "https://search.example.com"}, clear=False):
            s = OpenSearchSettings()
            assert s.is_configured is True


class TestEmbeddingSettings:
    def test_defaults(self):
        s = EmbeddingSettings()
        assert s.provider == "bedrock"
        assert s.model_id == "amazon.titan-embed-text-v2:0"
        assert s.dimension == 1024
        assert s.batch_size == 25


class TestLLMSettings:
    def test_defaults(self):
        s = LLMSettings()
        assert s.vision_provider == "bedrock"
        assert s.text_provider == "bedrock"
        assert s.max_tokens == 4096
        assert s.temperature == 0.0


class TestIngestionSettings:
    def test_defaults(self):
        s = IngestionSettings()
        assert ".pdf" in s.supported_extensions
        assert ".py" in s.supported_extensions
        assert s.max_file_size_mb == 50
        assert s.enable_incremental is True


class TestChunkingSettings:
    def test_defaults(self):
        s = ChunkingSettings()
        assert s.max_tokens == 512
        assert s.overlap_tokens == 64
        assert s.strategy == "fixed"

    def test_env_override(self):
        with patch.dict(os.environ, {"CHUNKING_MAX_TOKENS": "256", "CHUNKING_STRATEGY": "semantic"}, clear=False):
            s = ChunkingSettings()
            assert s.max_tokens == 256
            assert s.strategy == "semantic"


class TestGraphSettings:
    def test_defaults(self):
        s = GraphSettings()
        assert s.normalize_entities is True
        assert s.quality_review is True
        assert s.min_confidence == 0.7


class TestRetrievalSettings:
    def test_defaults(self):
        s = RetrievalSettings()
        assert s.text_top_k == 10
        assert s.graph_top_k == 5
        assert s.fusion_strategy == "rrf"
        assert s.rrf_k == 60


# ---------------------------------------------------------------------------
# AppSettings (master config)
# ---------------------------------------------------------------------------


class TestAppSettings:
    def test_create(self):
        s = AppSettings()
        assert s.app_name == "hermes_bedrock_agent"
        assert s.app_version == "0.3.0"
        assert s.dry_run is True

    def test_sub_settings_access(self):
        s = AppSettings()
        assert s.aws.region == "ap-northeast-1"
        assert s.s3.bucket == "s3-hulftchina-rd"
        assert s.embedding.dimension == 1024

    def test_paths(self):
        s = AppSettings()
        assert s.project_root.exists()
        assert (s.project_root / "pyproject.toml").exists()

    def test_dry_run_override(self):
        with patch.dict(os.environ, {"DRY_RUN": "false"}, clear=False):
            s = AppSettings()
            assert s.dry_run is False


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


class TestGetSettings:
    def test_cached(self):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear(self):
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # New instance after clear
        assert s1 is not s2
