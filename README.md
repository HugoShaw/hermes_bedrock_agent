# DualRAG — Enterprise Document Parsing & Dual-RAG Knowledge Base

## What This Project Does

DualRAG is a complete pipeline that transforms Japanese enterprise design documents (Excel workbooks, PDFs) stored in AWS S3 into a searchable knowledge base with a question-answering terminal.

**The problem it solves:** Japanese companies often use Excel files as software design documents. These Excel files contain business process diagrams, system flow diagrams, data transformation rules, interface definitions, database table mappings, and field-level mappings between multiple systems. This knowledge is trapped in visual spreadsheet layouts and is extremely difficult to search, query, or integrate into other systems.

**What DualRAG does:**

1. **Parses** complex Excel design documents by converting each sheet into PDF/PNG images and using Claude Sonnet (a multimodal AI model) to understand the visual content
2. **Builds** a dual knowledge base: a vector database (LanceDB) for semantic text search AND a graph database (Neptune Analytics) for relationship queries
3. **Answers** questions about the documents using both knowledge sources plus the original images as visual evidence

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Architecture Overview](#4-architecture-overview)
5. [Project Structure](#5-project-structure)
6. [Usage Guide](#6-usage-guide)
7. [Multi-Project Isolation](#7-multi-project-isolation)
8. [Technical Details](#8-technical-details)
9. [Troubleshooting](#9-troubleshooting)
10. [Development](#10-development)

---

## 1. Prerequisites

Before you can use DualRAG, you need the following installed on your system:

### Required Software

| Software | Purpose | How to Install |
|----------|---------|----------------|
| **Python 3.11+** | Runtime | `sudo apt install python3.11` or use pyenv |
| **uv** | Package manager (fast pip alternative) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **AWS CLI** | AWS authentication | `sudo apt install awscli` |
| **LibreOffice** | Converts Excel files to PDF (one PDF per sheet) | `sudo apt install libreoffice` |
| **poppler-utils** | Converts PDF pages to PNG images (`pdftoppm`) | `sudo apt install poppler-utils` |

### Required AWS Resources

| Resource | Purpose | Required? |
|----------|---------|-----------|
| **AWS credentials** | Authentication for all AWS services | ✅ Yes |
| **Amazon Bedrock (Claude Sonnet)** | AI model for visual document understanding + answer generation | ✅ Yes |
| **Amazon Bedrock (Titan Embed V2)** | AI model for text embedding (converts text to numbers for search) | ✅ Yes |
| **S3 bucket** | Where your source documents are stored | ✅ Yes |
| **Neptune Analytics** | Graph database for relationship knowledge | ⚠️ Optional (QA works without it, but with less context) |

### Verify Prerequisites

```bash
# Check Python version (need 3.11 or higher)
python3 --version

# Check uv is installed
uv --version

# Check AWS credentials are configured
aws sts get-caller-identity

# Check LibreOffice
soffice --version

# Check poppler (pdftoppm)
pdftoppm -v
```

---

## 2. Installation

### Step 1: Clone and enter the project directory

```bash
cd ~/projects/hermes_bedrock_agent
```

### Step 2: Install Python dependencies

```bash
# Install all dependencies (this creates a .venv/ directory automatically)
uv sync

# If you also need PDF processing support:
uv sync --extra pdf

# If you also need graph database support:
uv sync --extra graph
```

### Step 3: Verify the installation

```bash
# This should print the CLI help without errors
uv run dualrag --help

# This should print version 1.0.0
uv run python -c "import hermes_bedrock_agent; print(hermes_bedrock_agent.__version__)"
```

If `uv run dualrag --help` shows the three commands (`parse`, `build-kb`, `qa`), the installation is successful.

---

## 3. Configuration

### Step 1: Create your `.env` file

```bash
cp .env.example .env
```

### Step 2: Edit `.env` with your actual values

Open `.env` in your editor and fill in the required fields:

```bash
# ─────────────────────────────────────────────────────────────
# REQUIRED SETTINGS (the pipeline will NOT work without these)
# ─────────────────────────────────────────────────────────────

# AWS Region where your Bedrock models are available
AWS_REGION=ap-northeast-1

# S3 bucket containing your source Excel/PDF documents
S3_BUCKET=your-bucket-name

# Bedrock model for visual understanding and answer generation
# IMPORTANT: In ap-northeast-1, you MUST use inference profile prefixes!
# Use: jp.anthropic.claude-sonnet-4-6  (correct)
# NOT: anthropic.claude-sonnet-4-20250514-v1:0  (will fail with ValidationException)
BEDROCK_VLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6

# Bedrock model for text embeddings (converts text to vectors for search)
BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0

# Where the vector database will be stored on disk
VECTOR_LOCAL_STORE_PATH=/home/ubuntu/projects/data/vector_store/lancedb

# ─────────────────────────────────────────────────────────────
# OPTIONAL SETTINGS (the pipeline works without these but with less features)
# ─────────────────────────────────────────────────────────────

# Neptune Analytics graph database ID (format: g-xxxxxxxxxx)
# If not set, the system works without graph context in QA answers
NEPTUNE_GRAPH_ID=g-xxxxxxxxxx
```

### Step 3: Start LibreOffice in listening mode

LibreOffice must be running as a background service to convert Excel files to PDF:

```bash
# Start LibreOffice in headless mode, listening on port 2002
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &

# Verify it's running:
lsof -i :2002
# Should show a process listening on port 2002
```

**Note:** If LibreOffice is not running, the `parse` command will fail at the "Excel → PDF" stage. You only need LibreOffice when parsing new Excel files. You do NOT need it for `build-kb` or `qa` commands.

---

## 4. Architecture Overview

DualRAG processes documents through 3 stages:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: Document Parsing                                                    │
│                                                                               │
│  S3 Bucket (Excel/PDF files)                                                  │
│       │                                                                       │
│       ▼                                                                       │
│  Download to local disk                                                       │
│       │                                                                       │
│       ▼                                                                       │
│  Excel → PDF (one PDF per sheet, via LibreOffice)                            │
│       │                                                                       │
│       ▼                                                                       │
│  PDF → PNG images (via pdftoppm, with adaptive DPI and tiling for large      │
│       │            sheets that don't fit in one image)                        │
│       ▼                                                                       │
│  PNG → Markdown (via Claude Sonnet multimodal AI — "looks at" each image     │
│                   and writes structured Markdown describing what it sees:     │
│                   tables, flowcharts, mappings, rules, etc.)                  │
│                                                                               │
│  Output: sheet_01.md, sheet_02.md, ... (one Markdown file per sheet)         │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: Knowledge Base Construction                                         │
│                                                                               │
│  Markdown files from Stage 1                                                  │
│       │                                                                       │
│       ├──── Chunk into pieces ──── Embed ──── Store in LanceDB (vector DB)   │
│       │     (split long Markdown  (convert    (enables semantic search:       │
│       │      into ~2000-char       text to     "find content similar to       │
│       │      sections)             numbers)     this question")               │
│       │                                                                       │
│       └──── Extract entities ──── Store in Neptune (graph DB)                │
│             and relationships     (enables relationship queries:              │
│             (systems, APIs,        "what systems connect to SAP?"             │
│              fields, rules,        "what fields map from X to Y?")           │
│              data flows)                                                      │
│                                                                               │
│  Output: LanceDB table + Neptune graph (both tagged with project_id)         │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 3: QA (Question Answering)                                             │
│                                                                               │
│  Your question: "How does order data flow from SAP to ANDPAD?"               │
│       │                                                                       │
│       ├── ① Search LanceDB → find relevant Markdown chunks (text evidence)   │
│       ├── ② Query Neptune → find related graph context (systems, fields...)  │
│       ├── ③ Load PDF/PNG images from chunk metadata (visual evidence)        │
│       │                                                                       │
│       ▼                                                                       │
│  Pack ALL evidence into one request to Claude Sonnet:                        │
│    - Text chunks (what the Markdown says)                                    │
│    - Graph context (what systems/fields/rules are connected)                 │
│    - PDF images (what the original sheet looks like)                          │
│                                                                               │
│  Output: Grounded answer citing specific sheets, flagging any inconsistencies│
└──────────────────────────────────────────────────────────────────────────────┘
```

### Why "Dual-RAG"?

Traditional RAG (Retrieval-Augmented Generation) uses only vector search. DualRAG combines:

1. **Vector RAG** — finds semantically similar text chunks (good for "tell me about X")
2. **Graph RAG** — traverses entity relationships (good for "how does X connect to Y?" or "what fields does system A send to system B?")

By combining both, the QA system can answer questions that neither approach could answer alone.

### Why Visual Parsing (VLM)?

Japanese enterprise Excel documents use:
- Merged cells, colored regions, arrows, and shapes to convey meaning
- Complex visual layouts that plain text extraction (openpyxl, pandas) cannot understand
- Flowcharts drawn with Excel shapes that have no text representation

By converting to images and using a Vision-Language Model (VLM), we capture the **visual** knowledge that traditional parsers miss.

---

## 5. Project Structure

```
hermes_bedrock_agent/
│
├── src/hermes_bedrock_agent/          # Main Python package (all production code)
│   ├── __init__.py                    # Package version
│   ├── config.py                      # Configuration (reads from .env)
│   ├── cli.py                         # CLI commands: parse, build-kb, qa
│   │
│   ├── clients/                       # AWS service wrappers
│   │   ├── bedrock.py                 # Amazon Bedrock (LLM + embeddings)
│   │   ├── neptune.py                 # Neptune Analytics (graph queries)
│   │   └── s3.py                      # S3 (file listing + download)
│   │
│   ├── parsing/                       # Stage 1: Document → Markdown
│   │   ├── models.py                  # Data models (SheetInfo, ParseResult)
│   │   ├── s3_discovery.py            # Find Excel/PDF files in S3
│   │   ├── excel_parser.py            # Excel → per-sheet PDF (LibreOffice)
│   │   ├── pdf_parser.py              # PDF → PNG images (with tiling)
│   │   ├── vlm_client.py             # Send images to Claude → get Markdown
│   │   ├── text_parser.py            # Clean up / post-process Markdown
│   │   ├── image_utils.py            # Image tiling, stitching, resizing
│   │   └── libreoffice.py            # LibreOffice UNO connection helper
│   │
│   ├── knowledge_base/                # Stage 2: Markdown → Knowledge Base
│   │   ├── schemas.py                 # Data models (Chunk, GraphNode, etc.)
│   │   ├── chunker.py                 # Split Markdown into semantic chunks
│   │   ├── vector_store.py            # Embed chunks → store in LanceDB
│   │   ├── graph_extractor.py         # Extract entities/relations (LLM)
│   │   └── graph_loader.py            # Write graph to Neptune
│   │
│   ├── retrieval/                     # Stage 3: Search + Answer
│   │   ├── vector_retriever.py        # Search LanceDB for relevant chunks
│   │   ├── graph_retriever.py         # Get graph context from Neptune
│   │   ├── answer_generator.py        # Combine all evidence → generate answer
│   │   └── query_router.py            # Orchestrate the retrieval + answer flow
│   │
│   └── qa/                            # Interactive terminal
│       └── terminal.py                # REPL with commands, spinner, history
│
├── scripts/                           # Helper scripts for demos and testing
│   ├── run_parse.py                   # Run parse with preset arguments
│   ├── run_build_kb.py                # Run build-kb with preset arguments
│   ├── run_qa.py                      # Run qa with preset arguments
│   ├── demo_qa_evidence_flow.py       # Step-by-step evidence flow demo
│   ├── demo_graph_extraction.py       # Test graph extraction on one sheet
│   └── verify_project_isolation.py    # Automated test for multi-project safety
│
├── outputs/                           # Pipeline outputs (generated, not in git)
│   └── reparse_wb2/                   # Example: parsed Murata 265 workbook
│       ├── pdf/                       #   Per-sheet PDFs
│       ├── images/                    #   Per-sheet PNG images
│       ├── vlm_parsed/                #   Markdown output from VLM
│       └── dual_rag/                  #   KB construction output (chunks.jsonl)
│
├── data/                              # Local databases (generated, not in git)
│   └── vector_store/lancedb/          # LanceDB vector database files
│
├── archive/                           # Old code (kept for history, not used)
│
├── pyproject.toml                     # Project definition + dependencies
├── .env.example                       # Template for environment variables
├── .env                               # Your actual config (NEVER commit this)
├── .gitignore                         # Excludes .env, outputs/, data/
└── README.md                          # This file
```

---

## 6. Usage Guide

DualRAG has three commands, matching the three pipeline stages:

| Command | Stage | What It Does |
|---------|-------|--------------|
| `dualrag parse` | 1 | Downloads and parses Excel/PDF files into Markdown |
| `dualrag build-kb` | 2 | Converts parsed Markdown into a searchable knowledge base |
| `dualrag qa` | 3 | Interactive question-answering terminal |

You can also invoke commands with `uv run python -m hermes_bedrock_agent.cli <command>` — this is equivalent to `dualrag <command>`.

---

### 6.1 Stage 1: Parsing Documents (`dualrag parse`)

This command takes Excel or PDF files, converts them to images, and uses AI to extract the content as Markdown.

**Parse a single local Excel file:**

```bash
dualrag parse --file /path/to/your/document.xlsx
```

**Parse all Excel files under an S3 prefix:**

```bash
dualrag parse --s3-prefix "your-folder/subfolder/"
```

**Parse with explicit project ID and output directory:**

```bash
dualrag parse \
  --s3-prefix "murata/205_order/" \
  --project-id "murata_205_order" \
  --output-dir outputs/murata_205
```

**What happens during parsing:**

```
1. S3 Discovery: scans the prefix for .xlsx and .pdf files
2. Download: copies files to outputs/<run>/downloads/
3. Excel → PDF: LibreOffice converts each sheet to a separate PDF
4. PDF → PNG: pdftoppm renders each page as an image
   - Small sheets → one image
   - Large sheets → split into tiles (3000px each, 300px overlap)
5. VLM Parse: Claude Sonnet "looks at" each image and writes Markdown
   - Detects sheet type (mapping table, flowchart, spec, etc.)
   - Uses a specialized prompt for each type
   - For tiled sheets: parses each tile, then synthesizes
6. Post-process: Cleans up Markdown formatting
```

**⚠️ Important timing notes:**
- VLM parsing takes 40–120 seconds per sheet
- A workbook with 27 sheets takes approximately 30–60 minutes
- Do NOT run multiple parse jobs in parallel — this causes timeout cascades
- The `--stages` option lets you re-run specific stages without repeating earlier ones

**Output structure:**

```
outputs/run_20260526_070000/
├── downloads/                     # Downloaded Excel files
├── MW_IFマッピング定義書_205/      # One directory per workbook
│   ├── pdf/                       # sheet_01.pdf, sheet_02.pdf, ...
│   ├── images/                    # sheet_01/full.png, sheet_02/tiles/...
│   ├── vlm_parsed/                # sheet_01.md, sheet_01_meta.json, ...
│   └── sheet_name_mapping.csv     # Sheet number → actual sheet name
└── parse_summary.json             # Summary of what was parsed
```

---

### 6.2 Stage 2: Building the Knowledge Base (`dualrag build-kb`)

This command takes the Markdown output from Stage 1 and builds both a vector database and a graph database.

**Basic usage:**

```bash
dualrag build-kb outputs/reparse_wb2/vlm_parsed/ \
  --project-id "murata_205_order"
```

**Full example with all options:**

```bash
dualrag build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --workbook "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)" \
  --s3-excel-key "サンプル20260519/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx" \
  --project-id "murata_205_order" \
  --use-llm-graph \
  --graph-delay 3.0
```

**Options explained:**

| Option | Purpose | Default |
|--------|---------|---------|
| `--workbook` / `-w` | Human-readable workbook name stored in chunk metadata | Directory name |
| `--s3-excel-key` | S3 path to the original Excel file (for evidence tracing) | Empty |
| `--s3-pdf-prefix` | Where to find PDF evidence files | Auto-derived from directory |
| `--project-id` | Tags all data with this ID for multi-project isolation | Empty (warns!) |
| `--skip-vector` | Don't write to LanceDB (graph only) | False |
| `--skip-graph` | Don't write to Neptune (vector only) | False |
| `--dry-run-graph` | Extract graph but don't write to Neptune (preview mode) | False |
| `--use-llm-graph` | Use Claude Sonnet for high-quality graph extraction | False (uses keyword) |
| `--graph-delay` | Seconds between LLM calls (avoid throttling) | 3.0 |

**Graph extraction modes:**

| Mode | How It Works | Quality | Cost | When to Use |
|------|-------------|---------|------|-------------|
| **Keyword** (default) | Pattern matching on Markdown text | Basic | Free | Quick testing |
| **LLM** (`--use-llm-graph`) | Claude reads each chunk and extracts entities/relations | High | $$$ | Production builds |

**What happens during build-kb:**

```
1. Chunking: Reads all sheet_XX.md files from the vlm_parsed/ directory
   - Splits each Markdown file into semantic chunks (~2000 chars each)
   - Each chunk knows: which workbook, which sheet, the PDF path, etc.

2. Vector Store: Embeds each chunk and stores in LanceDB
   - Calls Bedrock Titan Embed V2 to convert text → 1024-dim vector
   - Stores in a LanceDB table with metadata columns
   - Table is per-collection (project_id used for filtering, not separate tables)

3. Graph Store: Extracts entities and writes to Neptune
   - Pass 1 (Business): Systems, APIs, DataFlows, BusinessProcesses
   - Pass 2 (Implementation): Tables, Fields, MappingRules, BusinessRules
   - All nodes/edges tagged with project_id
```

**Verify the build:**

```bash
# Check how many chunks were created:
cat outputs/reparse_wb2/dual_rag/kb_summary.json

# Check LanceDB contents:
uv run python -c "
import lancedb
db = lancedb.connect('/home/ubuntu/projects/data/vector_store/lancedb')
tbl = db.open_table('murata_excel_vlm_dual_rag')
print(f'Rows: {tbl.count_rows()}')
print(f'Schema: {tbl.schema.names[:10]}...')
"
```

---

### 6.3 Stage 3: Question Answering (`dualrag qa`)

This command starts an interactive terminal where you can ask questions about the parsed documents.

**Start the interactive QA terminal:**

```bash
dualrag qa --project-id "murata_205_order"
```

**One-shot query (ask one question, get one answer, exit):**

```bash
dualrag qa --project-id "murata_205_order" \
  "SAPからANDPADへの発注データフローを説明してください"
```

**With a catalog directory (enables sheet browsing in the terminal):**

```bash
dualrag qa \
  --project-id "murata_205_order" \
  --catalog-dir outputs/reparse_wb2/
```

**Interactive terminal commands:**

Once inside the QA terminal, you can use these slash commands:

| Command | What It Does |
|---------|--------------|
| `/mode retrieve` | Switch to retrieval-only mode (shows chunks, no answer generation) |
| `/mode answer` | Switch to full answer mode (default — retrieves + generates answer) |
| `/mode graph` | Switch to graph-only mode (shows graph context) |
| `/topk 10` | Change how many chunks to retrieve (1–20) |
| `/verbose` | Toggle showing full chunk text vs. preview |
| `/evidence` | Toggle loading PDF/PNG evidence images |
| `/sheets` | List all available sheets (requires --catalog-dir) |
| `/sheet 6` | Show content of sheet 6 |
| `/history` | Show your query history this session |
| `/stats` | Show session statistics (queries, tokens, timing) |
| `/help` | Show all available commands |
| `/quit` or Ctrl+D | Exit the terminal |

**Example session:**

```
┌────────────────────────────────────────────────────────────┐
║  DualRAG QA Terminal v1.0                                  ║
║  Project: murata_205_order                                 ║
║  Vector: 468 chunks | Graph: 1939 nodes                    ║
╚════════════════════════════════════════════════════════════╝

[answer] @murata_205_order Query> 発注データの取引先管理IDはどのように変換されますか？

⠹ Retrieving... (LanceDB + Neptune)
⠹ Generating answer... (Claude Sonnet + 4 evidence images)

────────── Answer ──────────
取引先管理IDの変換は以下のフローで行われます：

1. SAP側のソースフィールド「仕入先確定コード」と「部門コード」を結合
2. 変換テーブルを参照して ANDPAD の「取引先管理ID」にマッピング
3. 条件: 工事区分が「1」の場合のみ変換実行...

[Evidence: sheet_06.pdf (マッピングシート), sheet_09.pdf (条件定義)]
────────────────────────────

[answer] @murata_205_order Query> /quit
Goodbye!
```

---

### 6.4 Running the Full Pipeline End-to-End

Here's the complete workflow from raw S3 documents to interactive QA:

```bash
# Step 1: Make sure LibreOffice is running
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &

# Step 2: Parse documents from S3
dualrag parse \
  --s3-prefix "サンプル20260519/" \
  --project-id "murata_205_order" \
  --output-dir outputs/murata_205

# Step 3: Build the knowledge base (vector + graph)
dualrag build-kb \
  outputs/murata_205/MW_IFマッピング定義書_205_発注情報/vlm_parsed/ \
  --workbook "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)" \
  --project-id "murata_205_order" \
  --use-llm-graph

# Step 4: Start QA terminal
dualrag qa \
  --project-id "murata_205_order" \
  --catalog-dir outputs/murata_205/MW_IFマッピング定義書_205_発注情報/
```

### 6.5 If You Already Have Parsed Content

If someone has already run Stage 1 and you have Markdown files, you can skip parsing:

```bash
# Just build KB from existing Markdown (no parsing needed)
dualrag build-kb outputs/reparse_wb2/vlm_parsed/ \
  --project-id "murata_205_order" \
  --skip-graph

# Then start QA
dualrag qa --project-id "murata_205_order"
```

---

## 7. Multi-Project Isolation

In production, you may have many different projects (different workbooks, different teams, different document sets). DualRAG ensures that data from one project NEVER leaks into another.

### How It Works

Every chunk in LanceDB and every node/edge in Neptune is tagged with a `project_id`. When you query, the system filters to show ONLY data from your specified project.

```
Project A: murata_205_order (発注情報ワークブック)
Project B: murata_300_delivery (納品情報ワークブック)

Query with --project-id "murata_205_order":
  → Only sees chunks from Project A
  → Only sees graph nodes from Project A
  → Never shows data from Project B
```

### Using Multi-Project

```bash
# Parse for project A
dualrag parse --s3-prefix "murata/205/" --project-id "murata_205_order"
dualrag build-kb outputs/205/vlm_parsed/ --project-id "murata_205_order"

# Parse for project B
dualrag parse --s3-prefix "murata/300/" --project-id "murata_300_delivery"
dualrag build-kb outputs/300/vlm_parsed/ --project-id "murata_300_delivery"

# Query each project independently:
dualrag qa --project-id "murata_205_order"
dualrag qa --project-id "murata_300_delivery"
```

### What Happens If You Forget --project-id

If you omit `--project-id`, the system will:
1. Show a **⚠ WARNING** message
2. For `build-kb`: tag data with empty project_id (can't be filtered later)
3. For `qa`: search across ALL projects (may mix results from different workbooks)

**Always specify --project-id in production.**

### Verify Isolation

```bash
# Run the automated isolation test:
uv run python scripts/verify_project_isolation.py

# Manual verification — query with a fake project_id should return 0 results:
dualrag qa --project-id "nonexistent_project" "test query"
```

---

## 8. Technical Details

### 8.1 VLM (Vision-Language Model) Parsing

The VLM parsing is the core innovation of this system. Here's what happens for each Excel sheet:

```
Sheet in Excel
    │
    ▼ LibreOffice UNO API (port 2002)
Separate PDF file (one page = one sheet, preserving all formatting)
    │
    ▼ pdftoppm (adaptive DPI: 36–150 depending on sheet size)
PNG image(s)
    │  ├─ Small sheet (< 3000px) → single image
    │  └─ Large sheet (> 3000px) → multiple tiles with 300px overlap
    │
    ▼ Claude Sonnet Multimodal (via Bedrock Converse API)
    │  1. Sheet type detection (mapping / flowchart / spec / overview)
    │  2. Specialized prompt per type
    │  3. For tiled sheets: parse each tile separately, then synthesize
    │  4. 3-second delay between sheets (prevent throttling)
    │
    ▼
Markdown output (sheet_XX.md + metadata JSON)
```

**Timing constraints (CRITICAL):**
- **Never parallelize VLM calls** — concurrent requests cause cascading 300+ second timeouts
- Minimum 3 seconds between sheet-level calls
- Minimum 2 seconds between tile-level calls
- Single VLM call takes 40–120 seconds
- `max_tokens` must be ≥ 12000 (large mapping sheets produce ~8000 output tokens)
- `boto3 read_timeout` must be 600s (default 60s times out on large outputs)

### 8.2 Graph Database (Neptune Analytics)

The graph stores two layers of knowledge:

**Business Semantic Graph** (high-level):
- System nodes: SAP, DataSpider, ANDPAD
- DataFlow nodes: order data pipeline
- InterfaceSpec nodes: IF definitions
- BusinessProcess nodes: registration, cancellation
- Edges: SENDS_DATA_TO, CALLS_API, TRIGGERS

**Implementation Graph** (detail-level):
- SourceTable / TargetTable nodes
- SourceField / TargetField nodes (column-level)
- MappingRule nodes (conversion logic)
- BusinessRule nodes (conditions, branches)
- Edges: HAS_FIELD, MAPS_TO, TRANSFORMS_TO, HAS_CONDITION

**Neptune access pattern:**
- Protocol: openCypher queries (NOT Gremlin)
- Authentication: IAM + SigV4 signing
- Node upsert: `MERGE (n:Label {node_id: ..., project_id: ...}) SET n += {...}`
- All queries filter by `project_id`

### 8.3 Vector Database (LanceDB)

LanceDB is a lightweight, local vector database (no server needed):

- Stored at: `/home/ubuntu/projects/data/vector_store/lancedb`
- Table name: `murata_excel_vlm_dual_rag`
- Embedding dimensions: 1024 (Titan Embed V2)
- Distance metric: Cosine similarity
- Each row contains: embedding vector + all chunk metadata (project_id, sheet_name, etc.)

**How search works:**
1. Your query is embedded using Titan Embed V2 → 1024-dim vector
2. LanceDB finds the K nearest vectors (cosine similarity)
3. Results are filtered by `project_id` (pre-filter)
4. Metadata from matching rows tells us which PDF to load as evidence

### 8.4 Evidence Image Resolution

When the QA system retrieves chunks, each chunk has metadata like:
```
source_pdf_s3_path: "s3://s3-hulftchina-rd/outputs/reparse_wb2/pdf/sheet_06.pdf"
```

The system resolves this to a local file:
1. Strip the bucket name: `outputs/reparse_wb2/pdf/sheet_06.pdf`
2. Join with project root: `/home/ubuntu/projects/hermes_bedrock_agent/outputs/reparse_wb2/pdf/sheet_06.pdf`
3. Read the PDF/PNG bytes
4. Include in the multimodal LLM request as visual evidence

This allows the AI to "see" the original document when generating its answer, catching any discrepancies between the parsed Markdown and the original visual.

### 8.5 Model ID Configuration (ap-northeast-1)

In the Tokyo region (ap-northeast-1), Amazon Bedrock requires **inference profile prefixes** for model IDs:

| Prefix | Region Scope | Example |
|--------|-------------|---------|
| `jp.anthropic.*` | Japan only | `jp.anthropic.claude-sonnet-4-6` |
| `apac.anthropic.*` | Asia-Pacific | `apac.anthropic.claude-sonnet-4-6` |
| `global.anthropic.*` | Global | `global.anthropic.claude-sonnet-4-6` |

**Common mistake:** Using bare model IDs like `anthropic.claude-sonnet-4-20250514-v1:0` will fail with `ValidationException`. Always use the prefixed form.

To check available inference profiles:
```bash
aws bedrock list-inference-profiles --region ap-northeast-1 --query "InferenceProfileSummaries[].InferenceProfileId"
```

---

## 9. Troubleshooting

### "LibreOffice connection refused on port 2002"

LibreOffice is not running or crashed. Fix:
```bash
# Kill any zombie processes
pkill -f soffice
# Restart
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &
# Wait 3 seconds for it to start
sleep 3
# Verify
lsof -i :2002
```

### "ValidationException: model ID not found"

You're using the wrong model ID format for your region. In ap-northeast-1:
```bash
# Wrong:
BEDROCK_VLM_MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0

# Correct:
BEDROCK_VLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6
```

### "VLM call timed out after 60 seconds"

The default boto3 timeout is too short. The config already sets `read_timeout=600` but if you're calling Bedrock directly, ensure you use:
```python
from botocore.config import Config
bedrock_config = Config(read_timeout=600, retries={"max_attempts": 3})
```

### "LanceDB table not found"

You haven't built the knowledge base yet. Run:
```bash
dualrag build-kb outputs/reparse_wb2/vlm_parsed/ --project-id "murata_205_order"
```

### "Neptune: connection error / graph not configured"

Neptune is optional. If you don't have a Neptune graph:
- `build-kb` will skip graph building (use `--skip-graph` to suppress the warning)
- `qa` will work without graph context (use `--no-graph` to suppress the warning)

### "0 chunks retrieved in QA"

Possible causes:
1. **Wrong project_id** — make sure the project_id you query with matches what you used in `build-kb`
2. **LanceDB is empty** — check with the verify command above
3. **Query too short** — try a more descriptive question

### "Evidence images: 0 (paths not resolved)"

The PDF files are not where the metadata says they should be. Check:
```bash
# Look at what path a chunk expects:
head -1 outputs/reparse_wb2/dual_rag/chunks.jsonl | python3 -c "
import json, sys
chunk = json.loads(sys.stdin.read())
print(chunk.get('source_pdf_s3_path'))
"

# Then verify the file exists at that relative path from project root
ls outputs/reparse_wb2/pdf/sheet_06.pdf
```

### "'hermes' command not found"

If you need the Hermes Agent CLI alongside DualRAG:
```bash
# Install hermes-agent into the same venv
uv pip install -e /home/ubuntu/projects/hermes-agent

# Verify both work:
hermes --version    # → Hermes Agent
dualrag --help      # → DualRAG pipeline
```

---

## 10. Development

### Running Tests

```bash
# Run all tests
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_chunker.py -v
```

### Linting

```bash
# Check for issues
uv run ruff check src/

# Auto-fix what's possible
uv run ruff check src/ --fix
```

### Verify the Package Imports Correctly

```bash
uv run python -c "
from hermes_bedrock_agent.config import config
from hermes_bedrock_agent.clients.bedrock import BedrockLLMAdapter
from hermes_bedrock_agent.knowledge_base.schemas import Chunk, QAAnswerResponse
from hermes_bedrock_agent.retrieval.query_router import answer
print('All imports OK')
"
```

### Demo Scripts

```bash
# Demo: Full evidence flow (shows each step of QA)
uv run python scripts/demo_qa_evidence_flow.py "発注データ"

# Demo: Graph extraction (test on one sheet)
uv run python scripts/demo_graph_extraction.py outputs/reparse_wb2/vlm_parsed/sheet_06.md

# Demo: Verify project isolation
uv run python scripts/verify_project_isolation.py
```

### Adding Support for a New Document Type

To add a new parser (e.g., for Word documents), you would:

1. Create `src/hermes_bedrock_agent/parsing/word_parser.py`
2. Implement a function that converts .docx → Markdown
3. Add the file type to `s3_discovery.py`'s classification logic
4. Hook it into the `parse` command in `cli.py`

The knowledge base construction (Stage 2) and QA (Stage 3) work on Markdown input regardless of the source format, so you only need to change Stage 1.

---

## License

Internal use only.
