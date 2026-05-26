"""Multimodal answer generator — text chunks + PDF evidence images → Bedrock Converse."""

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
    if not s3_path.startswith("s3://"):
        return None
    parts = s3_path[5:].split("/", 1)
    if len(parts) < 2:
        return None
    return project_root / parts[1]


def _pdf_to_png_bytes(pdf_path: Path) -> Optional[bytes]:
    if not pdf_path.exists():
        logger.warning("PDF not found, skipping: %s", pdf_path)
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
        "- Answer in the same language as the user's question (Japanese or English).\n"
        "- Cite which sheet number or sheet name your answer is based on.\n"
        "- Be concise but complete. Do not speculate beyond what the evidence shows."
    )}]


_MAX_GRAPH_NODES = 30
_MAX_GRAPH_EDGES = 50
_MAX_CONTENT_PREVIEW = 100


def _serialize_graph_context(graph_context: Optional[GraphContext]) -> str:
    if not graph_context or (not graph_context.nodes and not graph_context.edges):
        return ""

    nodes = graph_context.nodes[:_MAX_GRAPH_NODES]
    edges = graph_context.edges[:_MAX_GRAPH_EDGES]

    id_to_name: dict[str, str] = {}
    for node in nodes:
        nid = node.get("id", "")
        props = node.get("properties", {})
        name = props.get("name") or props.get("sheet_name") or props.get("display_name") or nid
        id_to_name[nid] = str(name)

    by_label: dict[str, list[dict]] = {}
    for node in nodes:
        by_label.setdefault(node.get("label", "Unknown"), []).append(node)

    lines: list[str] = ["## Knowledge Graph Context", "", "### Entities (Nodes)"]
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
                parts.append(f"— \"{str(content_preview)[:_MAX_CONTENT_PREVIEW]}\"")
            lines.append(" ".join(parts))

    lines.extend(["", "### Relationships (Edges)"])
    for edge in edges:
        from_name = id_to_name.get(edge.get("from", ""), edge.get("from", "?"))
        to_name = id_to_name.get(edge.get("to", ""), edge.get("to", "?"))
        lines.append(f"- {from_name} --{edge.get('relationship', '?')}--> {to_name}")

    label_counts = {lbl: len(ns) for lbl, ns in by_label.items()}
    system_names = [n.get("properties", {}).get("name", "") for n in by_label.get("System", [])]
    lines.extend(["", "### Overview", f"- Total: {len(nodes)} nodes, {len(edges)} edges"])
    if system_names:
        lines.append(f"- Systems: {', '.join(system_names)}")
    for lbl, count in label_counts.items():
        if lbl != "System":
            lines.append(f"- {lbl}: {count}")

    return "\n".join(lines)


def load_evidence_images(
    chunks: list[RetrievedChunk],
    project_root: Path,
    max_images: int = _MAX_EVIDENCE_IMAGES,
) -> list[tuple[str, bytes, str]]:
    """Load unique PDF evidence images. Returns list of (label, png_bytes, local_path_str)."""
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
    cfg: Optional[Config] = None,
) -> QAAnswerResponse:
    """Call Bedrock Converse with text chunks + PDF images to generate a final answer."""
    from ..clients.bedrock import make_bedrock_client

    cfg = cfg or _default_config
    model_id = cfg.vlm_model_id
    client = make_bedrock_client(cfg.aws_region)

    graph_text = _serialize_graph_context(graph_context)

    chunk_lines = [
        f"[Chunk {i} | Sheet {c.sheet_index} {c.sheet_name} | Type: {c.chunk_type} | Score: {c.score:.3f}]\n{c.content}"
        for i, c in enumerate(retrieved_chunks, 1)
    ]
    chunks_text = "\n\n---\n\n".join(chunk_lines)
    graph_section = f"\n\n{graph_text}" if graph_text else ""

    content: list[dict] = [{"text": (
        f"Retrieved text chunks:\n\n{chunks_text}"
        f"{graph_section}\n\n"
        f"---\n\nPlease answer this question: {query}"
    )}]

    for label, png_bytes in [(label, b) for label, b, _ in evidence_images]:
        content.append({"text": f"[Visual evidence — {label}]"})
        content.append({"image": {"format": "png", "source": {"bytes": png_bytes}}})

    from ..clients.bedrock import converse_with_system
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

    return QAAnswerResponse(
        query=query,
        chunks=retrieved_chunks,
        evidence_paths=evidence_paths,
        graph_context=graph_context,
        answer=answer_text,
        graph_context_text=graph_text,
        evidence_images_used=image_paths,
        model_id=model_id,
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
    )
