#!/bin/sh
# frago LOCAL installation script for development/testing
#
# Usage (run from repository root):
#   ./local_install.sh
#
# This script builds frago from source instead of installing from PyPI.
# Use install.sh for production installations.

set -e

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Check if terminal supports colors
if [ -t 1 ]; then
    USE_COLOR=true
    RESET='\033[0m'
    BOLD='\033[1m'
    DIM='\033[2m'
    CYAN='\033[36m'
    GREEN='\033[32m'
    YELLOW='\033[33m'
    RED='\033[31m'
else
    USE_COLOR=false
    RESET=''
    BOLD=''
    DIM=''
    CYAN=''
    GREEN=''
    YELLOW=''
    RED=''
fi

# Gradient colors for banner (green for local build)
print_gradient_line() {
    line="$1"
    index="$2"
    if [ "$USE_COLOR" = true ]; then
        case $index in
            0) printf '\033[38;2;0;255;127m%s\033[0m\n' "$line" ;;
            1) printf '\033[38;2;0;220;100m%s\033[0m\n' "$line" ;;
            2) printf '\033[38;2;0;180;80m%s\033[0m\n' "$line" ;;
            3) printf '\033[38;2;0;140;60m%s\033[0m\n' "$line" ;;
            4) printf '\033[38;2;0;100;50m%s\033[0m\n' "$line" ;;
            5) printf '\033[38;2;0;70;35m%s\033[0m\n' "$line" ;;
            *) printf '%s\n' "$line" ;;
        esac
    else
        printf '%s\n' "$line"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Output Functions
# ═══════════════════════════════════════════════════════════════════════════════

print_banner() {
    echo ""
    print_gradient_line '███████╗██████╗  █████╗  ██████╗  ██████╗ ' 0
    print_gradient_line '██╔════╝██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗' 1
    print_gradient_line '█████╗  ██████╔╝███████║██║  ███╗██║   ██║' 2
    print_gradient_line '██╔══╝  ██╔══██╗██╔══██║██║   ██║██║   ██║' 3
    print_gradient_line '██║     ██║  ██║██║  ██║╚██████╔╝╚██████╔╝' 4
    print_gradient_line '╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ' 5
    printf "${YELLOW}           [LOCAL BUILD]${RESET}\n"
    echo ""
}

print_section() {
    echo ""
    printf "${CYAN}${BOLD}━━━ %s ━━━${RESET}\n" "$1"
    echo ""
}

print_success() {
    printf "${GREEN} + %s${RESET}\n" "$1"
}

print_info() {
    printf "${DIM}   %s${RESET}\n" "$1"
}

print_warning() {
    printf "${YELLOW} ~ %s${RESET}\n" "$1"
}

print_error() {
    printf "${RED} ✗ %s${RESET}\n" "$1" >&2
}

print_step() {
    printf "${CYAN}   %s${RESET}" "$1"
}

print_done() {
    printf "\r${GREEN} + %s${RESET}\n" "$1"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

get_version() {
    "$1" --version 2>/dev/null | head -n1 || echo "unknown"
}

detect_platform() {
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    case "$OS" in
        Linux*)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                PLATFORM="WSL"
            else
                PLATFORM="Linux"
            fi
            ;;
        Darwin*)
            PLATFORM="macOS"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            print_error "This script is for Unix-like systems"
            print_info "For Windows, use: .\\local_install.ps1"
            exit 1
            ;;
        *)
            print_error "Unsupported operating system: $OS"
            exit 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# Installation Functions
# ═══════════════════════════════════════════════════════════════════════════════

install_uv() {
    if command_exists uv; then
        version=$(get_version uv)
        print_success "uv $version"
        return 0
    fi

    print_step "Installing uv..."

    if command_exists curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    elif command_exists wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    else
        print_error "Neither curl nor wget found"
        exit 1
    fi

    # Source env to get uv in PATH
    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command_exists uv; then
        version=$(get_version uv)
        print_done "uv $version"
    else
        print_error "uv installation failed"
        exit 1
    fi
}

check_node() {
    if command_exists node; then
        version=$(get_version node)
        print_success "Node.js $version"
        return 0
    else
        print_error "Node.js not found (required for building frontend)"
        print_info "Install from: https://nodejs.org/ or use 'nvm install --lts'"
        exit 1
    fi
}

check_pnpm() {
    if command_exists pnpm; then
        version=$(get_version pnpm)
        print_success "pnpm $version"
        return 0
    fi

    print_step "Installing pnpm..."
    npm install -g pnpm >/dev/null 2>&1

    if command_exists pnpm; then
        version=$(get_version pnpm)
        print_done "pnpm $version"
    else
        print_error "pnpm installation failed"
        exit 1
    fi
}

build_frontend() {
    print_step "Building frontend..."

    cd src/frago/client
    pnpm install --frozen-lockfile >/dev/null 2>&1 || pnpm install >/dev/null 2>&1
    pnpm build >/dev/null 2>&1
    cd - >/dev/null

    print_done "Frontend built"
}

install_frago_local() {
    export PATH="$HOME/.local/bin:$PATH"

    print_step "Building frago from source..."

    # Clean previous builds
    rm -rf dist/ >/dev/null 2>&1 || true

    # Build wheel
    uv build >/dev/null 2>&1

    # Find and install the wheel
    WHEEL=$(find dist -name "*.whl" | head -n1)
    if [ -z "$WHEEL" ]; then
        print_error "Build failed - no wheel found"
        exit 1
    fi

    # Install with force to replace any existing version
    uv tool install "$WHEEL" --force >/dev/null 2>&1

    if command_exists frago; then
        version=$(get_version frago)
        print_done "frago $version (from source)"
    else
        print_error "frago installation failed"
        exit 1
    fi
}

print_next_steps() {
    print_section "Getting Started"

    printf "  ${DIM}To ensure frago is always available, add to your shell profile:${RESET}\n"
    echo ""

    case "$SHELL" in
        */zsh)
            printf "    ${CYAN}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc${RESET}\n"
            ;;
        */bash)
            printf "    ${CYAN}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc${RESET}\n"
            ;;
        *)
            printf "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}\n"
            ;;
    esac

    echo ""
    printf "  ${DIM}Commands:${RESET}\n"
    printf "    ${BOLD}frago start${RESET}         Start frago and open Web UI\n"
    printf "    ${BOLD}frago --help${RESET}        Show all available commands\n"
    echo ""
}

wait_for_server() {
    # Wait for server to accept connections (max 30 seconds)
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        # Try to connect to the port
        if (echo >/dev/tcp/127.0.0.1/8093) 2>/dev/null; then
            # Port is open, wait a bit more for HTTP to be fully ready
            sleep 2
            return 0
        elif command_exists nc && nc -z 127.0.0.1 8093 2>/dev/null; then
            sleep 2
            return 0
        elif curl -s --connect-timeout 1 "http://127.0.0.1:8093/" >/dev/null 2>&1; then
            sleep 2
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    return 1
}

launch_frago() {
    print_section "Launching"

    export PATH="$HOME/.local/bin:$PATH"
    printf "  ${DIM}Starting frago server...${RESET}\n"

    # Stop any existing server first, then start fresh
    frago server stop >/dev/null 2>&1 || true
    sleep 2  # Give port time to be released
    frago server start >/dev/null 2>&1 || true

    # Wait for server to be ready before opening browser
    if wait_for_server; then
        printf "  ${DIM}Opening browser...${RESET}\n"
        echo ""
        frago start --no-browser >/dev/null 2>&1 || true
        # Open browser directly since server is ready
        if command_exists xdg-open; then
            xdg-open "http://127.0.0.1:8093" >/dev/null 2>&1 &
        elif command_exists open; then
            open "http://127.0.0.1:8093"
        else
            printf "  ${CYAN}Open in browser: http://127.0.0.1:8093${RESET}\n"
        fi
    else
        print_warning "Server did not start in time. Run 'frago start' manually."
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    # Ensure we're in the repository root
    if [ ! -f "pyproject.toml" ] || [ ! -d "src/frago" ]; then
        print_error "This script must be run from the frago repository root"
        exit 1
    fi

    print_banner

    print_section "Environment"
    detect_platform
    print_success "$PLATFORM ($ARCH)"

    print_section "Dependencies"
    install_uv
    check_node
    check_pnpm

    print_section "Build"
    build_frontend
    install_frago_local

    print_next_steps
    launch_frago
}

main "$@"
