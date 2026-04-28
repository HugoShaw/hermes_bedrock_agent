# hermes-bedrock-agent

A CLI tool and Python library for querying Amazon Bedrock Knowledge Bases and analyzing
company documents to visualize hierarchical and cross-system relationships as Mermaid
flowcharts.

## Features

- Query one or more Bedrock Knowledge Bases with a single command
- Parallel fetch across multiple KBs using a thread pool
- Three result-merge strategies: score, round_robin, kb_order
- Automatic deduplication of identical chunks across KBs
- Rich colored terminal output or structured JSON output
- Compare results across KBs side-by-side
- Zero-boilerplate .env config — one line per KB
- doc-analyze: upload company docs to S3, extract entity/relationship graph,
  render a color-coded Mermaid flowchart (hierarchy, integration, data-flow)

## Requirements

- Python 3.11+
- AWS credentials configured (any standard method: ~/.aws/credentials, env vars, instance role)
- One or more Amazon Bedrock Knowledge Bases already provisioned (for ask/compare/list-kbs)
- An S3 bucket you can read/write (for doc-analyze)

## Installation

    git clone <repo-url> hermes-bedrock-agent
    cd hermes-bedrock-agent
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .

    # dev dependencies (tests + linting)
    pip install -e ".[dev]"

## Configuration

Copy .env.example to .env and fill in your values:

    cp .env.example .env

### Multi-KB setup (preferred)

    AWS_REGION=ap-northeast-1
    BEDROCK_KNOWLEDGE_BASES=docs:ABCDE12345,sales:FGHIJ67890,support:KLMNO11111
    BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-6   # used by doc-analyze
    GRAPHRAG_S3_BUCKET=my-company-docs-bucket       # used by doc-analyze

Labels are optional — bare IDs work too:

    BEDROCK_KNOWLEDGE_BASES=ABCDE12345,FGHIJ67890

### Single-KB setup (legacy)

    AWS_REGION=ap-northeast-1
    BEDROCK_KNOWLEDGE_BASE_ID=ABCDE12345
    BEDROCK_KNOWLEDGE_BASE_LABEL=my-kb      # optional

If both are set, BEDROCK_KNOWLEDGE_BASES takes priority.

### AWS credentials

The tool uses boto3 and picks up credentials from any standard source:

- Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
- Shared credentials file: ~/.aws/credentials
- IAM role attached to the instance or container
- AWS SSO / AWS Vault / any credential helper

Temporary credentials also work — add AWS_SESSION_TOKEN to .env if needed.

---

## doc-analyze — Company Document Relationship Analyzer

This feature reads all documents from an S3 directory, uses Claude (via Amazon Bedrock)
to extract companies, subsidiaries, systems, and departments from the content, and then
renders a Mermaid flowchart that visualizes the hierarchical and cross-system relationships.

### Supported file formats

  pdf, docx, txt, md, json, csv

### Step-by-step guide

#### Step 1 — Confirm your .env is set up

You need at least these two variables in .env (or as shell env vars):

    GRAPHRAG_S3_BUCKET=my-company-docs-bucket
    AWS_REGION=ap-northeast-1

The Bedrock model defaults to anthropic.claude-sonnet-4-6. Override with:

    BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-6

#### Step 2 — Upload your documents to S3

Option A: use the built-in upload command

    hermes-bedrock-agent doc-analyze upload \
        org_chart.pdf \
        system_architecture.docx \
        subsidiary_list.txt \
        --prefix company-docs/

    # upload only, skip auto-analysis
    hermes-bedrock-agent doc-analyze upload report.pdf --prefix company-docs/ --no-analyze

Option B: upload manually with the AWS CLI

    aws s3 cp ./docs/ s3://my-company-docs-bucket/company-docs/ --recursive

Files can be nested in sub-folders under the prefix — the tool lists recursively.

#### Step 3 — Check what is in the S3 prefix

    hermes-bedrock-agent doc-analyze list --prefix company-docs/

Example output:

    ╭──────────────────────────────────────────────────────────────╮
    │ s3://my-company-docs-bucket/company-docs/                    │
    ├──────────────────────────┬──────────┬───────────────────────┤
    │ File                     │     Size │ Last Modified         │
    ├──────────────────────────┼──────────┼───────────────────────┤
    │ org_chart.pdf            │  128.4 KB│ 2025-04-28 07:30 UTC  │
    │ system_architecture.docx │   54.1 KB│ 2025-04-28 07:31 UTC  │
    │ subsidiary_list.txt      │    2.8 KB│ 2025-04-28 07:31 UTC  │
    ╰──────────────────────────┴──────────┴───────────────────────╯
    3 object(s) total

#### Step 4 — Run the analysis

    hermes-bedrock-agent doc-analyze run --prefix company-docs/

With all options shown:

    hermes-bedrock-agent doc-analyze run \
        --prefix    company-docs/ \
        --bucket    my-company-docs-bucket \
        --title     "Acme Corp Structure 2025" \
        --output    ./acme_structure.md \
        --model     anthropic.claude-sonnet-4-6 \
        --max-chars 8000

Option descriptions:

    --prefix     S3 prefix (directory) to read documents from.
                 Default: company-docs/
    --bucket     S3 bucket name. Default: $GRAPHRAG_S3_BUCKET env var.
    --title      Title shown at the top of the Mermaid diagram.
                 Default: "Company Document Relationship Map"
    --output     Path for the output .md file.
                 Default: ./doc_analysis_<timestamp>.md
    --model      Bedrock model ID for the analysis LLM call.
                 Default: $BEDROCK_MODEL_ID or anthropic.claude-sonnet-4-6
    --max-chars  Maximum characters extracted per file to send to Claude.
                 Raise this for more detail; lower it to stay within token limits.
                 Default: 8000

#### Step 5 — Open and preview the output

The command writes a Markdown file with:
  1. A plain-text summary of what was found
  2. A Mermaid flowchart code block

Open the file in any Markdown viewer that renders Mermaid:

  VS Code     — install the "Markdown Preview Mermaid Support" extension,
                then open the .md file and hit Ctrl+Shift+V
  GitHub      — push the file; GitHub renders Mermaid natively in README/docs
  Obsidian    — enable the Mermaid plugin; Mermaid renders in the preview pane
  Mermaid Live — paste the diagram block at https://mermaid.live for instant preview

#### Example output file

    # Acme Corp Structure 2025

    **Summary:** Acme Corp owns two subsidiaries (Acme Asia, Acme Europe).
    Acme Asia operates an ERP system that synchronises data with the CRM.
    The IT Department manages both systems.

    ```mermaid
    %% Title: Acme Corp Structure 2025
    flowchart TD
        classDef company    fill:#4A90D9,color:#fff,stroke:#2C5F8A
        classDef subsidiary fill:#7BB3E8,color:#fff,stroke:#4A90D9
        classDef system     fill:#50C878,color:#fff,stroke:#2D8A4E
        classDef department fill:#FFB347,color:#fff,stroke:#E07000

        subgraph Companies
            corp["Acme Corp"]
            sub1["Acme Asia"]
            sub2["Acme Europe"]
        end

        subgraph Systems
            erp["ERP System"]
            crm["CRM System"]
        end

        subgraph Departments
            it["IT Department"]
        end

        class corp company
        class sub1,sub2 subsidiary
        class erp,crm system
        class it department

        corp -->|"owns"| sub1
        corp -->|"owns"| sub2
        sub1 -->|"operates"| erp
        erp <-->|"syncs data"| crm
        it ==>|"manages"| erp
        it ==>|"manages"| crm
    ```

#### Node and edge color legend

    Node type     Color         Meaning
    company       Blue          Top-level legal entity / parent company
    subsidiary    Light blue    Subsidiary or regional entity under a parent
    system        Green         Software system or platform
    module        Light green   Sub-module or component of a system
    department    Orange        Business unit or functional team
    team          Yellow        Sub-team within a department
    other         Grey          Anything not fitting the above categories

    Edge style    Meaning
    -->           Hierarchical ownership or directional relationship
    <-->          Bidirectional / mutual relationship (e.g. data sync)
    ==>           Business process dependency (thick arrow)

### Quick-start (one-liner after upload)

    hermes-bedrock-agent doc-analyze upload *.pdf *.docx --prefix company-docs/

This uploads every PDF and DOCX in the current directory and immediately runs the analysis.
The output .md file path is printed when complete.

### Common errors

    "No files found in s3://..."
      The prefix does not exist or the bucket is wrong.
      Run: doc-analyze list --prefix <your-prefix>

    "Unsupported file type"
      Convert the file to one of: pdf, docx, txt, md, json, csv

    "parse_error: could not parse JSON from LLM response"
      The raw LLM response is saved to <output>.raw.txt for inspection.
      Try increasing --max-chars or splitting documents into smaller files.

    AWS credential / permission errors
      The IAM principal needs: s3:GetObject, s3:PutObject, s3:ListBucket
      on the target bucket, plus bedrock:InvokeModel on the chosen model ARN.

---

## Usage — Knowledge Base commands

### ask — query one or more KBs

    hermes-bedrock-agent ask "What is the return policy?"

Options:

    --top-k  / -k   N      Chunks to retrieve per KB (1-20, default 5)
    --merge         STR    Merge strategy: score | round_robin | kb_order (default score)
    --kb            ID     Restrict query to specific KB(s), repeatable:
                             --kb ABCDE12345 --kb FGHIJ67890
    --no-dedup             Disable deduplication of identical chunks
    --json                 Return structured JSON instead of colored output

Examples:

    hermes-bedrock-agent ask "How do I reset my password?" -k 10
    hermes-bedrock-agent ask "pricing plans" --kb ABCDE12345
    hermes-bedrock-agent ask "onboarding steps" --merge round_robin
    hermes-bedrock-agent ask "refund process" --json | jq '.results[].text'

### list-kbs — show configured knowledge bases

    hermes-bedrock-agent list-kbs
    hermes-bedrock-agent list-kbs --json

### compare — query each KB separately and show side-by-side

    hermes-bedrock-agent compare "What are the shipping options?"

Options:

    --top-k  / -k   N   Chunks per KB (1-20, default 3)
    --json              JSON output

## Merge strategies

    score       All results pooled and sorted by relevance score descending.
    round_robin Interleaves one result per KB in turn: KB1[0], KB2[0], KB3[0], KB1[1]...
    kb_order    Results appended KB by KB in the configured order.

## JSON output format

The --json flag on ask returns:

    {
      "query": "your question",
      "results": [
        {
          "text": "retrieved chunk text",
          "score": 0.9123,
          "metadata": { ... },
          "location": { "s3Location": { "uri": "s3://..." } },
          "kb_id": "ABCDE12345",
          "kb_label": "docs"
        }
      ]
    }

## Shell wrapper

bin/kb_query.sh activates the project venv and delegates all arguments to the CLI.
Useful when you want to run without manually activating the venv:

    ./bin/kb_query.sh ask "What is the SLA?"
    ./bin/kb_query.sh doc-analyze run --prefix company-docs/

## Python library usage

    from hermes_bedrock_agent.config import Settings
    from hermes_bedrock_agent.kb_client import MultiKBClient

    settings = Settings.from_env()
    client = MultiKBClient(settings)
    results = client.retrieve(
        "What is the refund policy?",
        number_of_results=5,
        merge_strategy="score",
        deduplicate=True,
    )
    for r in results:
        print(f"[{r.display_source}] score={r.score:.4f}")
        print(r.text)

    # doc-analyze from Python
    from hermes_bedrock_agent.doc_analyze.analyzer import analyze_directory
    from hermes_bedrock_agent.doc_analyze.mermaid_renderer import render_mermaid

    result = analyze_directory(
        bucket="my-company-docs-bucket",
        prefix="company-docs/",
        region="ap-northeast-1",
        model_id="anthropic.claude-sonnet-4-6",
        max_chars_per_file=8000,
    )
    raw_mermaid, full_markdown = render_mermaid(result, title="My Diagram")
    print(full_markdown)

## Project structure

    hermes-bedrock-agent/
    ├── src/hermes_bedrock_agent/
    │   ├── config.py                    Settings and KBEntry dataclasses; env parsing
    │   ├── kb_client.py                 BedrockKBClient, MultiKBClient, KBResult
    │   ├── main.py                      Typer CLI entry point
    │   ├── doc_analyze/
    │   │   ├── analyzer.py              S3 download, text extraction, Bedrock LLM call
    │   │   ├── mermaid_renderer.py      Renders AnalysisResult -> Mermaid flowchart TD
    │   │   └── cmd.py                   Typer sub-commands: run, upload, list
    │   └── graphrag/
    │       ├── extractor.py             Text extraction (pdf/docx/txt/md/json/csv)
    │       └── s3_reader.py             S3 list, download, upload helpers
    ├── tests/
    ├── bin/
    │   └── kb_query.sh
    ├── .env.example
    └── pyproject.toml

## Running tests

    source .venv/bin/activate
    pytest

All tests use mocks — no AWS credentials or live KBs needed.

## Linting

    ruff check src/ tests/
    ruff check src/ tests/ --fix

## Environment variable reference

    Variable                      Required   Default                        Description
    ----------------------------+-----------+-------------------------------+-----------------------------
    AWS_REGION                    No         ap-northeast-1                 AWS region for Bedrock + S3
    BEDROCK_KNOWLEDGE_BASES       One of     -                              Multi-KB: "label:id,..."
    BEDROCK_KNOWLEDGE_BASE_ID     these      -                              Legacy single-KB ID
    BEDROCK_KNOWLEDGE_BASE_LABEL  No         ""                             Label for single-KB setup
    BEDROCK_MODEL_ID              No         anthropic.claude-sonnet-4-6   Model for doc-analyze LLM call
    GRAPHRAG_S3_BUCKET            No*        -                              S3 bucket for doc-analyze
    AWS_ACCESS_KEY_ID             No**       -                              AWS credentials
    AWS_SECRET_ACCESS_KEY         No**       -                              AWS credentials
    AWS_SESSION_TOKEN             No**       -                              Temporary credentials only

    *  Required for doc-analyze unless --bucket is passed on the command line.
    ** Required unless credentials come from instance role or ~/.aws/credentials.

## License

MIT
