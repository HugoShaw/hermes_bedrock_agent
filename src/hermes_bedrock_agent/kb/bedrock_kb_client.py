"""Bedrock Knowledge Base clients - single and multi-KB support."""
from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from hermes_bedrock_agent.config import KBEntry, Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level single-KB retrieve
# ---------------------------------------------------------------------------

class BedrockKBClient:
    """Client for a *single* Bedrock Knowledge Base (kept for back-compat)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = boto3.client(
            "bedrock-agent-runtime",
            region_name=settings.aws_region,
        )

    def retrieve(self, query: str, number_of_results: int = 5) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("Query must not be empty.")
        if number_of_results < 1 or number_of_results > 20:
            raise ValueError("number_of_results must be between 1 and 20.")

        kb_id = self.settings.bedrock_knowledge_base_id
        return _retrieve_one(self.client, kb_id, query, number_of_results)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class KBResult:
    """A single retrieved chunk, enriched with source KB info."""

    text: str
    score: float
    metadata: dict[str, Any]
    location: dict[str, Any]
    kb_id: str
    kb_label: str

    @property
    def display_source(self) -> str:
        return self.kb_label if self.kb_label else self.kb_id


# ---------------------------------------------------------------------------
# Multi-KB client
# ---------------------------------------------------------------------------

class MultiKBClient:
    """Query multiple Bedrock Knowledge Bases in parallel and merge results."""

    def __init__(
        self,
        settings: Settings,
        kb_ids: list[str] | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.settings = settings
        self._boto_client = boto3.client(
            "bedrock-agent-runtime",
            region_name=settings.aws_region,
        )

        all_kbs = settings.knowledge_bases
        if kb_ids:
            id_set = set(kb_ids)
            self._kbs: list[KBEntry] = [kb for kb in all_kbs if kb.kb_id in id_set]
            missing = id_set - {kb.kb_id for kb in self._kbs}
            if missing:
                raise ValueError(
                    f"KB ID(s) {missing} not found in settings. "
                    f"Configured KBs: {[kb.kb_id for kb in all_kbs]}"
                )
        else:
            self._kbs = list(all_kbs)

        self._max_workers = max_workers or len(self._kbs) or 1

    def retrieve(
        self,
        query: str,
        number_of_results: int = 5,
        merge_strategy: str = "score",
        deduplicate: bool = True,
    ) -> list[KBResult]:
        """Query all configured KBs and return merged, ranked results."""
        if not query.strip():
            raise ValueError("Query must not be empty.")
        if number_of_results < 1 or number_of_results > 20:
            raise ValueError("number_of_results must be between 1 and 20.")
        if not self._kbs:
            raise RuntimeError("No knowledge bases configured.")

        raw_per_kb: dict[str, list[KBResult]] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._fetch_one, kb, query, number_of_results): kb
                for kb in self._kbs
            }
            for future in concurrent.futures.as_completed(futures):
                kb = futures[future]
                try:
                    raw_per_kb[kb.kb_id] = future.result()
                except Exception as exc:
                    logger.warning("KB %s failed: %s", kb.display_name, exc)
                    raw_per_kb[kb.kb_id] = []

        merged = self._merge(raw_per_kb, merge_strategy)
        if deduplicate:
            merged = self._deduplicate(merged)
        return merged

    def retrieve_from(
        self,
        kb_id: str,
        query: str,
        number_of_results: int = 5,
    ) -> list[KBResult]:
        """Query a *single* KB by ID."""
        entry = next((kb for kb in self._kbs if kb.kb_id == kb_id), None)
        if entry is None:
            raise ValueError(
                f"KB {kb_id!r} not in client's KB list: "
                f"{[kb.kb_id for kb in self._kbs]}"
            )
        return self._fetch_one(entry, query, number_of_results)

    def _fetch_one(
        self, kb: KBEntry, query: str, number_of_results: int
    ) -> list[KBResult]:
        raw = _retrieve_one(self._boto_client, kb.kb_id, query, number_of_results)
        results: list[KBResult] = []
        for row in raw.get("retrievalResults", []):
            content = row.get("content", {})
            results.append(
                KBResult(
                    text=content.get("text", ""),
                    score=float(row.get("score") or 0.0),
                    metadata=row.get("metadata", {}),
                    location=row.get("location", {}),
                    kb_id=kb.kb_id,
                    kb_label=kb.label,
                )
            )
        return results

    @staticmethod
    def _merge(per_kb: dict[str, list[KBResult]], strategy: str) -> list[KBResult]:
        if strategy == "score":
            all_results = [r for results in per_kb.values() for r in results]
            return sorted(all_results, key=lambda r: r.score, reverse=True)

        if strategy == "round_robin":
            merged: list[KBResult] = []
            lists = [results for results in per_kb.values() if results]
            max_len = max((len(lst) for lst in lists), default=0)
            for i in range(max_len):
                for lst in lists:
                    if i < len(lst):
                        merged.append(lst[i])
            return merged

        if strategy == "kb_order":
            merged_list: list[KBResult] = []
            for results in per_kb.values():
                merged_list.extend(results)
            return merged_list

        raise ValueError(
            f"Unknown merge_strategy {strategy!r}. "
            "Use 'score', 'round_robin', or 'kb_order'."
        )

    @staticmethod
    def _deduplicate(results: list[KBResult]) -> list[KBResult]:
        seen: set[str] = set()
        unique: list[KBResult] = []
        for r in results:
            key = r.text.strip()
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique


# ---------------------------------------------------------------------------
# Low-level helper
# ---------------------------------------------------------------------------

def _retrieve_one(
    client: Any,
    kb_id: str,
    query: str,
    number_of_results: int,
) -> dict[str, Any]:
    """Call the Bedrock RetrieveAPI for one KB and return the raw response."""
    try:
        return client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": number_of_results
                }
            },
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = error.get("Code", "Unknown")
        message = error.get("Message", str(exc))
        raise RuntimeError(f"Bedrock client error [{code}]: {message}") from exc
    except BotoCoreError as exc:
        raise RuntimeError(f"AWS SDK error: {exc}") from exc
