#!/usr/bin/env bash
# Thin wrapper around the dualrag CLI.
# Activates the project venv and delegates all arguments to the 'dualrag' entry point.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

source "$PROJECT_ROOT/.venv/bin/activate"

dualrag "$@"
