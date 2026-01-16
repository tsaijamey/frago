#!/bin/sh
# frago installation script for Linux, macOS, and WSL
#
# Usage:
#   curl -fsSL https://frago.ai/install.sh | sh
#   wget -qO- https://frago.ai/install.sh | sh

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

# Gradient colors for banner (cyan → blue → purple)
print_gradient_line() {
    line="$1"
    index="$2"
    if [ "$USE_COLOR" = true ]; then
        case $index in
            0) printf '\033[38;2;0;255;255m%s\033[0m\n' "$line" ;;
            1) printf '\033[38;2;0;191;255m%s\033[0m\n' "$line" ;;
            2) printf '\033[38;2;65;105;225m%s\033[0m\n' "$line" ;;
            3) printf '\033[38;2;138;43;226m%s\033[0m\n' "$line" ;;
            4) printf '\033[38;2;148;0;211m%s\033[0m\n' "$line" ;;
            5) printf '\033[38;2;186;85;211m%s\033[0m\n' "$line" ;;
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
            print_info "For Windows, use: irm https://frago.ai/install.ps1 | iex"
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

install_frago() {
    export PATH="$HOME/.local/bin:$PATH"

    if command_exists frago; then
        version=$(get_version frago)
        print_step "Upgrading frago..."
        uv tool upgrade frago-cli >/dev/null 2>&1 || uv tool install frago-cli --force >/dev/null 2>&1
        new_version=$(get_version frago)
        print_done "frago $new_version"
    else
        print_step "Installing frago..."
        uv tool install frago-cli >/dev/null 2>&1

        if command_exists frago; then
            version=$(get_version frago)
            print_done "frago $version"
        else
            print_error "frago installation failed"
            exit 1
        fi
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
    printf "    ${BOLD}frago start${RESET}       Start frago and open Web UI\n"
    printf "    ${BOLD}frago --help${RESET}      Show all available commands\n"
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
    # (restart can fail due to process termination issues)
    frago server stop >/dev/null 2>&1 || true
    sleep 2  # Give port time to be released
    frago server start >/dev/null 2>&1 || true

    # Wait for server to be ready before opening browser
    if wait_for_server; then
        printf "  ${DIM}Opening browser...${RESET}\n"
        echo ""
        frago start --no-browser >/dev/null 2>&1 || true  # Ensure server is tracked
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
    print_banner

    print_section "Environment"
    detect_platform
    print_success "$PLATFORM ($ARCH)"

    print_section "Dependencies"
    install_uv
    install_frago

    print_next_steps
    launch_frago
}

main "$@"
