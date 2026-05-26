"""
Excel Neptune loader — thin wrapper around base V2 NeptuneLoader
with Excel-specific validation and verification queries.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from hermes_bedrock_agent.v2.graph.neptune_loader import (
    NeptuneLoader,
    NeptuneLoaderConfig,
)

logger = logging.getLogger(__name__)


# Verification queries for Excel graph
VERIFICATION_QUERIES = [
    ("Total nodes", "MATCH (n) RETURN count(n) AS cnt"),
    ("Total relationships", "MATCH ()-[r]->() RETURN count(r) AS cnt"),
    ("Nodes by label", "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"),
    ("Relationships by type", "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS cnt ORDER BY cnt DESC"),
    ("System nodes", "MATCH (n:System) RETURN n.name AS name, n.`~id` AS id"),
    ("Message sample", "MATCH (n:Message) RETURN n.name AS name, n.sheet_name AS sheet LIMIT 5"),
    ("Cross-layer links", "MATCH ()-[r:RELATED_TO]->() WHERE r.semantic_layer = 'cross_layer' RETURN count(r) AS cnt"),
    ("MAPS_TO edges", "MATCH ()-[r:MAPS_TO]->() RETURN count(r) AS cnt"),
    ("HAS_EVIDENCE edges", "MATCH ()-[r:HAS_EVIDENCE]->() RETURN count(r) AS cnt"),
    ("EvidenceChunk nodes", "MATCH (n:EvidenceChunk) RETURN count(n) AS cnt"),
    ("Run ID check", "MATCH (n) WHERE n.run_id = $run_id RETURN count(n) AS cnt"),
    ("Dataset check", "MATCH (n) WHERE n.dataset = $dataset RETURN count(n) AS cnt"),
    ("API nodes", "MATCH (n:API) RETURN n.name AS name, n.`~id` AS id"),
    ("BusinessProcess nodes", "MATCH (n:BusinessProcess) RETURN n.name AS name"),
    ("Function nodes", "MATCH (n:Function) RETURN n.name AS name"),
]


class ExcelNeptuneLoader(NeptuneLoader):
    """Excel-specific Neptune loader with verification queries."""

    def __init__(self, config: NeptuneLoaderConfig, run_id: str = "", dataset: str = ""):
        super().__init__(config)
        self._run_id = run_id
        self._dataset = dataset
        self.verification_results: list[dict[str, Any]] = []

    def verify_load(self) -> list[dict[str, Any]]:
        """Run verification queries after load to confirm graph state.

        Returns list of {query_name, query, result, success} dicts.
        """
        if not self.config.execute or not self.config.is_configured:
            return [{"query_name": "SKIPPED", "reason": "Not in execute mode"}]

        client = self._get_client()
        results = []

        for name, query in VERIFICATION_QUERIES:
            try:
                params = {}
                if '$run_id' in query:
                    params['run_id'] = self._run_id
                if '$dataset' in query:
                    params['dataset'] = self._dataset
                result = client.execute_query(query, params)
                results.append({
                    "query_name": name,
                    "query": query,
                    "result": result,
                    "success": True,
                })
            except Exception as e:
                results.append({
                    "query_name": name,
                    "query": query,
                    "error": str(e),
                    "success": False,
                })
            time.sleep(0.3)  # Rate limiting

        self.verification_results = results
        return results
