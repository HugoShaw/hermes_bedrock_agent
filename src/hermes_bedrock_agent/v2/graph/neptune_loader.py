"""
Neptune Loader for Stage 09.

Provides safe, optional Neptune loading with explicit guards:
- Default mode: dry-run (Cypher export only, no Neptune connection)
- Execute mode: requires --execute flag
- Clear mode: requires both --execute and --clear-before-load flags

Uses the existing V1 NeptuneClient for actual query execution.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class NeptuneLoaderConfig:
    """Configuration for Neptune loading."""

    def __init__(
        self,
        graph_id: str = "",
        region: str = "ap-northeast-1",
        execute: bool = False,
        clear_before_load: bool = False,
        batch_size: int = 50,
        delay_between_batches_s: float = 0.5,
    ):
        self.graph_id = graph_id
        self.region = region
        self.execute = execute
        self.clear_before_load = clear_before_load
        self.batch_size = batch_size
        self.delay_between_batches_s = delay_between_batches_s

    @property
    def is_configured(self) -> bool:
        """Check if Neptune connection info is available."""
        return bool(self.graph_id and self.region)


class NeptuneLoader:
    """Safe Neptune loader with explicit execution guards."""

    def __init__(self, config: NeptuneLoaderConfig):
        self.config = config
        self._client: Optional[Any] = None
        self.load_stats: dict[str, Any] = {
            'mode': 'dry_run',
            'executed': False,
            'cleared': False,
            'statements_total': 0,
            'statements_executed': 0,
            'statements_failed': 0,
            'errors': [],
        }

    def _get_client(self) -> Any:
        """Lazily import and create Neptune client."""
        if self._client is None:
            try:
                from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
                self._client = NeptuneClient(
                    graph_id=self.config.graph_id,
                    region=self.config.region,
                )
            except ImportError as e:
                raise RuntimeError(
                    f"Cannot import NeptuneClient: {e}. "
                    f"Ensure hermes_bedrock_agent is installed."
                ) from e
        return self._client

    def validate_config(self) -> dict[str, Any]:
        """Validate Neptune configuration without connecting."""
        return {
            'graph_id_present': bool(self.config.graph_id),
            'graph_id': self.config.graph_id or 'NOT SET',
            'region_present': bool(self.config.region),
            'region': self.config.region or 'NOT SET',
            'is_configured': self.config.is_configured,
            'execute_requested': self.config.execute,
            'clear_requested': self.config.clear_before_load,
        }

    def dry_run(
        self,
        queries: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Validate queries without executing.

        Returns stats about what would happen.
        """
        self.load_stats['mode'] = 'dry_run'
        self.load_stats['statements_total'] = len(queries)

        # Basic validation
        invalid = []
        for i, (cypher, params) in enumerate(queries):
            if not cypher.strip():
                invalid.append(f"Query {i}: empty cypher")
            if 'JOURNAL_BASE20180530' in cypher.upper():
                invalid.append(f"Query {i}: contains JOURNAL_BASE reference")

        self.load_stats['validation_errors'] = invalid
        self.load_stats['valid'] = len(invalid) == 0

        return self.load_stats

    def execute_load(
        self,
        queries: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Execute queries against Neptune.

        ONLY call this when --execute is explicitly passed.
        """
        if not self.config.execute:
            raise RuntimeError(
                "Neptune execution not requested. "
                "Pass --execute to enable actual loading."
            )

        if not self.config.is_configured:
            raise RuntimeError(
                f"Neptune not configured. "
                f"graph_id={self.config.graph_id!r}, region={self.config.region!r}"
            )

        self.load_stats['mode'] = 'execute'
        self.load_stats['statements_total'] = len(queries)

        client = self._get_client()

        # Optional clear
        if self.config.clear_before_load:
            logger.warning("Clearing Neptune graph before load...")
            try:
                client.execute_query("MATCH (n) DETACH DELETE n")
                self.load_stats['cleared'] = True
                logger.info("Neptune graph cleared.")
            except Exception as e:
                self.load_stats['errors'].append(f"Clear failed: {e}")
                raise

        # Execute in batches
        executed = 0
        failed = 0
        batch_errors: list[str] = []

        for i in range(0, len(queries), self.config.batch_size):
            batch = queries[i:i + self.config.batch_size]
            for cypher, params in batch:
                try:
                    client.execute_query(cypher, params)
                    executed += 1
                except Exception as e:
                    failed += 1
                    err_msg = f"Query failed: {str(e)[:100]}"
                    batch_errors.append(err_msg)
                    if failed > 10:
                        self.load_stats['errors'] = batch_errors
                        self.load_stats['statements_executed'] = executed
                        self.load_stats['statements_failed'] = failed
                        self.load_stats['aborted'] = True
                        raise RuntimeError(
                            f"Too many failures ({failed}). Aborting."
                        )

            # Delay between batches
            if i + self.config.batch_size < len(queries):
                time.sleep(self.config.delay_between_batches_s)

        self.load_stats['executed'] = True
        self.load_stats['statements_executed'] = executed
        self.load_stats['statements_failed'] = failed
        self.load_stats['errors'] = batch_errors

        return self.load_stats
