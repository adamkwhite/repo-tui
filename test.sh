#!/bin/bash
# Run tests with proper PYTHONPATH and ensure terminal cleanup

cleanup() {
    # Force disable mouse tracking
    printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?25h'
}

# Register cleanup on exit
trap cleanup EXIT INT TERM

cd "$(dirname "$0")"
PYTHONPATH=src ./venv/bin/pytest tests/ -v "$@"

# Explicit cleanup
cleanup
