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
    case "$1" in
        tmux)
            tmux -V 2>/dev/null | head -n1 || echo "unknown"
            ;;
        ffmpeg)
            ffmpeg -version 2>/dev/null | head -n1 | sed 's/ Copyright.*$//' || echo "unknown"
            ;;
        *)
            "$1" --version 2>/dev/null | head -n1 || echo "unknown"
            ;;
    esac
}

# Run a build command quietly, but never silently. Output goes to a temp file;
# if the command fails, the tail of that file is printed together with the exit
# code. Without this a build that failed and a build that worked look exactly
# the same on the terminal, and the install goes on with the old binary in place.
#
# A step marked --quiet-fail is one the caller expects to fail and retry another
# way (the stale-lockfile fallback). It stays silent, but its log is kept and
# remembered: if the retry fails too, that log holds the root cause, and the
# retry's own output only shows the symptom.
QUIET_ATTEMPT_LOG=""

run_build_step() {
    local quiet_fail=false
    if [ "$1" = "--quiet-fail" ]; then
        quiet_fail=true
        shift
    fi

    local label="$1"
    shift

    local tmpdir="${TMPDIR:-/tmp}"
    tmpdir="${tmpdir%/}"

    local log
    log=$(mktemp "$tmpdir/frago-build-XXXXXX") || {
        # No temp file available - run it out loud instead.
        "$@"
        return $?
    }

    local status=0
    "$@" >"$log" 2>&1 || status=$?

    if [ "$status" -eq 0 ]; then
        rm -f "$log"
        # The retry worked, so the earlier attempt's log has served its purpose.
        if [ -n "$QUIET_ATTEMPT_LOG" ]; then
            rm -f "$QUIET_ATTEMPT_LOG"
        fi
        QUIET_ATTEMPT_LOG=""
        return 0
    fi

    if [ "$quiet_fail" = true ]; then
        # Silent, but the log stays: the retry may need to point back at it.
        QUIET_ATTEMPT_LOG="$log"
        return "$status"
    fi

    # Everything below goes to stderr: the log path matters most exactly when
    # someone is redirecting the output to a file.
    printf "\n" >&2
    print_error "$label failed (exit $status). Last 30 lines:"
    if [ -s "$log" ]; then
        tail -n 30 "$log" >&2
    else
        printf "${DIM}   (this step produced no output)${RESET}\n" >&2
    fi
    printf "${DIM}   Full output kept at: %s${RESET}\n" "$log" >&2

    if [ -n "$QUIET_ATTEMPT_LOG" ] && [ -f "$QUIET_ATTEMPT_LOG" ]; then
        printf "${DIM}   The attempt before it kept its own log at: %s${RESET}\n" \
            "$QUIET_ATTEMPT_LOG" >&2
    fi

    return "$status"
}

detect_platform() {
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    case "$OS" in
        Linux*)
            OS_FAMILY="linux"
            if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
                PLATFORM="WSL"
            else
                PLATFORM="Linux"
            fi
            ;;
        Darwin*)
            OS_FAMILY="macos"
            PLATFORM="macOS"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS_FAMILY="windows"
            PLATFORM="Windows (POSIX shell)"
            ;;
        *)
            print_error "Unsupported operating system: $OS"
            exit 1
            ;;
    esac
}

detect_network_mirror() {
    if [ "${FRAGO_INSTALL_SOURCE:-auto}" = "official" ]; then
        return 0
    fi
    if [ "${FRAGO_INSTALL_SOURCE:-auto}" = "cn" ] || [ "${FRAGO_INSTALL_SOURCE:-auto}" = "mirror" ]; then
        export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
        export UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone}"
        print_success "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
        return 0
    fi
    if command_exists curl && ! curl -fsSLI --connect-timeout 3 --max-time 3 "https://github.com/astral-sh/uv" >/dev/null 2>&1; then
        export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
        export UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone}"
        print_success "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Installation Functions
# ═══════════════════════════════════════════════════════════════════════════════

install_dependencies() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

    if ! command_exists git || ! command_exists tmux || ! command_exists ffmpeg || ! command_exists uv; then
        if [ -f "./install.sh" ]; then
            sh ./install.sh --no-start
        fi
    fi

    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

    for req_cmd in git tmux ffmpeg uv; do
        if command_exists "$req_cmd"; then
            version=$(get_version "$req_cmd")
            print_success "$req_cmd ($version)"
        else
            print_error "$req_cmd installation failed"
            exit 1
        fi
    done
}

install_frago_local() {
    export PATH="$HOME/.local/bin:$PATH"

    print_step "Building frago from source..."

    # Clean previous builds
    rm -rf dist/ >/dev/null 2>&1 || true

    # Build wheel
    run_build_step "uv build" uv build

    # Find and install the wheel
    WHEEL=$(find dist -name "*.whl" | head -n1)
    if [ -z "$WHEEL" ]; then
        print_error "Build failed - no wheel found"
        exit 1
    fi

    # Install with force to replace any existing version
    run_build_step "uv tool install" uv tool install "$WHEEL" --force
    uv tool update-shell >/dev/null 2>&1 || true

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
    detect_network_mirror

    print_section "Dependencies"
    install_dependencies

    print_section "Build"
    install_frago_local

    print_next_steps
    launch_frago
}

main "$@"
