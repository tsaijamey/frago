#!/bin/sh
# Isolated macOS sandbox test for frago (zero disk residue, uses temporary HOME)
#
# Usage:
#   ./scripts/install/test-macos-sandbox.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SANDBOX_HOME="$(mktemp -d -t frago-macos-sandbox.XXXXXX)"
trap 'rm -rf "$SANDBOX_HOME"' EXIT

export HOME="$SANDBOX_HOME"
export XDG_CONFIG_HOME="$SANDBOX_HOME/.config"
export XDG_DATA_HOME="$SANDBOX_HOME/.local/share"
export XDG_CACHE_HOME="$SANDBOX_HOME/.cache"
export PYTHONPATH="$REPO_ROOT/src"

if [ -z "$PYTHON_BIN" ]; then
    if command -v frago >/dev/null 2>&1; then
        SHEBANG_PY="$(head -n 1 "$(command -v frago)" | sed 's/^#!//')"
        if [ -x "$SHEBANG_PY" ]; then
            PYTHON_BIN="$SHEBANG_PY"
        fi
    fi
fi
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"

echo "━━━ macOS Isolated Sandbox Test ━━━"
echo "Sandbox HOME: $SANDBOX_HOME"
"$PYTHON_BIN" "$REPO_ROOT/docker/verify_env.py" --expect macos
