#!/bin/sh
# Reset test environment for install.sh testing
#
# This script removes frago and optionally uv to simulate a fresh user environment.
#
# Usage:
#   ./scripts/test-reset.sh          # Remove frago only
#   ./scripts/test-reset.sh --all    # Remove frago + uv (full reset)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { printf "${GREEN}[+]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
error() { printf "${RED}[-]${NC} %s\n" "$1"; }

FULL_RESET=false
if [ "$1" = "--all" ] || [ "$1" = "-a" ]; then
    FULL_RESET=true
fi

echo ""
echo "━━━ Test Environment Reset ━━━"
echo ""

# 1. Stop frago server if running
if command -v frago >/dev/null 2>&1; then
    if frago server status >/dev/null 2>&1; then
        info "Stopping frago server..."
        frago server stop 2>/dev/null || true
    fi
fi

# 2. Uninstall frago via uv tool
if command -v uv >/dev/null 2>&1; then
    if uv tool list 2>/dev/null | grep -q frago-cli; then
        info "Uninstalling frago-cli..."
        uv tool uninstall frago-cli
    else
        warn "frago-cli not installed via uv tool"
    fi
fi

# 3. Remove frago user data (optional - uncomment if needed)
# warn "Removing ~/.frago/ (user data)"
# rm -rf ~/.frago

# 4. Remove frago from PATH locations
if [ -f "$HOME/.local/bin/frago" ]; then
    info "Removing ~/.local/bin/frago"
    rm -f "$HOME/.local/bin/frago"
fi

# 5. Full reset: also remove uv
if [ "$FULL_RESET" = true ]; then
    warn "Full reset: removing uv..."

    # Remove uv binary
    if [ -f "$HOME/.local/bin/uv" ]; then
        info "Removing ~/.local/bin/uv"
        rm -f "$HOME/.local/bin/uv"
        rm -f "$HOME/.local/bin/uvx"
    fi

    if [ -f "$HOME/.cargo/bin/uv" ]; then
        info "Removing ~/.cargo/bin/uv"
        rm -f "$HOME/.cargo/bin/uv"
        rm -f "$HOME/.cargo/bin/uvx"
    fi

    # Remove uv cache and data
    if [ -d "$HOME/.cache/uv" ]; then
        info "Removing ~/.cache/uv"
        rm -rf "$HOME/.cache/uv"
    fi

    if [ -d "$HOME/.local/share/uv" ]; then
        info "Removing ~/.local/share/uv"
        rm -rf "$HOME/.local/share/uv"
    fi
fi

echo ""
echo "━━━ Verification ━━━"
echo ""

# Verify removal
if command -v frago >/dev/null 2>&1; then
    error "frago still found: $(which frago)"
else
    info "frago removed successfully"
fi

if [ "$FULL_RESET" = true ]; then
    if command -v uv >/dev/null 2>&1; then
        error "uv still found: $(which uv)"
    else
        info "uv removed successfully"
    fi
fi

echo ""
info "Reset complete. Run install.sh to test:"
echo "    sh install.sh"
echo ""
