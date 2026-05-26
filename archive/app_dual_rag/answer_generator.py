"""Multimodal answer generator for the dual-RAG pipeline.

Sends retrieved text chunks + PDF evidence images to Claude via Bedrock
Converse API and produces a grounded, citation-aware answer.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .config import config
from .schemas import GraphContext, QAAnswerResponse, RetrievedChunk

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_IMAGES = 5
_MAX_IMAGE_PX = 3000
_BEDROCK_MAX_PX = 7900


def _s3_path_to_local(s3_path: str) -> Optional[Path]:
    """Convert s3://bucket/key path to local path relative to project root."""
    if not s3_path.startswith("s3://"):
        return None
    # Strip s3://bucket-name/
    parts = s3_path[5:].split("/", 1)
    if len(parts) < 2:
        return None
    local = config.project_root / parts[1]
    return local


def _pdf_to_png_bytes(pdf_path: Path) -> Optional[bytes]:
    """Convert first page of a PDF to PNG bytes via pdftoppm.
    
    Uses adaptive DPI: checks page dimensions and picks DPI that produces
    an image where the longest side is approximately _MAX_IMAGE_PX.
    """
    if not pdf_path.exists():
        logger.warning("PDF not found, skipping: %s", pdf_path)
        return None

    # Determine page size to pick appropriate DPI
    dpi = 150  # default
    try:
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True, timeout=10, text=True
        )
        for line in result.stdout.splitlines():
            if "Page size:" in line:
                # Parse "8503.94 x 5669.29 pts"
                parts = line.split(":")[1].strip().split()
                w_pts, h_pts = float(parts[0]), float(parts[2])
                longest_pts = max(w_pts, h_pts)
                # Calculate DPI to get longest side = _MAX_IMAGE_PX
                # pts → inches: divide by 72
                longest_inches = longest_pts / 72.0
                ideal_dpi = int(_MAX_IMAGE_PX / longest_inches)
                dpi = max(36, min(150, ideal_dpi))  # clamp between 36-150
                logger.debug("PDF %s: %.0f x %.0f pts, using DPI=%d", pdf_path.name, w_pts, h_pts, dpi)
                break
    except Exception:
        pass  # fallback to default DPI

    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / "page"
        try:
            result = subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r", str(dpi),
                    "-f", "1",
                    "-l", "1",
                    str(pdf_path),
                    str(prefix),
                ],
                capture_output=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("pdftoppm failed for %s: %s", pdf_path, exc)
            return None

        if result.returncode != 0:
            logger.warning("pdftoppm error for %s: %s", pdf_path, result.stderr.decode())
            return None

        # pdftoppm produces prefix-1.png (with leading zero padding)
        candidates = sorted(Path(tmpdir).glob("page*.png"))
        if not candidates:
            logger.warning("pdftoppm produced no PNG for %s", pdf_path)
            return None

        png_path = candidates[0]
        raw = png_path.read_bytes()

    resized = _resize_png_if_needed(raw)
    if resized is None:
        logger.warning("Failed to resize PNG for %s, skipping", pdf_path)
        return None
    return resized


def _resize_png_if_needed(png_bytes: bytes) -> Optional[bytes]:
    """Downscale a PNG so its longest dimension is at most _MAX_IMAGE_PX.
    
    Returns None if resize fails (caller should skip this image).
    """
    try:
        from PIL import Image
        import io

        # Allow very large images (enterprise Excel renders can be huge)
        Image.MAX_IMAGE_PIXELS = 500_000_000

        img = Image.open(io.BytesIO(png_bytes))
        w, h = img.size
        longest = max(w, h)
        if longest <= _MAX_IMAGE_PX:
            return png_bytes

        scale = _MAX_IMAGE_PX / longest
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        logger.info("Resized image from %dx%d to %dx%d", w, h, new_w, new_h)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("Image resize failed (%s), skipping this image", exc)
        return None


def _build_system_prompt() -> list[dict]:
    return [
        {
            "text": (
                "You are a precise technical document analyst. "
                "You are given:\n"
                "1. Text chunks extracted from Excel-based specification sheets (may contain OCR/parsing errors).\n"
                "2. PNG images of the original PDF specification sheets as visual evidence.\n"
                "3. Knowledge graph context showing entity relationships, system connections, data flows, "
                "and field mappings extracted from the full document set.\n\n"
                "Your task:\n"
                "- Answer the user's question using ALL THREE sources of evidence.\n"
                "- Use the graph context to understand the overall architecture and data flow direction.\n"
                "- Use text chunks for specific details, rules, and conditions.\n"
                "- Use visual evidence to verify and correct any parsing errors in the text.\n"
                "- If the graph shows a relationship that contradicts the text chunks, note the discrepancy.\n"
                "- Answer in the same language as the user's question (Japanese or English).\n"
                "- Cite which sheet number or sheet name your answer is based on "
                "(e.g. 'Sheet 5 (AP発注情報登録)' or 'シート5').\n"
                "- Be concise but complete. Do not speculate beyond what the evidence shows."
            )
        }
    ]


_MAX_CONTENT_PREVIEW = 100
_MAX_GRAPH_NODES = 30
_MAX_GRAPH_EDGES = 50


def _serialize_graph_context(graph_context: Optional[GraphContext]) -> str:
    """Serialize Neptune graph context into a structured LLM-readable text block.

    Targets 500-1500 tokens. Groups nodes by label, lists edges with readable names.
    Returns empty string if no context.
    """
    if not graph_context or (not graph_context.nodes and not graph_context.edges):
        return ""

    nodes = graph_context.nodes[:_MAX_GRAPH_NODES]
    edges = graph_context.edges[:_MAX_GRAPH_EDGES]

    # Build a name lookup for edge formatting
    id_to_name: dict[str, str] = {}
    for node in nodes:
        nid = node.get("id", "")
        props = node.get("properties", {})
        name = props.get("name") or props.get("sheet_name") or props.get("display_name") or nid
        id_to_name[nid] = str(name)

    # Group nodes by label
    by_label: dict[str, list[dict]] = {}
    for node in nodes:
        lbl = node.get("label", "Unknown")
        by_label.setdefault(lbl, []).append(node)

    lines: list[str] = ["## Knowledge Graph Context", ""]
    lines.append("### Entities (Nodes)")

    label_order = ["System", "API", "Field", "MappingRule", "BusinessRule", "DataFlow", "Sheet"]
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
                preview = str(content_preview)[:_MAX_CONTENT_PREVIEW]
                parts.append(f"— \"{preview}\"")
            lines.append(" ".join(parts))

    lines.append("")
    lines.append("### Relationships (Edges)")
    for edge in edges:
        from_name = id_to_name.get(edge.get("from", ""), edge.get("from", "?"))
        to_name   = id_to_name.get(edge.get("to", ""),   edge.get("to",   "?"))
        rel       = edge.get("relationship", "?")
        lines.append(f"- {from_name} --{rel}--> {to_name}")

    lines.append("")
    lines.append("### Overview")

    label_counts = {lbl: len(ns) for lbl, ns in by_label.items()}
    system_names = [
        (n.get("properties", {}).get("name") or n.get("id", ""))
        for n in by_label.get("System", [])
    ]
    lines.append(f"- Total: {len(nodes)} nodes, {len(edges)} edges")
    if system_names:
        lines.append(f"- Systems: {', '.join(system_names)}")
    for lbl, count in label_counts.items():
        if lbl != "System":
            lines.append(f"- {lbl}: {count}")

    return "\n".join(lines)


def _build_user_message(
    query: str,
    chunks: list[RetrievedChunk],
    image_data: list[tuple[str, bytes]],
    graph_context: Optional[GraphContext],
) -> tuple[dict, str]:
    """Build the Converse API user message with text + image content blocks.

    Returns:
        (message_dict, graph_context_text) where graph_context_text is the
        serialized graph section sent to the LLM (empty string if none).
    """
    content: list[dict] = []

    # ── Text context block ────────────────────────────────────────────────────
    chunk_lines: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        chunk_lines.append(
            f"[Chunk {i} | Sheet {chunk.sheet_index} {chunk.sheet_name} | "
            f"Type: {chunk.chunk_type} | Score: {chunk.score:.3f}]\n{chunk.content}"
        )
    chunks_text = "\n\n---\n\n".join(chunk_lines)

    graph_text = _serialize_graph_context(graph_context)

    graph_section = f"\n\n{graph_text}" if graph_text else ""

    content.append(
        {
            "text": (
                f"Retrieved text chunks:\n\n{chunks_text}"
                f"{graph_section}\n\n"
                f"---\n\nPlease answer this question: {query}"
            )
        }
    )

    # ── Image blocks ──────────────────────────────────────────────────────────
    for label, png_bytes in image_data:
        content.append({"text": f"[Visual evidence — {label}]"})
        content.append(
            {
                "image": {
                    "format": "png",
                    "source": {"bytes": png_bytes},
                }
            }
        )

    return {"role": "user", "content": content}, graph_text


def load_evidence_images(
    chunks: list[RetrievedChunk],
    max_images: int = _MAX_EVIDENCE_IMAGES,
) -> list[tuple[str, bytes, str]]:
    """Load unique PDF evidence images for the given chunks.

    Returns:
        List of (label, png_bytes, local_path_str) tuples, deduplicated by sheet.
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

        local_path = _s3_path_to_local(s3_path)
        if local_path is None:
            continue

        png_bytes = _pdf_to_png_bytes(local_path)
        if png_bytes is None:
            continue

        label = f"Sheet {chunk.sheet_index} ({chunk.sheet_name}) — {local_path.name}"
        results.append((label, png_bytes, str(local_path)))

    return results


def generate_answer(
    query: str,
    retrieved_chunks: list[RetrievedChunk],
    evidence_images: list[tuple[str, bytes, str]],
    graph_context: Optional[GraphContext] = None,
) -> QAAnswerResponse:
    """Call Bedrock Converse with text chunks + PDF images to generate a final answer.

    Args:
        query: The user question.
        retrieved_chunks: Top-K retrieved text chunks.
        evidence_images: List of (label, png_bytes, local_path_str) from load_evidence_images().
        graph_context: Optional Neptune graph context.

    Returns:
        QAAnswerResponse with generated answer and token usage.
    """
    from hermes_bedrock_agent.clients.bedrock_client import BedrockRuntimeClient

    model_id = os.getenv("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")

    image_data = [(label, png_bytes) for label, png_bytes, _ in evidence_images]
    image_paths = [path for _, _, path in evidence_images]

    system = _build_system_prompt()
    user_message, graph_context_text = _build_user_message(
        query, retrieved_chunks, image_data, graph_context
    )

    client = BedrockRuntimeClient()
    response = client.converse(
        model_id=model_id,
        messages=[user_message],
        system=system,
        inference_config={"maxTokens": 4096, "temperature": 0.2},
    )

    output_msg = response.get("output", {}).get("message", {})
    content_blocks = output_msg.get("content", [])
    answer_text = " ".join(
        block.get("text", "") for block in content_blocks if "text" in block
    ).strip()

    usage = response.get("usage", {})
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)

    evidence_paths = list({c.source_pdf_s3_path for c in retrieved_chunks if c.source_pdf_s3_path})

    return QAAnswerResponse(
        query=query,
        chunks=retrieved_chunks,
        evidence_paths=evidence_paths,
        graph_context=graph_context,
        answer=answer_text,
        graph_context_text=graph_context_text,
        evidence_images_used=image_paths,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
