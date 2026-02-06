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
# GitHub Configuration
# ═══════════════════════════════════════════════════════════════════════════════

GITHUB_OWNER="tsaijamey"
GITHUB_REPO="frago"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases"

# Download mirrors (tried in order, China-friendly first)
DOWNLOAD_MIRRORS="https://mirror.ghproxy.com/ https://ghproxy.net/ "

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

check_node() {
    if command_exists node; then
        version=$(get_version node)
        print_success "Node.js $version"
    else
        print_error "Node.js not found (required)"
        print_info "Install from: https://nodejs.org/ or use 'nvm install --lts'"
        exit 1
    fi
}

get_latest_version() {
    # Try gh CLI first (if available)
    if command_exists gh; then
        version=$(gh release view --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --json tagName -q '.tagName' 2>/dev/null | sed 's/^v//')
        if [ -n "$version" ]; then
            echo "$version"
            return 0
        fi
    fi

    # Fallback to GitHub API
    if command_exists curl; then
        version=$(curl -s "${GITHUB_API_URL}/latest" | grep '"tag_name"' | sed 's/.*"v\([^"]*\)".*/\1/')
    elif command_exists wget; then
        version=$(wget -qO- "${GITHUB_API_URL}/latest" | grep '"tag_name"' | sed 's/.*"v\([^"]*\)".*/\1/')
    fi

    if [ -n "$version" ]; then
        echo "$version"
        return 0
    fi

    return 1
}

get_asset_name() {
    version="$1"
    case "$PLATFORM-$ARCH" in
        macOS-arm64)   echo "frago_${version}_aarch64-apple-darwin.tar.gz" ;;
        macOS-x86_64)  echo "frago_${version}_x86_64-apple-darwin.tar.gz" ;;
        Linux-x86_64)  echo "frago_${version}_x86_64-unknown-linux-gnu.AppImage" ;;
        Linux-aarch64) echo "frago_${version}_aarch64-unknown-linux-gnu.AppImage" ;;
        WSL-x86_64)    echo "frago_${version}_x86_64-unknown-linux-gnu.AppImage" ;;
        WSL-aarch64)   echo "frago_${version}_aarch64-unknown-linux-gnu.AppImage" ;;
        *)             echo "" ;;
    esac
}

get_install_dir() {
    case "$PLATFORM" in
        macOS)
            # Prefer system Applications, fallback to user Applications
            if [ -w "/Applications" ]; then
                echo "/Applications"
            else
                echo "$HOME/Applications"
            fi
            ;;
        Linux|WSL)   echo "$HOME/.local/bin" ;;
        *)           echo "$HOME/.frago/client" ;;
    esac
}

download_with_mirrors() {
    url="$1"
    dest="$2"

    # Try each mirror in order
    for mirror in $DOWNLOAD_MIRRORS ""; do
        full_url="${mirror}${url}"
        if command_exists curl; then
            if curl -fsSL --connect-timeout 10 -o "$dest" "$full_url" 2>/dev/null; then
                return 0
            fi
        elif command_exists wget; then
            if wget -q --timeout=10 -O "$dest" "$full_url" 2>/dev/null; then
                return 0
            fi
        fi
    done

    return 1
}

create_linux_desktop_entry() {
    app_path="$1"
    desktop_dir="$HOME/.local/share/applications"
    mkdir -p "$desktop_dir"

    cat > "$desktop_dir/frago.desktop" << EOF
[Desktop Entry]
Name=frago
Comment=AI-driven browser automation
Exec=$app_path
Icon=frago
Terminal=false
Type=Application
Categories=Development;Utility;
StartupWMClass=frago
EOF

    # Update desktop database if available
    command_exists update-desktop-database && update-desktop-database "$desktop_dir" 2>/dev/null || true
}

add_to_macos_dock() {
    app_path="$1"

    # Check if already in Dock
    if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "frago.app"; then
        return 0
    fi

    # Add to Dock
    defaults write com.apple.dock persistent-apps -array-add \
        "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$app_path</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"

    # Restart Dock to apply changes
    killall Dock 2>/dev/null || true
}

download_client() {
    print_step "Checking latest version..."
    VERSION=$(get_latest_version)

    if [ -z "$VERSION" ]; then
        print_warning "Could not fetch version (skipping client download)"
        return 1
    fi

    ASSET=$(get_asset_name "$VERSION")
    if [ -z "$ASSET" ]; then
        print_warning "No desktop client available for $PLATFORM-$ARCH"
        return 1
    fi

    INSTALL_DIR=$(get_install_dir)
    mkdir -p "$INSTALL_DIR"

    DOWNLOAD_URL="https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/v${VERSION}/${ASSET}"

    # Create temp directory for download
    TEMP_DIR=$(mktemp -d)
    ARCHIVE_PATH="$TEMP_DIR/$ASSET"

    printf "\r"
    print_step "Downloading v$VERSION..."

    if ! download_with_mirrors "$DOWNLOAD_URL" "$ARCHIVE_PATH"; then
        rm -rf "$TEMP_DIR"
        print_warning "Download failed (skipping client)"
        return 1
    fi

    printf "\r"
    print_step "Installing..."

    case "$PLATFORM" in
        macOS)
            # Extract tar.gz and move .app bundle
            tar -xzf "$ARCHIVE_PATH" -C "$TEMP_DIR" 2>/dev/null
            APP_PATH=$(find "$TEMP_DIR" -name "*.app" -type d | head -n1)
            if [ -n "$APP_PATH" ]; then
                rm -rf "$INSTALL_DIR/frago.app" 2>/dev/null
                mv "$APP_PATH" "$INSTALL_DIR/frago.app"
                # Fix executable permission and re-sign
                chmod +x "$INSTALL_DIR/frago.app/Contents/MacOS/"* 2>/dev/null || true
                xattr -cr "$INSTALL_DIR/frago.app" 2>/dev/null || true
                codesign -fs - "$INSTALL_DIR/frago.app" 2>/dev/null || true
                # Add to Dock
                add_to_macos_dock "$INSTALL_DIR/frago.app"
                print_done "Installed to $INSTALL_DIR/frago.app (added to Dock)"
            else
                print_warning "Could not find .app bundle"
            fi
            ;;
        Linux|WSL)
            # AppImage - just copy and make executable
            DEST="$INSTALL_DIR/frago.AppImage"
            mv "$ARCHIVE_PATH" "$DEST"
            chmod +x "$DEST"
            create_linux_desktop_entry "$DEST"
            print_done "Installed to ~/.local/bin/frago.AppImage"
            ;;
        *)
            print_warning "Unsupported platform for client install"
            ;;
    esac

    # Save installed version
    mkdir -p "$HOME/.frago"
    echo "$VERSION" > "$HOME/.frago/client_version"

    rm -rf "$TEMP_DIR"
    return 0
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
    printf "    ${BOLD}frago client start${RESET}  Launch the desktop app\n"
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
    check_node
    install_frago

    print_section "Desktop Client"
    download_client

    print_next_steps
    launch_frago
}

main "$@"
