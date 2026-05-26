"""Neptune Analytics graph operations module.

Phase 6 modules:
- extractor: LLM-based entity/relation extraction
- normalizer: entity deduplication and canonical naming
- quality_review: validation and confidence filtering
- neptune_loader: Cypher generation and Neptune loading

Legacy modules (unchanged):
- neptune_client: low-level Neptune connection
- cypher_templates: parameterized query templates
"""

from hermes_bedrock_agent.graph.extractor import (
    BaseGraphExtractor,
    ExtractionResult,
    ExtractorConfig,
    GraphExtractor,
    MockGraphExtractor,
    build_extraction_prompt,
    parse_llm_json_response,
)
from hermes_bedrock_agent.graph.normalizer import (
    EntityNormalizer,
    NormalizerConfig,
    build_entity_id,
    merge_aliases,
    normalize_name,
)
from hermes_bedrock_agent.graph.neptune_loader import (
    build_edge_cypher,
    build_edge_query_and_params,
    build_import_cypher,
    build_node_cypher,
    build_node_query_and_params,
    entity_type_to_label,
    load_edges_to_neptune,
    load_nodes_to_neptune,
    load_to_neptune,
    relation_type_to_cypher_type,
    serialize_property_value,
    write_neptune_import_cypher,
)
from hermes_bedrock_agent.graph.i18n_enricher import (
    BUILTIN_RELATION_I18N_MAP,
    EntityI18n,
    EnrichmentConfig,
    I18nEnricher,
    MockDeterministicLLM,
    RelationI18n,
)
from hermes_bedrock_agent.graph.quality_review import (
    GraphQualityReviewer,
    QualityConfig,
    ReviewResult,
    load_graph_schema,
)

__all__ = [
    # Extractor
    "BaseGraphExtractor",
    "ExtractionResult",
    "ExtractorConfig",
    "GraphExtractor",
    "MockGraphExtractor",
    "build_extraction_prompt",
    "parse_llm_json_response",
    # Normalizer
    "EntityNormalizer",
    "NormalizerConfig",
    "build_entity_id",
    "merge_aliases",
    "normalize_name",
    # Quality Review
    "GraphQualityReviewer",
    "QualityConfig",
    "ReviewResult",
    "load_graph_schema",
    # Neptune Loader
    "build_edge_cypher",
    "build_import_cypher",
    "build_node_cypher",
    "load_to_neptune",
    "write_neptune_import_cypher",
    # i18n Enricher
    "BUILTIN_RELATION_I18N_MAP",
    "EntityI18n",
    "EnrichmentConfig",
    "I18nEnricher",
    "MockDeterministicLLM",
    "RelationI18n",
]
