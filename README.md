# hermes-bedrock-agent

A CLI tool and Python library for querying Amazon Bedrock Knowledge Bases.
Supports single and multiple KBs with parallel fetching, three merge strategies,
deduplication, and both human-readable and JSON output.

## Features

- Query one or more Bedrock Knowledge Bases with a single command
- Parallel fetch across multiple KBs using a thread pool
- Three result-merge strategies: score, round_robin, kb_order
- Automatic deduplication of identical chunks across KBs
- Rich colored terminal output or structured JSON output
- Compare results across KBs side-by-side
- Zero-boilerplate .env config — one line per KB

## Requirements

- Python 3.11+
- AWS credentials configured (any standard method: ~/.aws/credentials, env vars, instance role)
- One or more Amazon Bedrock Knowledge Bases already provisioned

## Installation

    # Clone and create a venv
    git clone <repo-url> hermes-bedrock-agent
    cd hermes-bedrock-agent
    python3 -m venv .venv
    source .venv/bin/activate

    # Install the package
    pip install -e .

    # Install dev dependencies (for tests and linting)
    pip install -e ".[dev]"

## Configuration

Copy .env.example to .env and fill in your values:

    cp .env.example .env

### Multi-KB setup (preferred)

Use comma-separated "label:id" pairs in BEDROCK_KNOWLEDGE_BASES:

    AWS_REGION=ap-northeast-1
    BEDROCK_KNOWLEDGE_BASES=docs:ABCDE12345,sales:FGHIJ67890,support:KLMNO11111

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

## Usage

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

    # Query all configured KBs, top 10 results, score-sorted
    hermes-bedrock-agent ask "How do I reset my password?" -k 10

    # Query only one specific KB
    hermes-bedrock-agent ask "pricing plans" --kb ABCDE12345

    # Round-robin merge so each KB contributes equally
    hermes-bedrock-agent ask "onboarding steps" --merge round_robin

    # JSON output for piping to jq or other tools
    hermes-bedrock-agent ask "refund process" --json | jq '.results[].text'

### list-kbs — show configured knowledge bases

    hermes-bedrock-agent list-kbs
    hermes-bedrock-agent list-kbs --json

### compare — query each KB separately and show side-by-side

Useful for evaluating which KB surfaces better results for a given query.

    hermes-bedrock-agent compare "What are the shipping options?"

Options:

    --top-k  / -k   N   Chunks per KB (1-20, default 3)
    --json              JSON output

## Merge strategies

score       (default) All results pooled and sorted by relevance score descending.
            Best when all KBs use the same embedding model and score scale.

round_robin Interleaves one result from each KB in turn: KB1[0], KB2[0], KB3[0],
            KB1[1], KB2[1], ... Gives each KB equal representation regardless of score.

kb_order    Results appended KB by KB in the order they are configured.
            Useful when KBs have a known priority order.

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
        },
        ...
      ]
    }

The --json flag on compare returns:

    {
      "query": "your question",
      "per_kb": {
        "ABCDE12345": [ ... ],
        "FGHIJ67890": [ ... ]
      }
    }

## Shell wrapper

bin/kb_query.sh activates the project venv and delegates all arguments to the
CLI entry point. Useful when you want to invoke the tool without manually
activating the venv:

    ./bin/kb_query.sh ask "What is the SLA?"

## Python library usage

You can also import and use the clients directly in your own code:

    from hermes_bedrock_agent.config import Settings
    from hermes_bedrock_agent.kb_client import MultiKBClient

    # Loads from environment / .env automatically
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
        print()

    # Query a specific KB by ID
    results = client.retrieve_from("ABCDE12345", "pricing", number_of_results=3)

    # Build Settings programmatically (no .env needed)
    from hermes_bedrock_agent.config import KBEntry, Settings

    settings = Settings(
        aws_region="us-east-1",
        knowledge_bases=[
            KBEntry(kb_id="ABCDE12345", label="docs"),
            KBEntry(kb_id="FGHIJ67890", label="sales"),
        ],
    )

## Project structure

    hermes-bedrock-agent/
    ├── src/hermes_bedrock_agent/
    │   ├── config.py          Settings and KBEntry dataclasses; env parsing
    │   ├── kb_client.py       BedrockKBClient, MultiKBClient, KBResult
    │   └── main.py            Typer CLI: ask, list-kbs, compare commands
    ├── tests/
    │   ├── test_config.py     39 unit tests (no AWS calls required)
    │   └── test_kb_client.py
    ├── bin/
    │   └── kb_query.sh        Shell wrapper
    ├── .env.example           Environment variable reference
    └── pyproject.toml

## Running tests

    source .venv/bin/activate
    pytest

All tests use mocks — no AWS credentials or live KBs needed.

## Linting

    ruff check src/ tests/
    ruff check src/ tests/ --fix    # auto-fix

## Environment variable reference

Variable                      Required   Default            Description
-----------------------------+----------+-------------------+----------------------------------
AWS_REGION                    No         ap-northeast-1     AWS region for Bedrock
BEDROCK_KNOWLEDGE_BASES       One of     —                  Multi-KB: "label:id,label:id,..."
BEDROCK_KNOWLEDGE_BASE_ID     these      —                  Legacy single-KB ID
BEDROCK_KNOWLEDGE_BASE_LABEL  No         ""                 Label for the single-KB setup
AWS_ACCESS_KEY_ID             No*        —                  AWS credentials (if not using role)
AWS_SECRET_ACCESS_KEY         No*        —                  AWS credentials
AWS_SESSION_TOKEN             No*        —                  Only for temporary credentials

* Required unless credentials come from instance role, ~/.aws/credentials, or another source.

## License

MIT
