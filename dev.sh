#!/bin/bash
# Development script with hot reload
# Uses watchdog to monitor src/ for changes and auto-restart

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/repo-tui-dev.log"

# Clear old log
> "$LOG_FILE"

echo "Starting repo-tui in dev mode with hot reload..." | tee -a "$LOG_FILE"
echo "Logging to $LOG_FILE" | tee -a "$LOG_FILE"

# Check if watchdog is installed
if ! "$SCRIPT_DIR/venv/bin/python3" -c "import watchdog" 2>/dev/null; then
    echo "Installing watchdog for hot reload..." | tee -a "$LOG_FILE"
    "$SCRIPT_DIR/venv/bin/pip" install watchdog --quiet 2>&1 | tee -a "$LOG_FILE"
fi

# Use watchmedo to auto-restart on file changes
cd "$SCRIPT_DIR"
echo "Starting watchmedo..." | tee -a "$LOG_FILE"
PYTHONPATH="$SCRIPT_DIR/src" "$SCRIPT_DIR/venv/bin/watchmedo" auto-restart \
    --directory="$SCRIPT_DIR/src" \
    --pattern="*.py" \
    --recursive \
    -- \
    "$SCRIPT_DIR/venv/bin/python3" -m repo_tui.app "$@" 2>&1 | tee -a "$LOG_FILE"
