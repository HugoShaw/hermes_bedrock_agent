#!/usr/bin/env bash
# Thin wrapper around the hermes-bedrock-agent CLI.
# Activates the project venv and delegates all arguments to the 'hermes-bedrock-agent' entry point.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$PROJECT_ROOT/.venv/bin/activate"

hermes-bedrock-agent "$@"
