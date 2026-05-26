"""CLI for flowchart-to-mermaid conversion tool."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from flowchart_to_mermaid.config import ConvertConfig
from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, PageFlow,
    TextBlock, UncertainPoint,
)

app = typer.Typer(name="flowchart-to-mermaid", help="Convert flowchart PDF/images to Mermaid format")
console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_time=False)],
    )


@app.command()
def convert(
    input: str = typer.Option(..., "--input", help="Input PDF or image file path"),
    output_dir: str = typer.Option(..., "--output-dir", help="Output directory"),
    lang: str = typer.Option("ja", "--lang", help="Language: ja/zh/en/auto"),
    render_zoom: int = typer.Option(3, "--render-zoom", help="PDF render zoom factor"),
    use_ocr: str = typer.Option("auto", "--use-ocr", help="OCR: true/false/auto"),
    use_llm_repair: bool = typer.Option(False, "--use-llm-repair", help="Use LLM for repair"),
    direction: str = typer.Option("auto", "--direction", help="Flow direction: TD/LR/auto"),
    render_svg: bool = typer.Option(True, "--render-svg", help="Render SVG from Mermaid"),
    svg_required: bool = typer.Option(True, "--svg-required", help="Fail if SVG cannot render"),
    repair_profile: Optional[str] = typer.Option(None, "--repair-profile", help="Semantic repair profile name (e.g. msha_dss)"),
    compare_with_gold: bool = typer.Option(False, "--compare-with-gold", help="Compare output with golden reference after conversion"),
    gold_reference: Optional[str] = typer.Option(None, "--gold-reference", help="Path to golden reference Mermaid file"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose logging"),
) -> None:
    """Convert a flowchart PDF or image to Mermaid format with SVG output."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    console.print(f"[bold blue]Flowchart to Mermaid Converter v0.1.0[/]")
    console.print(f"Input: {input}")
    console.print(f"Output: {output_dir}")
    console.print(f"Language: {lang} | Direction: {direction} | Zoom: {render_zoom}")
    console.print()

    # Configure
    config = ConvertConfig(
        input_path=Path(input),
        output_dir=Path(output_dir),
        lang=lang,
        render_zoom=render_zoom,
        use_ocr=use_ocr,
        use_llm_repair=use_llm_repair,
        direction=direction,
        render_svg=render_svg,
        svg_required=svg_required,
    )
    config.ensure_dirs()

    if not config.input_path.exists():
        console.print(f"[red]Error: Input file not found: {config.input_path}[/]")
        raise typer.Exit(code=1)

    # Determine input type
    suffix = config.input_path.suffix.lower()
    is_pdf = suffix == ".pdf"
    is_image = suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

    if not (is_pdf or is_image):
        console.print(f"[red]Error: Unsupported file type: {suffix}[/]")
        raise typer.Exit(code=1)

    # Phase 1: Load and render
    console.print("[bold]Phase 1: Loading document...[/]")
    pages_info = _load_document(config, is_pdf)

    # Phase 2: Extract text
    console.print("[bold]Phase 2: Extracting text...[/]")
    text_blocks_by_page = _extract_text(config, pages_info, is_pdf, use_ocr)

    # Phase 3: Generate crops
    console.print("[bold]Phase 3: Generating crops...[/]")
    crops_info = _generate_crops(config, pages_info)

    # Phase 4: Detect shapes, arrows, groups
    console.print("[bold]Phase 4: Detecting visual elements...[/]")
    shapes_by_page, arrows_by_page, groups_by_page = _detect_elements(
        config, pages_info, text_blocks_by_page
    )

    # Phase 5: Build graph
    console.print("[bold]Phase 5: Building flow graph...[/]")
    doc = _build_graph(
        config, pages_info, text_blocks_by_page,
        shapes_by_page, arrows_by_page, groups_by_page
    )

    # Phase 6: Save intermediate JSON (raw)
    console.print("[bold]Phase 6: Saving intermediate JSON...[/]")
    raw_json_path = config.output_dir / "intermediate_flow.raw.json"
    _save_json(doc, raw_json_path)

    # Phase 7: Semantic repair
    console.print("[bold]Phase 7: Semantic repair...[/]")
    if repair_profile:
        # Use profile-based repair
        console.print(f"  Using repair profile: {repair_profile}")
        from flowchart_to_mermaid.graph.profile_repair import apply_profile_repair
        raw_flow_data = json.loads(raw_json_path.read_text(encoding="utf-8"))
        doc = apply_profile_repair(raw_flow_data, repair_profile, config.output_dir)
        console.print(f"  Profile repair complete: {len(doc.pages[0].nodes)} nodes, "
                     f"{len(doc.pages[0].edges)} edges, {len(doc.pages[0].groups)} groups")
    else:
        from flowchart_to_mermaid.graph.semantic_repair import SemanticRepairer
        repairer = SemanticRepairer()
        doc = repairer.repair(doc)

        repaired_json_path = config.output_dir / "intermediate_flow.repaired.json"
        _save_json(doc, repaired_json_path)

        # Save final intermediate JSON
        final_json_path = config.output_dir / "intermediate_flow.json"
        _save_json(doc, final_json_path)

    # Phase 8: Generate debug overlays
    console.print("[bold]Phase 8: Generating debug overlays...[/]")
    _generate_debug_overlays(config, pages_info, doc)

    # Phase 9: Render Mermaid
    console.print("[bold]Phase 9: Rendering Mermaid...[/]")
    mmd_path = config.output_dir / "flowchart.mmd"
    from flowchart_to_mermaid.renderers.mermaid_renderer import MermaidRenderer
    renderer = MermaidRenderer()
    mmd_content = renderer.render(doc, mmd_path)

    # Phase 10: Render SVG
    svg_result = None
    if render_svg:
        console.print("[bold]Phase 10: Rendering SVG...[/]")
        from flowchart_to_mermaid.renderers.svg_renderer import SVGRenderer
        svg_renderer = SVGRenderer(project_root=Path.cwd())
        svg_path = config.output_dir / "flowchart.svg"
        svg_result = svg_renderer.render(mmd_path, svg_path)

        if svg_result.success:
            console.print(f"[green]SVG rendered: {svg_result.svg_path} ({svg_result.svg_size} bytes)[/]")
        else:
            console.print(f"[red]SVG rendering failed: {svg_result.stderr[:200]}[/]")

    # Phase 11: Validate and generate reports
    console.print("[bold]Phase 11: Validating and generating reports...[/]")
    from flowchart_to_mermaid.graph.graph_validator import GraphValidator
    validator = GraphValidator()
    validation = validator.validate(doc)

    _generate_reports(config, doc, validation, svg_result, crops_info)

    # Final status
    console.print()
    console.print(f"[bold green]✓ Conversion complete[/]")
    console.print(f"  Nodes: {validation['total_nodes']}")
    console.print(f"  Edges: {validation['total_edges']}")
    console.print(f"  Groups: {validation['total_groups']}")
    console.print(f"  Mermaid: {mmd_path}")

    if svg_result and svg_result.success:
        console.print(f"  SVG: {svg_result.svg_path} ({svg_result.svg_size} bytes)")
    elif svg_required and (not svg_result or not svg_result.success):
        console.print(f"[red]  SVG: FAILED (required)[/]")
        raise typer.Exit(code=2)
    else:
        console.print(f"  SVG: Not generated (optional)")

    # Phase 12: Gold comparison (optional)
    if compare_with_gold and gold_reference:
        console.print()
        console.print("[bold]Phase 12: Comparing with golden reference...[/]")
        gold_path = Path(gold_reference)
        if gold_path.exists():
            comparison_dir = config.output_dir / "comparison_after_fix"
            try:
                from flowchart_to_mermaid.compare.mermaid_parser import MermaidParser
                from flowchart_to_mermaid.compare.graph_normalizer import GraphNormalizer
                from flowchart_to_mermaid.compare.graph_diff import GraphDiff
                from flowchart_to_mermaid.compare.comparison_reporter import ComparisonReporter

                parser = MermaidParser()
                normalizer = GraphNormalizer()
                differ = GraphDiff()
                reporter = ComparisonReporter()

                actual_text = mmd_path.read_text(encoding="utf-8")
                expected_text = gold_path.read_text(encoding="utf-8")

                actual_parsed = parser.parse(actual_text)
                expected_parsed = parser.parse(expected_text)

                actual_norm = normalizer.normalize(actual_parsed)
                expected_norm = normalizer.normalize(expected_parsed)

                diff_result = differ.diff(actual_norm, expected_norm)

                reporter.save_all(
                    output_dir=comparison_dir,
                    actual_path=str(mmd_path),
                    expected_path=str(gold_path),
                    diff_result=diff_result,
                    actual_normalized=actual_norm,
                    expected_normalized=expected_norm,
                )

                console.print(f"  CRITICAL: {diff_result.severity_counts.get('CRITICAL', 0)}")
                console.print(f"  HIGH: {diff_result.severity_counts.get('HIGH', 0)}")
                console.print(f"  Comparison saved: {comparison_dir}/")
            except Exception as e:
                console.print(f"[yellow]  Gold comparison failed: {e}[/]")
        else:
            console.print(f"[yellow]  Gold reference not found: {gold_path}[/]")


def _load_document(config: ConvertConfig, is_pdf: bool) -> list[dict]:
    """Load document and render pages."""
    if is_pdf:
        from flowchart_to_mermaid.loaders.pdf_loader import PDFLoader
        loader = PDFLoader(config)
        return loader.load()
    else:
        from flowchart_to_mermaid.loaders.image_loader import ImageLoader
        loader = ImageLoader(config)
        return loader.load()


def _extract_text(
    config: ConvertConfig, pages_info: list[dict],
    is_pdf: bool, use_ocr: str
) -> list[list[TextBlock]]:
    """Extract text from all pages."""
    text_blocks_by_page = []

    for page_info in pages_info:
        page_blocks = []

        if is_pdf:
            from flowchart_to_mermaid.extraction.text_extractor import TextExtractor
            extractor = TextExtractor(config.input_path, config.render_zoom)
            page_blocks = extractor.extract_page(page_info["page_index"])

            # Decide if OCR is needed
            if use_ocr == "true" or (use_ocr == "auto" and len(page_blocks) < 5):
                from flowchart_to_mermaid.extraction.ocr_extractor import OCRExtractor, is_ocr_available
                if is_ocr_available():
                    ocr = OCRExtractor(lang="jpn+eng" if config.lang == "ja" else "eng")
                    ocr_blocks = ocr.extract(Path(page_info["image_path"]))
                    page_blocks.extend(ocr_blocks)
        else:
            # Image input - try OCR
            if use_ocr in ("true", "auto"):
                from flowchart_to_mermaid.extraction.ocr_extractor import OCRExtractor, is_ocr_available
                if is_ocr_available():
                    ocr = OCRExtractor(lang="jpn+eng" if config.lang == "ja" else "eng")
                    page_blocks = ocr.extract(Path(page_info["image_path"]))

        text_blocks_by_page.append(page_blocks)
        logging.getLogger(__name__).info(
            f"Page {page_info['page_index']}: {len(page_blocks)} text blocks"
        )

    return text_blocks_by_page


def _generate_crops(config: ConvertConfig, pages_info: list[dict]) -> list[dict]:
    """Generate image crops for each page."""
    from flowchart_to_mermaid.utils.image_utils import ImageCropper
    cropper = ImageCropper()
    all_crops = []

    for page_info in pages_info:
        crops = cropper.generate_crops(
            Path(page_info["image_path"]), config.crops_dir
        )
        all_crops.extend(crops)

    return all_crops


def _detect_elements(
    config: ConvertConfig, pages_info: list[dict],
    text_blocks_by_page: list[list[TextBlock]],
) -> tuple[list, list, list]:
    """Detect shapes, arrows, and groups."""
    from flowchart_to_mermaid.extraction.shape_detector import ShapeDetector
    from flowchart_to_mermaid.extraction.arrow_detector import ArrowDetector
    from flowchart_to_mermaid.extraction.group_detector import GroupDetector

    shape_detector = ShapeDetector()
    arrow_detector = ArrowDetector()
    group_detector = GroupDetector()

    shapes_by_page = []
    arrows_by_page = []
    groups_by_page = []

    for i, page_info in enumerate(pages_info):
        img_path = Path(page_info["image_path"])
        text_blocks = text_blocks_by_page[i] if i < len(text_blocks_by_page) else []

        # Detect shapes
        shapes = shape_detector.detect(img_path)
        shapes_by_page.append(shapes)

        # Generate overlay
        shape_overlay = config.debug_dir / f"page_{i+1:03d}_shapes_overlay.png"
        shape_detector.generate_overlay(img_path, shapes, shape_overlay)

        # Detect arrows
        arrows = arrow_detector.detect(img_path)
        arrows_by_page.append(arrows)

        arrow_overlay = config.debug_dir / f"page_{i+1:03d}_arrows_overlay.png"
        arrow_detector.generate_overlay(img_path, arrows, arrow_overlay)

        # Detect groups
        groups = group_detector.detect(img_path, text_blocks)
        groups_by_page.append(groups)

        group_overlay = config.debug_dir / f"page_{i+1:03d}_groups_overlay.png"
        group_detector.generate_overlay(img_path, groups, group_overlay)

    return shapes_by_page, arrows_by_page, groups_by_page


def _build_graph(
    config: ConvertConfig, pages_info: list[dict],
    text_blocks_by_page: list, shapes_by_page: list,
    arrows_by_page: list, groups_by_page: list,
) -> FlowDocument:
    """Build the flow document with nodes, edges, groups."""
    from flowchart_to_mermaid.graph.graph_builder import GraphBuilder
    from flowchart_to_mermaid.extraction.layout_analyzer import LayoutAnalyzer

    builder = GraphBuilder(direction=config.direction)
    analyzer = LayoutAnalyzer()

    pages = []
    for i, page_info in enumerate(pages_info):
        text_blocks = text_blocks_by_page[i] if i < len(text_blocks_by_page) else []
        shapes = shapes_by_page[i] if i < len(shapes_by_page) else []
        arrows = arrows_by_page[i] if i < len(arrows_by_page) else []
        groups = groups_by_page[i] if i < len(groups_by_page) else []

        pw = page_info["width"]
        ph = page_info["height"]

        # Determine direction
        if config.direction == "auto":
            direction = analyzer.analyze_direction(pw, ph, text_blocks)
            builder.direction = direction

        nodes, edges, groups_out, uncertain = builder.build(
            text_blocks, shapes, arrows, groups, pw, ph
        )

        pages.append(PageFlow(
            page_index=i,
            width=pw,
            height=ph,
            text_blocks=text_blocks,
            nodes=nodes,
            edges=edges,
            groups=groups_out,
            uncertain_points=uncertain,
        ))

    direction = builder.direction if builder.direction != "auto" else "LR"
    doc = FlowDocument(
        source_file=str(config.input_path),
        source_type="pdf" if config.input_path.suffix.lower() == ".pdf" else "image",
        pages=pages,
        direction=direction,
    )

    return doc


def _save_json(doc: FlowDocument, path: Path) -> None:
    """Save FlowDocument as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = doc.model_dump(mode="json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info(f"Saved: {path} ({path.stat().st_size} bytes)")


def _generate_debug_overlays(
    config: ConvertConfig, pages_info: list[dict], doc: FlowDocument
) -> None:
    """Generate debug overlay images."""
    from flowchart_to_mermaid.renderers.debug_renderer import DebugRenderer
    from flowchart_to_mermaid.utils.image_utils import generate_text_overlay

    debug = DebugRenderer()

    for i, page_info in enumerate(pages_info):
        if i >= len(doc.pages):
            break
        page = doc.pages[i]
        img_path = Path(page_info["image_path"])

        # Text overlay
        text_overlay = config.debug_dir / f"page_{i+1:03d}_text_overlay.png"
        generate_text_overlay(img_path, page.text_blocks, text_overlay)

        # Nodes overlay
        nodes_overlay = config.debug_dir / f"page_{i+1:03d}_nodes_overlay.png"
        debug.render_nodes_overlay(img_path, page.nodes, nodes_overlay)

        # Edges overlay (arrows between nodes)
        # Note: arrows_overlay is generated in _detect_elements already


def _generate_reports(
    config: ConvertConfig, doc: FlowDocument, validation: dict,
    svg_result, crops_info: list[dict]
) -> None:
    """Generate all report files."""
    _generate_flow_summary(config, doc, crops_info, svg_result)
    _generate_uncertain_points(config, doc)
    _generate_validation_report(config, doc, validation, svg_result)


def _generate_flow_summary(
    config: ConvertConfig, doc: FlowDocument,
    crops_info: list[dict], svg_result
) -> None:
    """Generate flow_summary.md."""
    lines = [
        "# Flow Summary",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Source:** {doc.source_file}",
        f"**Type:** {doc.source_type}",
        f"**Direction:** {doc.direction}",
        "",
        "## Pages",
        "",
    ]

    for page in doc.pages:
        lines.append(f"### Page {page.page_index + 1}")
        lines.append(f"- Size: {page.width} x {page.height}")
        lines.append(f"- Text blocks: {len(page.text_blocks)}")
        lines.append(f"- Nodes: {len(page.nodes)}")
        lines.append(f"- Edges: {len(page.edges)}")
        lines.append(f"- Groups: {len(page.groups)}")
        lines.append("")

    # Crops
    lines.append("## Crops")
    lines.append("")
    for crop in crops_info:
        lines.append(f"- **{crop['name']}**: bbox={crop['bbox']}")
    lines.append("")

    # Main flow
    lines.append("## Detected Main Flow")
    lines.append("")
    for page in doc.pages:
        for node in page.nodes:
            prefix = "→ " if node.type.value != "terminator" else "● "
            lines.append(f"{prefix}{node.label} [{node.type.value}]")
    lines.append("")

    # Function numbers found
    lines.append("## Function Numbers Found")
    lines.append("")
    for page in doc.pages:
        for node in page.nodes:
            if "機能No" in node.label or "機能" in node.label:
                lines.append(f"- {node.label}")
    lines.append("")

    # API calls found
    lines.append("## API Calls Found")
    lines.append("")
    for page in doc.pages:
        for node in page.nodes:
            if any(kw in node.label for kw in ["GET：", "POST：", "PUT：", "DELETE：", "GET:", "POST:", "PUT:", "DELETE:"]):
                lines.append(f"- {node.label}")
    lines.append("")

    # Output files
    lines.append("## Generated Files")
    lines.append("")
    lines.append(f"- Mermaid: {config.output_dir / 'flowchart.mmd'}")
    if svg_result and svg_result.success:
        lines.append(f"- SVG: {svg_result.svg_path} ({svg_result.svg_size} bytes)")
    else:
        lines.append("- SVG: NOT GENERATED")
    lines.append(f"- JSON: {config.output_dir / 'intermediate_flow.json'}")
    lines.append("")

    path = config.output_dir / "flow_summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def _generate_uncertain_points(config: ConvertConfig, doc: FlowDocument) -> None:
    """Generate uncertain_points.md."""
    lines = [
        "# Uncertain Points",
        "",
        "Points requiring human review.",
        "",
    ]

    idx = 0
    for page in doc.pages:
        for up in page.uncertain_points:
            idx += 1
            lines.append(f"## {idx}. {up.type.value.title()}")
            lines.append(f"- **Message:** {up.message}")
            lines.append(f"- **Related IDs:** {', '.join(up.related_ids)}")
            if up.suggested_review_image:
                lines.append(f"- **Review image:** {up.suggested_review_image}")
            lines.append("")

        # Also list uncertain nodes
        for node in page.nodes:
            if node.uncertain:
                idx += 1
                lines.append(f"## {idx}. Uncertain Node")
                lines.append(f"- **Node:** {node.id} - {node.label}")
                lines.append(f"- **Confidence:** {node.confidence:.2f}")
                lines.append("")

        # Inferred edges
        for edge in page.edges:
            if edge.inferred:
                idx += 1
                lines.append(f"## {idx}. Inferred Edge")
                lines.append(f"- **Edge:** {edge.source} → {edge.target}")
                lines.append(f"- **Confidence:** {edge.confidence:.2f}")
                if edge.label:
                    lines.append(f"- **Label:** {edge.label}")
                lines.append("")

    if idx == 0:
        lines.append("No uncertain points detected.")
        lines.append("")

    lines.append(f"\n**Total uncertain points:** {idx}")

    path = config.output_dir / "uncertain_points.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def _generate_validation_report(
    config: ConvertConfig, doc: FlowDocument,
    validation: dict, svg_result
) -> None:
    """Generate validation_report.md."""
    lines = [
        "# Validation Report",
        "",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Source:** {doc.source_file}",
        "",
        "## Statistics",
        "",
        f"- Text blocks: {validation['total_text_blocks']}",
        f"- Nodes: {validation['total_nodes']}",
        f"- Edges: {validation['total_edges']}",
        f"- Groups: {validation['total_groups']}",
        f"- Start nodes: {validation['start_nodes']}",
        f"- End nodes: {validation['end_nodes']}",
        f"- Orphan nodes: {validation['orphan_nodes']}",
        f"- Uncertain edges: {validation['uncertain_edges']}",
        f"- Inferred edges: {validation['inferred_edges']}",
        "",
        "## Function Number Coverage",
        "",
        f"Coverage: {validation.get('function_coverage_ratio', 0):.0%}",
        "",
    ]

    fn_cov = validation.get("function_coverage", {})
    for fn, found in fn_cov.items():
        status = "✓" if found else "✗"
        lines.append(f"- {status} {fn}")
    lines.append("")

    lines.append("## API Coverage")
    lines.append("")
    lines.append(f"Coverage: {validation.get('api_coverage_ratio', 0):.0%}")
    lines.append("")
    api_cov = validation.get("api_coverage", {})
    for api, found in api_cov.items():
        status = "✓" if found else "✗"
        lines.append(f"- {status} {api}")
    lines.append("")

    # Mermaid SVG Rendering section
    lines.append("## Mermaid SVG Rendering")
    lines.append("")
    lines.append(f"- Mermaid source: {config.output_dir / 'flowchart.mmd'}")

    if svg_result:
        lines.append(f"- SVG output: {config.output_dir / 'flowchart.svg'}")
        lines.append(f"- Renderer command: {svg_result.command_used}")
        lines.append(f"- SVG generated: {svg_result.success}")
        lines.append(f"- SVG file size: {svg_result.svg_size} bytes")
        lines.append(f"- Render exit code: {svg_result.exit_code}")
        if not svg_result.success:
            lines.append(f"- Render stderr: {svg_result.stderr[:500]}")
            lines.append("")
            lines.append("**SVG_RENDER_FAILED**")
        else:
            lines.append("")
            lines.append("**SVG_RENDERED_SUCCESSFULLY**")
    else:
        lines.append("- SVG rendering: skipped (--render-svg false)")
    lines.append("")

    # Issues and warnings
    if validation.get("issues"):
        lines.append("## Issues")
        lines.append("")
        for issue in validation["issues"]:
            lines.append(f"- ⚠️ {issue}")
        lines.append("")

    if validation.get("warnings"):
        lines.append("## Warnings")
        lines.append("")
        for warning in validation["warnings"]:
            lines.append(f"- ⚡ {warning}")
        lines.append("")

    path = config.output_dir / "validation_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


@app.command()
def validate(
    mmd_file: str = typer.Option(..., "--input", help="Mermaid .mmd file to validate"),
) -> None:
    """Validate a Mermaid file for syntax issues."""
    setup_logging()
    path = Path(mmd_file)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/]")
        raise typer.Exit(code=1)

    content = path.read_text(encoding="utf-8")

    # Basic syntax checks
    issues = []
    if not content.strip().startswith("flowchart"):
        issues.append("File does not start with 'flowchart' directive")

    # Check for unbalanced quotes
    if content.count('"') % 2 != 0:
        issues.append("Unbalanced double quotes")

    # Check subgraph/end balance
    subgraph_count = content.count("subgraph ")
    end_count = content.count("\n    end") + content.count("\nend")
    if subgraph_count != end_count:
        issues.append(f"Subgraph/end mismatch: {subgraph_count} subgraphs, {end_count} ends")

    if issues:
        console.print("[red]Validation issues:[/]")
        for issue in issues:
            console.print(f"  - {issue}")
        raise typer.Exit(code=1)
    else:
        console.print("[green]✓ Mermaid file looks valid[/]")


def main():
    app()


if __name__ == "__main__":
    main()
