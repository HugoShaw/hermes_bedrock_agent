"""Unified configuration for hermes_bedrock_agent.

Loads settings from .env and configs/ YAML files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env from the project root, regardless of where the command is run from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class KBEntry:
    """A single knowledge base entry: an ID and an optional human-readable label."""

    kb_id: str
    label: str = ""

    @property
    def display_name(self) -> str:
        return self.label if self.label else self.kb_id


@dataclass(frozen=True)
class S3Config:
    """S3 source configuration for document ETL."""

    bucket: str = ""
    prefix: str = ""
    region: str = "ap-northeast-1"

    @classmethod
    def from_env(cls) -> "S3Config":
        return cls(
            bucket=os.getenv("S3_BUCKET", "s3-hulftchina-rd"),
            prefix=os.getenv("S3_PREFIX", ""),
            region=os.getenv("AWS_REGION", "ap-northeast-1"),
        )


@dataclass(frozen=True)
class NeptuneConfig:
    """Neptune Analytics configuration."""

    endpoint: str = ""
    graph_id: str = ""
    region: str = "ap-northeast-1"

    @classmethod
    def from_env(cls) -> "NeptuneConfig":
        return cls(
            endpoint=os.getenv("NEPTUNE_ENDPOINT", ""),
            graph_id=os.getenv("NEPTUNE_GRAPH_ID", "") or os.getenv("NEPTUNE_ANALYTICS_GRAPH_ID", ""),
            region=os.getenv("AWS_REGION", "ap-northeast-1"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.graph_id)


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding provider configuration."""

    provider: str = "bedrock"  # bedrock | openai
    model_id: str = "amazon.titan-embed-text-v2:0"
    dimension: int = 1024

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(
            provider=os.getenv("EMBEDDING_PROVIDER", "bedrock"),
            model_id=os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
            dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
        )


@dataclass(frozen=True)
class LLMConfig:
    """LLM configuration for parsing and extraction."""

    vision_provider: str = "bedrock"  # bedrock | openai | local
    vision_model_id: str = "anthropic.claude-sonnet-4-20250514"
    text_provider: str = "bedrock"
    text_model_id: str = "anthropic.claude-sonnet-4-20250514"

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            vision_provider=os.getenv("VISION_LLM_PROVIDER", "bedrock"),
            vision_model_id=os.getenv("VISION_LLM_MODEL_ID", "anthropic.claude-sonnet-4-20250514"),
            text_provider=os.getenv("TEXT_LLM_PROVIDER", "bedrock"),
            text_model_id=os.getenv("TEXT_LLM_MODEL_ID", "anthropic.claude-sonnet-4-20250514"),
        )


@dataclass(frozen=True)
class Settings:
    """Master settings object."""

    aws_region: str
    knowledge_bases: list[KBEntry]
    s3: S3Config = field(default_factory=S3Config.from_env)
    neptune: NeptuneConfig = field(default_factory=NeptuneConfig.from_env)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig.from_env)
    llm: LLMConfig = field(default_factory=LLMConfig.from_env)
    dry_run: bool = True

    # Legacy compat fields
    graphrag_db_path: Path = field(default_factory=lambda: Path.home() / ".hermes_bedrock_agent" / "graphrag.db")
    graphrag_s3_bucket: str = "s3-hulftchina-rd"
    graphrag_embedding_model: str = "amazon.titan-embed-text-v2:0"
    neptune_graph_id: str | None = None

    # --- back-compat: single-KB access -----------------------------------------

    @property
    def bedrock_knowledge_base_id(self) -> str:
        """Return the first KB id (legacy single-KB accessor)."""
        if not self.knowledge_bases:
            raise ValueError("No knowledge bases configured.")
        return self.knowledge_bases[0].kb_id

    # ---------------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> Settings:
        """Build Settings from environment variables.

        Supports two formats:

        1. Multi-KB  (preferred) -- comma-separated ``name:id`` pairs:
               BEDROCK_KNOWLEDGE_BASES=docs:KB001,sales:KB002,support:KB003

        2. Legacy single-KB:
               BEDROCK_KNOWLEDGE_BASE_ID=KB001

        If both are set, BEDROCK_KNOWLEDGE_BASES takes priority.
        """
        region = os.getenv("AWS_REGION", "ap-northeast-1")
        kbs: list[KBEntry] = []

        # --- multi-KB env var --------------------------------------------------
        multi_raw = os.getenv("BEDROCK_KNOWLEDGE_BASES", "").strip()
        if multi_raw:
            for token in multi_raw.split(","):
                token = token.strip()
                if not token:
                    continue
                if ":" in token:
                    label, kb_id = token.split(":", 1)
                    kbs.append(KBEntry(kb_id=kb_id.strip(), label=label.strip()))
                else:
                    # bare ID, no label
                    kbs.append(KBEntry(kb_id=token))

        # --- legacy single-KB env var -----------------------------------------
        if not kbs:
            single = os.getenv("BEDROCK_KNOWLEDGE_BASE_ID", "").strip()
            if single:
                label = os.getenv("BEDROCK_KNOWLEDGE_BASE_LABEL", "")
                kbs.append(KBEntry(kb_id=single, label=label))

        if not kbs:
            raise ValueError(
                "No knowledge bases configured. "
                "Set BEDROCK_KNOWLEDGE_BASES (e.g. 'docs:KB001,sales:KB002') "
                f"or BEDROCK_KNOWLEDGE_BASE_ID in {PROJECT_ROOT / '.env'}."
            )

        graphrag_db_path = Path(
            os.getenv("GRAPHRAG_DB_PATH", str(Path.home() / ".hermes_bedrock_agent" / "graphrag.db"))
        )
        graphrag_s3_bucket = os.getenv("GRAPHRAG_S3_BUCKET", "s3-hulftchina-rd")
        graphrag_embedding_model = os.getenv("GRAPHRAG_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
        neptune_graph_id = os.getenv("NEPTUNE_ANALYTICS_GRAPH_ID") or os.getenv("NEPTUNE_GRAPH_ID") or None

        dry_run = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")

        return cls(
            aws_region=region,
            knowledge_bases=kbs,
            s3=S3Config.from_env(),
            neptune=NeptuneConfig.from_env(),
            embedding=EmbeddingConfig.from_env(),
            llm=LLMConfig.from_env(),
            dry_run=dry_run,
            graphrag_db_path=graphrag_db_path,
            graphrag_s3_bucket=graphrag_s3_bucket,
            graphrag_embedding_model=graphrag_embedding_model,
            neptune_graph_id=neptune_graph_id,
        )
