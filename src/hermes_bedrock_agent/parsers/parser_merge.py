"""Parser merge — combines text parsing and VLM parsing results.

Merges NormalizedDocument text content with VLM-enriched VisualBlocks
to produce a unified NormalizedDocument that references all visual content.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.parsers.base import ParserOutput
from hermes_bedrock_agent.schemas.document import NormalizedDocument
from hermes_bedrock_agent.schemas.visual import VisualBlock

logger = get_logger(__name__)


def merge_parser_outputs(
    text_output: ParserOutput,
    vlm_blocks: list[VisualBlock],
) -> ParserOutput:
    """Merge text parsing result with VLM-enriched visual blocks.

    The merged NormalizedDocument:
    - Keeps original text content
    - Appends VLM-extracted text as additional sections
    - Updates visual_block_ids to reference all visual blocks
    - Merges metadata

    Args:
        text_output: Original text parser output.
        vlm_blocks: VLM-enriched VisualBlocks to merge in.

    Returns:
        Merged ParserOutput with unified NormalizedDocument.
    """
    doc = text_output.normalized_document

    # Collect all visual block IDs (existing + new VLM blocks)
    existing_vb_ids = set(doc.visual_block_ids)
    all_vb_ids = list(existing_vb_ids)
    for vb in vlm_blocks:
        if vb.visual_id not in existing_vb_ids:
            all_vb_ids.append(vb.visual_id)

    # Append VLM-extracted text as additional content sections
    vlm_text_parts: list[str] = []
    vlm_sections: list[dict[str, str]] = []

    for vb in vlm_blocks:
        if vb.extracted_text:
            vlm_text_parts.append(
                f"\n\n[Visual Block: {vb.visual_type.value} — Page {vb.page}]\n{vb.extracted_text}"
            )
        if vb.visual_summary:
            vlm_sections.append({
                "title": f"[Visual] {vb.visual_summary[:80]}",
                "level": "2",
                "page": str(vb.page),
                "source": "vlm",
            })
        if vb.table_markdown:
            vlm_text_parts.append(
                f"\n\n[Table — Page {vb.page}]\n{vb.table_markdown}"
            )

    # Build merged content
    merged_content = doc.content
    if vlm_text_parts:
        merged_content += "\n\n--- VLM Extracted Content ---" + "".join(vlm_text_parts)

    # Build merged sections
    merged_sections = list(doc.sections) + vlm_sections

    # Merge metadata
    merged_metadata = dict(doc.metadata) if doc.metadata else {}
    merged_metadata["vlm_block_count"] = len(vlm_blocks)
    merged_metadata["vlm_merged"] = True

    # Create updated NormalizedDocument
    merged_doc = NormalizedDocument(
        document_id=doc.document_id,
        source_uri=doc.source_uri,
        source_type=doc.source_type,
        title=doc.title,
        content=merged_content,
        sections=merged_sections,
        language=doc.language,
        page_count=doc.page_count,
        content_hash=doc.content_hash,
        metadata=merged_metadata,
        visual_block_ids=all_vb_ids,
        created_at=doc.created_at,
        updated_at=datetime.now(timezone.utc),
    )

    # Combine all visual blocks
    all_blocks = list(text_output.visual_blocks) + vlm_blocks

    return ParserOutput(
        normalized_document=merged_doc,
        visual_blocks=all_blocks,
        metadata={
            "merge_source": "parser_merge",
            "text_blocks": len(text_output.visual_blocks),
            "vlm_blocks": len(vlm_blocks),
        },
    )
