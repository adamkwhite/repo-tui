#!/bin/bash
# Development script with hot reload
# Uses watchdog to monitor src/ for changes and auto-restart

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if watchdog is installed
if ! "$SCRIPT_DIR/venv/bin/python3" -c "import watchdog" 2>/dev/null; then
    echo "Installing watchdog for hot reload..."
    "$SCRIPT_DIR/venv/bin/pip" install watchdog --quiet
fi

# Use watchmedo to auto-restart on file changes
cd "$SCRIPT_DIR"
PYTHONPATH="$SCRIPT_DIR/src" "$SCRIPT_DIR/venv/bin/watchmedo" auto-restart \
    --directory="$SCRIPT_DIR/src" \
    --pattern="*.py" \
    --recursive \
    -- \
    "$SCRIPT_DIR/venv/bin/python3" -m repo_tui.app "$@"
