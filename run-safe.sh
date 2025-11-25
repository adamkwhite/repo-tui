#!/bin/bash
# Wrapper script that guarantees terminal cleanup

cleanup() {
    # Force disable mouse tracking
    printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?25h'
}

# Register cleanup on exit
trap cleanup EXIT INT TERM

# Run the app
"$(dirname "$0")/run.sh" "$@"

# Explicit cleanup
cleanup
