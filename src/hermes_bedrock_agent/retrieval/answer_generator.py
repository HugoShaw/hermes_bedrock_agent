"""Multimodal answer generator — evidence pack → Bedrock Converse → grounded answer.

Evidence flow:
  1. Retrieved Markdown chunks (text)
  2. PDF/PNG page images resolved from chunk metadata (visual)
  3. Business Semantic Graph context from Neptune (architecture)
  4. Implementation Graph context from Neptune (details)
  → All sent together to multimodal VLM for grounded answer generation.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..config import Config, config as _default_config
from ..knowledge_base.schemas import GraphContext, QAAnswerResponse, RetrievedChunk

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_IMAGES = 5
_MAX_IMAGE_PX = 3000


def _s3_path_to_local(s3_path: str, project_root: Path) -> Optional[Path]:
    """Resolve S3-style path to local filesystem path under project_root."""
    if not s3_path.startswith("s3://"):
        return None
    parts = s3_path[5:].split("/", 1)
    if len(parts) < 2:
        return None
    # Try project_root / relative_key
    local = project_root / parts[1]
    if local.exists():
        return local
    # Try outputs/ relative path
    for prefix in ("outputs/", "data/"):
        candidate = project_root / prefix / parts[1]
        if candidate.exists():
            return candidate
    return local  # Return the standard path even if it doesn't exist yet


def _pdf_to_png_bytes(pdf_path: Path) -> Optional[bytes]:
    """Convert page 1 of a PDF to PNG bytes for sending to VLM."""
    if not pdf_path.exists():
        logger.debug("PDF not found, skipping: %s", pdf_path)
        return None

    dpi = 150
    try:
        result = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, timeout=10, text=True)
        for line in result.stdout.splitlines():
            if "Page size:" in line:
                parts = line.split(":")[1].strip().split()
                w_pts, h_pts = float(parts[0]), float(parts[2])
                longest_inches = max(w_pts, h_pts) / 72.0
                ideal_dpi = int(_MAX_IMAGE_PX / longest_inches)
                dpi = max(36, min(150, ideal_dpi))
                break
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / "page"
        try:
            result = subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1", str(pdf_path), str(prefix)],
                capture_output=True, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("pdftoppm failed for %s: %s", pdf_path, exc)
            return None

        if result.returncode != 0:
            return None

        candidates = sorted(Path(tmpdir).glob("page*.png"))
        if not candidates:
            return None

        raw = candidates[0].read_bytes()

    return _resize_png_if_needed(raw)


def _load_png_image(png_path: Path) -> Optional[bytes]:
    """Load a PNG image file directly."""
    if not png_path.exists():
        return None
    raw = png_path.read_bytes()
    return _resize_png_if_needed(raw)


def _resize_png_if_needed(png_bytes: bytes) -> Optional[bytes]:
    try:
        from PIL import Image
        import io

        Image.MAX_IMAGE_PIXELS = 500_000_000
        img = Image.open(io.BytesIO(png_bytes))
        w, h = img.size
        longest = max(w, h)
        if longest <= _MAX_IMAGE_PX:
            return png_bytes
        scale = _MAX_IMAGE_PX / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("Image resize failed (%s), skipping", exc)
        return None


def _build_system_prompt() -> list[dict]:
    return [{"text": (
        "You are a precise technical document analyst for enterprise integration specifications.\n\n"
        "You are given multiple sources of evidence:\n"
        "1. **Markdown text chunks** — extracted from Excel specification sheets via VLM parsing "
        "(may contain OCR/parsing errors or omissions).\n"
        "2. **PDF/PNG page images** — original visual evidence of the specification sheets.\n"
        "3. **Business Semantic Graph** — high-level system architecture, data flow direction "
        "between systems (SAP, DataSpider, ANDPAD, etc.), and sheet relationships.\n"
        "4. **Implementation Graph** — detailed API calls, field mappings, transformation rules, "
        "business rules, and data conditions.\n\n"
        "Your task:\n"
        "- Answer the user's question using ALL available sources of evidence.\n"
        "- Use the Business Graph to understand overall architecture and data flow direction.\n"
        "- Use the Implementation Graph for specific APIs, fields, rules, and conditions.\n"
        "- Use Markdown chunks for textual details and transformation logic.\n"
        "- Use PDF/PNG images to verify and correct any parsing errors in the text.\n"
        "- **IMPORTANT**: If the Markdown text and the PDF/PNG visual evidence seem inconsistent "
        "(e.g., different field names, different flow direction, missing items in text), "
        "explicitly mention the discrepancy and state which source you trust more.\n"
        "- Answer in the same language as the user's question (Japanese or English).\n"
        "- Cite which sheet number or sheet name your answer is based on.\n"
        "- Be concise but complete. Do not speculate beyond what the evidence shows.\n"
        "- If information is insufficient, say so clearly rather than guessing."
    )}]


_MAX_GRAPH_NODES = 30
_MAX_GRAPH_EDGES = 50
_MAX_CONTENT_PREVIEW = 100


def _serialize_dual_graph_context(
    business_graph: Optional[GraphContext],
    implementation_graph: Optional[GraphContext],
) -> str:
    """Serialize two-layer graph context into structured text for the VLM prompt."""
    sections: list[str] = []

    if business_graph and (business_graph.nodes or business_graph.edges):
        sections.append(_serialize_graph_layer(
            business_graph, "Business Semantic Graph",
            "High-level system architecture and data flow direction between systems.",
        ))

    if implementation_graph and (implementation_graph.nodes or implementation_graph.edges):
        sections.append(_serialize_graph_layer(
            implementation_graph, "Implementation Graph",
            "Detailed field mappings, API calls, transformation rules, and business conditions.",
        ))

    return "\n\n".join(sections) if sections else ""


def _serialize_graph_layer(graph: GraphContext, title: str, description: str) -> str:
    """Serialize a single graph layer."""
    nodes = graph.nodes[:_MAX_GRAPH_NODES]
    edges = graph.edges[:_MAX_GRAPH_EDGES]

    id_to_name: dict[str, str] = {}
    for node in nodes:
        nid = node.get("id", "")
        props = node.get("properties", {})
        name = props.get("name") or props.get("sheet_name") or props.get("display_name") or nid
        id_to_name[nid] = str(name)

    by_label: dict[str, list[dict]] = {}
    for node in nodes:
        by_label.setdefault(node.get("label", "Unknown"), []).append(node)

    lines: list[str] = [f"## {title}", f"_{description}_", "", "### Entities"]
    label_order = ["System", "DataFlow", "API", "Field", "MappingRule", "BusinessRule", "Sheet"]
    ordered_labels = label_order + [l for l in by_label if l not in label_order]

    for lbl in ordered_labels:
        if lbl not in by_label:
            continue
        for node in by_label[lbl]:
            props = node.get("properties", {})
            name = props.get("name") or props.get("sheet_name") or props.get("display_name") or node.get("id", "")
            display_name = props.get("display_name", "")
            content_preview = props.get("content_preview", "")
            sheet_index = props.get("sheet_index", "")
            parts = [f"- [{lbl}] {name}"]
            if display_name and display_name != name:
                parts.append(f"({display_name})")
            if sheet_index:
                parts.append(f"— sheet {sheet_index}")
            if content_preview:
                parts.append(f"— \"{str(content_preview)[:_MAX_CONTENT_PREVIEW]}\"")
            lines.append(" ".join(parts))

    lines.extend(["", "### Relationships"])
    for edge in edges:
        from_name = id_to_name.get(edge.get("from", ""), edge.get("from", "?"))
        to_name = id_to_name.get(edge.get("to", ""), edge.get("to", "?"))
        lines.append(f"- {from_name} --{edge.get('relationship', '?')}--> {to_name}")

    lines.extend(["", f"_Total: {len(nodes)} nodes, {len(edges)} edges_"])
    return "\n".join(lines)


def _serialize_graph_context(graph_context: Optional[GraphContext]) -> str:
    """Legacy single-layer serialization for backward compat."""
    if not graph_context or (not graph_context.nodes and not graph_context.edges):
        return ""
    return _serialize_graph_layer(graph_context, "Knowledge Graph Context",
                                  "Entity relationships, system connections, and data flows.")


def load_evidence_images(
    chunks: list[RetrievedChunk],
    project_root: Path,
    max_images: int = _MAX_EVIDENCE_IMAGES,
) -> list[tuple[str, bytes, str]]:
    """Load unique PDF/PNG evidence images from chunk metadata.

    Resolution order for each chunk:
      1. Try source_pdf_s3_path → local PDF → render page 1 to PNG
      2. Try corresponding PNG in images/ directory (pre-rendered)

    Returns list of (label, png_bytes, local_path_str).
    """
    seen_paths: set[str] = set()
    results: list[tuple[str, bytes, str]] = []

    for chunk in chunks:
        if len(results) >= max_images:
            break
        s3_path = chunk.source_pdf_s3_path
        if not s3_path or s3_path in seen_paths:
            continue
        seen_paths.add(s3_path)

        local_path = _s3_path_to_local(s3_path, project_root)
        if local_path is None:
            continue

        png_bytes: Optional[bytes] = None
        resolved_path = str(local_path)

        # Strategy 1: PDF → PNG conversion
        if local_path.suffix.lower() == ".pdf" and local_path.exists():
            png_bytes = _pdf_to_png_bytes(local_path)

        # Strategy 2: Look for pre-rendered PNG in images/ directory
        if png_bytes is None:
            png_dir = local_path.parent.parent / "images" / local_path.stem
            if png_dir.exists():
                full_png = png_dir / "full.png"
                if full_png.exists():
                    png_bytes = _load_png_image(full_png)
                    resolved_path = str(full_png)
                else:
                    # Try any PNG in the directory
                    for candidate in sorted(png_dir.glob("*.png"))[:1]:
                        png_bytes = _load_png_image(candidate)
                        resolved_path = str(candidate)
                        break

        if png_bytes is None:
            logger.debug("No visual evidence found for: %s", s3_path)
            continue

        label = f"Sheet {chunk.sheet_index} ({chunk.sheet_name}) — {Path(resolved_path).name}"
        results.append((label, png_bytes, resolved_path))

    return results


def generate_answer(
    query: str,
    retrieved_chunks: list[RetrievedChunk],
    evidence_images: list[tuple[str, bytes, str]],
    graph_context: Optional[GraphContext] = None,
    business_graph: Optional[GraphContext] = None,
    implementation_graph: Optional[GraphContext] = None,
    cfg: Optional[Config] = None,
    project_id: str = "",
) -> QAAnswerResponse:
    """Call Bedrock Converse with full evidence pack to generate a grounded answer.

    Evidence pack:
      - Markdown chunks (text)
      - PDF/PNG page images (visual)
      - Business Semantic Graph context (architecture)
      - Implementation Graph context (details)
    """
    from ..clients.bedrock import make_bedrock_client, converse_with_system

    cfg = cfg or _default_config
    model_id = cfg.vlm_model_id
    client = make_bedrock_client(cfg.aws_region)

    # Serialize graph context — prefer dual-layer if available
    if business_graph or implementation_graph:
        graph_text = _serialize_dual_graph_context(business_graph, implementation_graph)
    else:
        graph_text = _serialize_graph_context(graph_context)

    # Build text content: chunks + graph
    chunk_lines = [
        f"[Chunk {i} | Sheet {c.sheet_index} {c.sheet_name} | Type: {c.chunk_type} | Score: {c.score:.3f}]\n{c.content}"
        for i, c in enumerate(retrieved_chunks, 1)
    ]
    chunks_text = "\n\n---\n\n".join(chunk_lines)
    graph_section = f"\n\n{graph_text}" if graph_text else ""

    # Build message content array (text + images)
    content: list[dict] = [{"text": (
        f"## Retrieved Markdown Chunks\n\n{chunks_text}"
        f"{graph_section}\n\n"
        f"---\n\nPlease answer this question: {query}"
    )}]

    # Add visual evidence images
    if evidence_images:
        content.append({"text": "\n## Visual Evidence (PDF/PNG pages from original specification sheets)"})
        for label, png_bytes, _ in evidence_images:
            content.append({"text": f"[{label}]"})
            content.append({"image": {"format": "png", "source": {"bytes": png_bytes}}})

    response = converse_with_system(
        client, model_id,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": content}],
        max_tokens=4096, temperature=0.2,
    )

    output_msg = response.get("output", {}).get("message", {})
    answer_text = " ".join(
        block.get("text", "") for block in output_msg.get("content", []) if "text" in block
    ).strip()

    usage = response.get("usage", {})
    evidence_paths = list({c.source_pdf_s3_path for c in retrieved_chunks if c.source_pdf_s3_path})
    image_paths = [path for _, _, path in evidence_images]

    # Merge graph for response object
    merged_graph = graph_context
    if business_graph or implementation_graph:
        merged_nodes = (business_graph.nodes if business_graph else []) + (implementation_graph.nodes if implementation_graph else [])
        merged_edges = (business_graph.edges if business_graph else []) + (implementation_graph.edges if implementation_graph else [])
        merged_graph = GraphContext(nodes=merged_nodes, edges=merged_edges)

    return QAAnswerResponse(
        query=query,
        chunks=retrieved_chunks,
        evidence_paths=evidence_paths,
        graph_context=merged_graph,
        answer=answer_text,
        graph_context_text=graph_text,
        evidence_images_used=image_paths,
        model_id=model_id,
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
    )
