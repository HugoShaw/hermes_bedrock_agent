# Flowchart to Mermaid Converter

A reusable Python CLI tool that converts PDF/image flowcharts into Mermaid format with SVG rendering and comprehensive validation reports.

## Quick Start

```bash
cd ~/projects/hermes_bedrock_agent
source .venv/bin/activate

python -m flowchart_to_mermaid.cli convert \
  --input "data/input/flowchart_samples/M社様_DSSスクリプト改修概要_フローチャート.pdf" \
  --output-dir "data/output/flowchart_samples/msha_dss_flowchart" \
  --lang ja \
  --render-zoom 3 \
  --verbose
```

## Output Files (8 mandatory)

| File | Purpose |
|------|---------|
| `intermediate_flow.raw.json` | Raw extraction result before repair |
| `intermediate_flow.repaired.json` | After semantic repair (edge removal, label normalization) |
| `intermediate_flow.json` | Final validated JSON (source-of-truth for edits) |
| `flowchart.mmd` | Mermaid diagram source |
| `flowchart.svg` | Rendered SVG (via mmdc) |
| `flow_summary.md` | High-level summary with node/edge counts |
| `uncertain_points.md` | Items needing human review |
| `validation_report.md` | Quality metrics, coverage, SVG status |

## Additional Outputs

- `pages/` - Rendered PDF pages as PNG
- `crops/` - Auto-generated section crops for inspection
- `debug/` - Overlay images (text, shapes, arrows, groups, nodes)

## Architecture

```
flowchart_to_mermaid/
├── __init__.py          # Package metadata
├── __main__.py          # Module entry point
├── cli.py               # CLI (typer) with full pipeline
├── config.py            # ConvertConfig dataclass
├── loaders/
│   ├── pdf_loader.py    # PDF → page images (PyMuPDF)
│   └── image_loader.py  # Image → normalized input
├── extraction/
│   ├── text_extractor.py   # PDF text layer extraction
│   ├── ocr_extractor.py    # Optional OCR (pytesseract)
│   ├── shape_detector.py   # OpenCV contour → shapes
│   ├── arrow_detector.py   # HoughLinesP → arrows
│   ├── group_detector.py   # Dashed-box → subgraphs
│   └── layout_analyzer.py  # Direction detection (TD/LR)
├── graph/
│   ├── models.py           # Pydantic models (FlowDocument, etc.)
│   ├── graph_builder.py    # Combine text+shapes → nodes+edges
│   ├── semantic_repair.py  # Rule-based fixes
│   └── graph_validator.py  # Quality checks
├── renderers/
│   ├── mermaid_renderer.py # FlowDocument → .mmd
│   ├── svg_renderer.py     # .mmd → .svg (mmdc)
│   └── debug_renderer.py   # Overlay images
└── utils/
    ├── image_utils.py      # Cropping, overlays
    ├── text_utils.py       # CJK normalization
    ├── geometry.py         # Bbox math
    └── logging_utils.py    # Logger factory
```

## CLI Options

```
--input TEXT       Input PDF or image file path [required]
--output-dir TEXT  Output directory [required]
--lang TEXT        Language: ja/zh/en/auto [default: ja]
--render-zoom INT  PDF render zoom factor [default: 3]
--use-ocr TEXT     OCR: true/false/auto [default: auto]
--use-llm-repair   Use LLM for repair [default: off]
--direction TEXT   Flow direction: TD/LR/auto [default: auto]
--render-svg       Render SVG from Mermaid [default: True]
--svg-required     Fail if SVG cannot render [default: True]
--verbose          Verbose logging
```

## Iterative Improvement Workflow

1. Run pipeline → inspect `uncertain_points.md`
2. Edit `intermediate_flow.json` (add/fix nodes, edges, groups)
3. Re-render from JSON: (future feature, re-run mermaid renderer only)
4. Check `validation_report.md` for coverage gaps

## Dependencies

- PyMuPDF (fitz) - PDF parsing and rendering
- OpenCV (headless) - Shape and arrow detection
- Pillow - Image processing
- Pydantic - Data models and validation
- NetworkX - Graph analysis
- Typer + Rich - CLI framework
- pdfplumber - Alternative PDF text extraction
- mmdc (Mermaid CLI) - SVG rendering

## Tests

```bash
python -m pytest tests/test_models.py tests/test_mermaid_renderer.py \
  tests/test_svg_renderer.py tests/test_graph_validator.py -v
```

All 27 tests cover: models serialization, Mermaid generation, SVG rendering (mocked), graph validation.
