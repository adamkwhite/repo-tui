#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$SCRIPT_DIR/src" "$SCRIPT_DIR/venv/bin/python3" -m repo_tui.app "$@"
