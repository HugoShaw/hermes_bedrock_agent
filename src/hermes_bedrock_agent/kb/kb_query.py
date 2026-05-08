"""High-level KB query functions used by CLI and scripts."""
from __future__ import annotations

from hermes_bedrock_agent.config import Settings
from hermes_bedrock_agent.kb.bedrock_kb_client import KBResult, MultiKBClient


def query_all_kbs(
    query: str,
    top_k: int = 5,
    merge_strategy: str = "score",
    kb_ids: list[str] | None = None,
    settings: Settings | None = None,
) -> list[KBResult]:
    """Convenience function to query KBs from scripts."""
    if settings is None:
        settings = Settings.from_env()
    client = MultiKBClient(settings, kb_ids=kb_ids)
    return client.retrieve(query, number_of_results=top_k, merge_strategy=merge_strategy)
