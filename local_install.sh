#!/bin/sh
# frago LOCAL installation script for Linux, macOS, and WSL
#
# Usage:
#   ./local_install.sh
#
# NOTE: This script installs from local dist/ directory instead of PyPI

set -e

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Definitions
# ═══════════════════════════════════════════════════════════════════════════════

if [ -t 1 ]; then
    RESET='\033[0m'
    BOLD='\033[1m'
    DIM='\033[2m'
    CYAN='\033[36m'
    GREEN='\033[32m'
    YELLOW='\033[33m'
    RED='\033[31m'
else
    RESET='' BOLD='' DIM='' CYAN='' GREEN='' YELLOW='' RED=''
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Progress Display
# ═══════════════════════════════════════════════════════════════════════════════

TOTAL_STEPS=7
CURRENT_STEP=0

# Print step with dots padding, no newline
# Usage: step "Task name"
step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    task="$1"
    # Calculate padding (40 chars total for task + dots)
    task_len=${#task}
    dots_count=$((38 - task_len))
    dots=$(printf '%*s' "$dots_count" '' | tr ' ' '.')
    printf "${DIM}[%d/%d]${RESET} %s %s " "$CURRENT_STEP" "$TOTAL_STEPS" "$task" "$dots"
}

# Print success result
ok() {
    printf "${GREEN}%s${RESET}\n" "$1"
}

# Print error result and exit
fail() {
    printf "${RED}%s${RESET}\n" "$1"
    exit 1
}

# Print warning result
warn() {
    printf "${YELLOW}%s${RESET}\n" "$1"
}

print_error() {
    printf "${RED}✗ %s${RESET}\n" "$1" >&2
}

# ═══════════════════════════════════════════════════════════════════════════════
# Banner
# ═══════════════════════════════════════════════════════════════════════════════

print_banner() {
    printf '\n'
    printf '\033[38;2;0;255;127m███████╗██████╗  █████╗  ██████╗  ██████╗ \033[0m\n'
    printf '\033[38;2;0;220;100m██╔════╝██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗\033[0m\n'
    printf '\033[38;2;0;180;80m█████╗  ██████╔╝███████║██║  ███╗██║   ██║\033[0m\n'
    printf '\033[38;2;0;140;60m██╔══╝  ██╔══██╗██╔══██║██║   ██║██║   ██║\033[0m\n'
    printf '\033[38;2;0;100;50m██║     ██║  ██║██║  ██║╚██████╔╝╚██████╔╝\033[0m\n'
    printf '\033[38;2;0;70;35m╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ \033[0m\n'
    printf '\n'
    printf "${YELLOW}   [LOCAL INSTALL]${RESET}\n"
    printf '\n'
}

# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

exit_virtualenv() {
    if [ -n "$VIRTUAL_ENV" ]; then
        PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "^$VIRTUAL_ENV" | tr '\n' ':' | sed 's/:$//')
        export PATH
        unset VIRTUAL_ENV
    fi
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

get_version() {
    "$1" --version 2>/dev/null | head -n1 || echo "unknown"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Installation Steps
# ═══════════════════════════════════════════════════════════════════════════════

step_detect_platform() {
    step "Detecting platform"

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
            fail "Use .\\local_install.ps1 for Windows"
            ;;
        *)
            fail "Unsupported: $OS"
            ;;
    esac

    ok "$PLATFORM ($ARCH)"
}

step_check_uv() {
    step "Checking uv"

    if command_exists uv; then
        ok "$(get_version uv)"
        return 0
    fi

    # Need to install uv
    printf "${DIM}installing...${RESET} "

    if command_exists curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    elif command_exists wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    else
        fail "curl/wget not found"
    fi

    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command_exists uv; then
        ok "$(get_version uv)"
    else
        fail "install failed"
    fi
}

step_build_frontend() {
    step "Building UI"

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    WEB_DIR="$SCRIPT_DIR/src/frago/server/web"

    if ! command_exists pnpm; then
        fail "pnpm not found"
    fi

    if (cd "$WEB_DIR" && pnpm install --frozen-lockfile >/dev/null 2>&1 && pnpm build >/dev/null 2>&1); then
        ok "done"
    else
        fail "build failed"
    fi
}

step_build_package() {
    step "Packaging"

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

    if (cd "$SCRIPT_DIR" && uv build >/dev/null 2>&1); then
        ok "done"
    else
        fail "build failed"
    fi
}

step_install_frago() {
    step "Installing frago"

    export PATH="$HOME/.local/bin:$PATH"
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    WHEEL_FILE=$(find "$SCRIPT_DIR/dist" -name "frago_cli-*.whl" 2>/dev/null | head -n1)

    if [ -z "$WHEEL_FILE" ]; then
        fail "wheel not found"
    fi

    if command_exists frago; then
        uv tool install "$WHEEL_FILE" --force >/dev/null 2>&1
    else
        uv tool install "$WHEEL_FILE" >/dev/null 2>&1
    fi

    if command_exists frago; then
        ok "$(get_version frago)"
    else
        fail "install failed"
    fi
}

step_create_shortcut() {
    step "Creating shortcut"

    export PATH="$HOME/.local/bin:$PATH"
    FRAGO_BIN=$(command -v frago)
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    ICON_SRC="$SCRIPT_DIR/src/frago/server/assets/icons/logo.png"

    case "$PLATFORM" in
        Linux|WSL)
            # Install icons to hicolor theme (freedesktop.org standard)
            ICON_BASE="$HOME/.local/share/icons/hicolor"
            mkdir -p "$ICON_BASE/256x256/apps"
            mkdir -p "$ICON_BASE/128x128/apps"
            mkdir -p "$ICON_BASE/48x48/apps"

            # Create index.theme if missing (required for gtk-update-icon-cache)
            if [ ! -f "$ICON_BASE/index.theme" ]; then
                cat > "$ICON_BASE/index.theme" << 'INDEXEOF'
[Icon Theme]
Name=Hicolor
Comment=Fallback icon theme
Hidden=true
Directories=48x48/apps,128x128/apps,256x256/apps

[48x48/apps]
Size=48
Context=Applications
Type=Threshold

[128x128/apps]
Size=128
Context=Applications
Type=Threshold

[256x256/apps]
Size=256
Context=Applications
Type=Threshold
INDEXEOF
            fi

            # Create different sizes (ImageMagick if available, otherwise copy original)
            if command -v convert >/dev/null 2>&1; then
                convert "$ICON_SRC" -resize 256x256 "$ICON_BASE/256x256/apps/frago.png" 2>/dev/null
                convert "$ICON_SRC" -resize 128x128 "$ICON_BASE/128x128/apps/frago.png" 2>/dev/null
                convert "$ICON_SRC" -resize 48x48 "$ICON_BASE/48x48/apps/frago.png" 2>/dev/null
            else
                cp "$ICON_SRC" "$ICON_BASE/256x256/apps/frago.png" 2>/dev/null
                cp "$ICON_SRC" "$ICON_BASE/128x128/apps/frago.png" 2>/dev/null
                cp "$ICON_SRC" "$ICON_BASE/48x48/apps/frago.png" 2>/dev/null
            fi

            # Also install to pixmaps as fallback
            mkdir -p "$HOME/.local/share/pixmaps"
            cp "$ICON_SRC" "$HOME/.local/share/pixmaps/frago.png" 2>/dev/null || true

            # Create .desktop file (use icon name, not path - per freedesktop spec)
            DESKTOP_DIR="$HOME/.local/share/applications"
            mkdir -p "$DESKTOP_DIR"
            cat > "$DESKTOP_DIR/frago.desktop" << EOF
[Desktop Entry]
Name=frago
Comment=AI-powered automation framework
Exec=$FRAGO_BIN start
Icon=frago
Terminal=false
Type=Application
Categories=Development;Utility;
StartupWMClass=frago
EOF
            # Update desktop database if available
            command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" 2>/dev/null
            command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache "$ICON_BASE" 2>/dev/null || true
            ok "frago.desktop"
            ;;
        macOS)
            # Create .app bundle for macOS
            APP_DIR="$HOME/Applications/frago.app"
            mkdir -p "$APP_DIR/Contents/MacOS"
            mkdir -p "$APP_DIR/Contents/Resources"

            # Copy icon (.icns for macOS native support)
            ICNS_SRC="$SCRIPT_DIR/src/frago/server/assets/icons/frago.icns"
            if [ -f "$ICNS_SRC" ]; then
                cp "$ICNS_SRC" "$APP_DIR/Contents/Resources/frago.icns" 2>/dev/null || true
                ICON_FILE="frago.icns"
            else
                cp "$ICON_SRC" "$APP_DIR/Contents/Resources/frago.png" 2>/dev/null || true
                ICON_FILE="frago.png"
            fi

            cat > "$APP_DIR/Contents/MacOS/frago-launcher" << EOF
#!/bin/bash
export PATH="\$HOME/.local/bin:\$PATH"
exec frago start
EOF
            chmod +x "$APP_DIR/Contents/MacOS/frago-launcher"
            cat > "$APP_DIR/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>frago</string>
    <key>CFBundleExecutable</key>
    <string>frago-launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.frago.app</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>$ICON_FILE</string>
</dict>
</plist>
EOF
            ok "~/Applications/frago.app"
            ;;
        *)
            warn "skipped"
            ;;
    esac
}

step_launch() {
    step "Launching"

    export PATH="$HOME/.local/bin:$PATH"

    frago server stop >/dev/null 2>&1 || true
    sleep 1
    frago server start >/dev/null 2>&1 || true

    # Quick check if server started
    attempt=0
    while [ $attempt -lt 10 ]; do
        if curl -s --connect-timeout 1 "http://127.0.0.1:8093/" >/dev/null 2>&1; then
            ok "done"
            # Try to open browser in background
            (sleep 1 && frago start >/dev/null 2>&1) &
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done

    warn "manual start needed"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Completion Message
# ═══════════════════════════════════════════════════════════════════════════════

print_complete() {
    printf '\n'
    printf "${GREEN}✓${RESET} ${BOLD}Installation complete!${RESET}\n"
    printf '\n'

    # How to open
    printf "${DIM}  Open frago:${RESET}\n"
    case "$PLATFORM" in
        Linux)
            printf "    • Search ${CYAN}frago${RESET} in your app launcher\n"
            printf "    • Or run ${CYAN}frago start${RESET}\n"
            ;;
        macOS)
            printf "    • Open ${CYAN}frago${RESET} from ~/Applications\n"
            printf "    • Or run ${CYAN}frago start${RESET}\n"
            ;;
        *)
            printf "    • Run ${CYAN}frago start${RESET}\n"
            printf "    • Or open ${CYAN}http://127.0.0.1:8093${RESET}\n"
            ;;
    esac
    printf '\n'

    # Check if PATH needs updating
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *)
            printf "${DIM}  Add to shell profile:${RESET}\n"
            case "$SHELL" in
                */zsh)  printf "    ${CYAN}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc${RESET}\n" ;;
                */bash) printf "    ${CYAN}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc${RESET}\n" ;;
                *)      printf "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}\n" ;;
            esac
            printf '\n'
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    print_banner
    exit_virtualenv

    step_detect_platform
    step_check_uv
    step_build_frontend
    step_build_package
    step_install_frago
    step_create_shortcut
    step_launch

    print_complete
}

main "$@"
