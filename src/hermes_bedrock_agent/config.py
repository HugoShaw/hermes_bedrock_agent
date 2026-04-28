from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

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
class Settings:
    aws_region: str
    knowledge_bases: list[KBEntry]
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

        1. Multi-KB  (preferred) — comma-separated ``name:id`` pairs:
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
        neptune_graph_id = os.getenv("NEPTUNE_ANALYTICS_GRAPH_ID") or None

        return cls(
            aws_region=region,
            knowledge_bases=kbs,
            graphrag_db_path=graphrag_db_path,
            graphrag_s3_bucket=graphrag_s3_bucket,
            graphrag_embedding_model=graphrag_embedding_model,
            neptune_graph_id=neptune_graph_id,
        )
