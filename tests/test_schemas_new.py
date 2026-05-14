"""Tests for the new Enterprise GraphRAG schemas.

Validates all 15 core Pydantic models can be instantiated, serialized,
and maintain stable ID generation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hermes_bedrock_agent.schemas import (
    AnswerResult,
    ChunkEmbedding,
    ChunkType,
    Citation,
    DocumentChunk,
    DocumentStatus,
    EntityType,
    EvidenceRecord,
    FusedContext,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    LayoutAlgorithm,
    NormalizedDocument,
    RelationType,
    RetrievalSource,
    SourceDocument,
    SourceType,
    SubgraphResult,
    TextEvidence,
    VisualBlock,
    VisualizationEdge,
    VisualizationNode,
    VisualType,
)
from hermes_bedrock_agent.utils.hashing import (
    content_hash,
    make_chunk_id,
    make_document_id,
    make_entity_id,
    make_evidence_id,
    make_relation_id,
    make_visual_id,
    sha256_hex,
)


# ---------------------------------------------------------------------------
# Document schemas
# ---------------------------------------------------------------------------


class TestSourceDocument:
    def test_create_minimal(self):
        doc = SourceDocument(
            document_id="doc_abc123",
            source_uri="s3://bucket/key.pdf",
        )
        assert doc.document_id == "doc_abc123"
        assert doc.source_type == SourceType.UNKNOWN
        assert doc.status == DocumentStatus.DISCOVERED
        assert doc.is_image is False

    def test_create_full(self):
        doc = SourceDocument(
            document_id="doc_full",
            source_uri="s3://bucket/image.png",
            source_type=SourceType.IMAGE,
            filename="image.png",
            file_size=1024,
            content_hash="abc123",
            status=DocumentStatus.PARSED,
            acl=["team-a"],
        )
        assert doc.is_image is True
        assert doc.needs_vlm is True
        assert doc.acl == ["team-a"]

    def test_serialization_roundtrip(self):
        doc = SourceDocument(
            document_id="doc_rt",
            source_uri="s3://bucket/test.md",
            source_type=SourceType.MARKDOWN,
        )
        json_str = doc.model_dump_json()
        restored = SourceDocument.model_validate_json(json_str)
        assert restored.document_id == doc.document_id
        assert restored.source_type == SourceType.MARKDOWN


class TestNormalizedDocument:
    def test_create(self):
        doc = NormalizedDocument(
            document_id="doc_norm",
            source_uri="s3://bucket/test.md",
            title="Test Document",
            content="Hello world. " * 100,
            sections=[
                {"title": "Intro", "level": "1", "offset": "0"},
            ],
        )
        assert doc.char_count == len("Hello world. " * 100)
        assert doc.section_count == 1

    def test_empty_doc(self):
        doc = NormalizedDocument(
            document_id="doc_empty",
            source_uri="s3://bucket/empty.txt",
        )
        assert doc.char_count == 0
        assert doc.section_count == 0


# ---------------------------------------------------------------------------
# Visual schemas
# ---------------------------------------------------------------------------


class TestVisualBlock:
    def test_create(self):
        vb = VisualBlock(
            visual_id="vis_abc",
            document_id="doc_parent",
            image_id="page_3_fig_1",
            visual_type=VisualType.ARCHITECTURE,
            visual_summary="System architecture showing three microservices",
            extracted_text="ServiceA -> ServiceB -> ServiceC",
            confidence=0.92,
            model_name="anthropic.claude-sonnet-4-20250514",
        )
        assert vb.has_structured_content is True
        assert "architecture" in vb.combined_text.lower() or "ServiceA" in vb.combined_text

    def test_no_structured_content(self):
        vb = VisualBlock(
            visual_id="vis_plain",
            document_id="doc_x",
            image_id="logo_1",
            visual_summary="Company logo",
        )
        assert vb.has_structured_content is False


# ---------------------------------------------------------------------------
# Chunk schemas
# ---------------------------------------------------------------------------


class TestDocumentChunk:
    def test_create(self):
        chunk = DocumentChunk(
            chunk_id="chunk_abc",
            document_id="doc_parent",
            chunk_index=0,
            content="This is a test chunk with enough content.",
            chunk_type=ChunkType.TEXT,
            token_count=10,
        )
        assert chunk.is_visual_derived is False

    def test_visual_derived(self):
        chunk = DocumentChunk(
            chunk_id="chunk_vis",
            document_id="doc_parent",
            chunk_index=1,
            content="Description of architecture diagram",
            chunk_type=ChunkType.VISUAL_DESCRIPTION,
            visual_block_ids=["vis_abc"],
        )
        assert chunk.is_visual_derived is True


class TestChunkEmbedding:
    def test_create(self):
        emb = ChunkEmbedding(
            chunk_id="chunk_abc",
            document_id="doc_parent",
            content="Test content",
            embedding=[0.1] * 1024,
            embedding_dimension=1024,
            embedding_model="amazon.titan-embed-text-v2:0",
        )
        assert len(emb.embedding) == 1024
        assert emb.embedding_model == "amazon.titan-embed-text-v2:0"


# ---------------------------------------------------------------------------
# Graph schemas
# ---------------------------------------------------------------------------


class TestGraphEntity:
    def test_create(self):
        entity = GraphEntity(
            entity_id="ent_abc",
            canonical_name="仕訳基礎システム",
            entity_type=EntityType.SYSTEM,
            description="Murata AP journaling module",
            aliases=["Journal Base", "仕訳基礎"],
            confidence=0.95,
        )
        assert entity.entity_type == EntityType.SYSTEM
        assert len(entity.aliases) == 2

    def test_serialization(self):
        entity = GraphEntity(
            entity_id="ent_ser",
            canonical_name="TestEntity",
            entity_type=EntityType.MODULE,
        )
        json_str = entity.model_dump_json()
        restored = GraphEntity.model_validate_json(json_str)
        assert restored.canonical_name == "TestEntity"


class TestGraphRelation:
    def test_create(self):
        rel = GraphRelation(
            relation_id="rel_abc",
            source_entity_id="ent_a",
            target_entity_id="ent_b",
            relation_type=RelationType.DEPENDS_ON,
            confidence=0.88,
        )
        assert rel.relation_type == RelationType.DEPENDS_ON


class TestEvidenceRecord:
    def test_create(self):
        ev = EvidenceRecord(
            evidence_id="evi_abc",
            entity_id="ent_a",
            source_chunk_id="chunk_x",
            document_id="doc_y",
            evidence_text="The system depends on the database",
            confidence=0.9,
        )
        assert ev.entity_id == "ent_a"
        assert ev.relation_id is None


# ---------------------------------------------------------------------------
# Retrieval schemas
# ---------------------------------------------------------------------------


class TestTextEvidence:
    def test_create(self):
        te = TextEvidence(
            evidence_id="te_1",
            chunk_id="chunk_abc",
            document_id="doc_x",
            content="Relevant text passage",
            source=RetrievalSource.OPENSEARCH_TEXT,
            score=0.85,
            rank=1,
        )
        assert te.source == RetrievalSource.OPENSEARCH_TEXT


class TestGraphEvidence:
    def test_create(self):
        ge = GraphEvidence(
            evidence_id="ge_1",
            entity_id="ent_a",
            content="SystemA depends on DatabaseB",
            path_description="SystemA --depends_on--> DatabaseB",
            hop_count=1,
            score=0.75,
        )
        assert ge.hop_count == 1


class TestFusedContext:
    def test_create_with_evidence(self):
        ctx = FusedContext(
            query="How does SystemA work?",
            text_evidence=[
                TextEvidence(
                    evidence_id="te_1",
                    chunk_id="c1",
                    document_id="d1",
                    content="SystemA processes data",
                    score=0.9,
                    rank=0,
                ),
            ],
            graph_evidence=[
                GraphEvidence(
                    evidence_id="ge_1",
                    content="SystemA connects to DB",
                    score=0.8,
                    rank=0,
                ),
            ],
        )
        assert ctx.total_evidence_count == 2


class TestAnswerResult:
    def test_create(self):
        ans = AnswerResult(
            query="What is SystemA?",
            answer="SystemA is the main processing module.",
            confidence=0.88,
            citations=[
                Citation(evidence_id="te_1", source_uri="s3://bucket/doc.pdf"),
            ],
            model_name="anthropic.claude-sonnet-4-20250514",
        )
        assert ans.has_citations is True
        assert ans.citation_count == 1


# ---------------------------------------------------------------------------
# Visualization schemas
# ---------------------------------------------------------------------------


class TestVisualizationNode:
    def test_create(self):
        node = VisualizationNode(
            node_id="ent_a",
            label="SystemA",
            entity_type="system",
            degree=5,
        )
        assert node.degree == 5


class TestVisualizationEdge:
    def test_create(self):
        edge = VisualizationEdge(
            edge_id="rel_a",
            source_id="ent_a",
            target_id="ent_b",
            label="depends_on",
        )
        assert edge.style == "solid"


class TestSubgraphResult:
    def test_create(self):
        sg = SubgraphResult(
            query="SystemA neighborhood",
            nodes=[
                VisualizationNode(node_id="n1", label="A"),
                VisualizationNode(node_id="n2", label="B"),
            ],
            edges=[
                VisualizationEdge(edge_id="e1", source_id="n1", target_id="n2", label="calls"),
            ],
        )
        assert sg.node_count == 2
        assert sg.edge_count == 1
        assert sg.is_empty is False

    def test_empty_subgraph(self):
        sg = SubgraphResult(query="nonexistent")
        assert sg.is_empty is True


# ---------------------------------------------------------------------------
# Hashing / ID generation
# ---------------------------------------------------------------------------


class TestHashing:
    def test_sha256_deterministic(self):
        assert sha256_hex("hello") == sha256_hex("hello")
        assert sha256_hex("hello") != sha256_hex("world")

    def test_content_hash(self):
        h = content_hash("test content")
        assert len(h) == 64  # SHA-256 hex

    def test_make_document_id(self):
        doc_id = make_document_id("s3://bucket/key.pdf")
        assert doc_id.startswith("doc_")
        assert len(doc_id) == 20  # "doc_" + 16 hex chars
        # Deterministic
        assert make_document_id("s3://bucket/key.pdf") == doc_id

    def test_make_chunk_id(self):
        chunk_id = make_chunk_id("doc_abc", 0, "hash123")
        assert chunk_id.startswith("chunk_")
        assert len(chunk_id) == 22  # "chunk_" + 16 hex chars

    def test_make_visual_id(self):
        vis_id = make_visual_id("doc_abc", page=1, image_id="fig_2")
        assert vis_id.startswith("vis_")

    def test_make_entity_id(self):
        ent_id = make_entity_id("system", "SystemA")
        assert ent_id.startswith("ent_")
        # Case-insensitive
        assert make_entity_id("system", "SystemA") == make_entity_id("system", "  systema  ")

    def test_make_relation_id(self):
        rel_id = make_relation_id("ent_a", "depends_on", "ent_b")
        assert rel_id.startswith("rel_")

    def test_make_evidence_id(self):
        evi_id = make_evidence_id("ent_a", "chunk_x")
        assert evi_id.startswith("evi_")
