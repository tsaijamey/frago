#!/bin/sh
# frago installation script for macOS, Linux, WSL, and Windows (Git Bash / MSYS2)
#
# Usage:
#   curl -fsSL https://frago.ai/install.sh | sh
#   wget -qO- https://frago.ai/install.sh | sh
#   sh install.sh [--cn|--official] [--no-start]
#
# Environment overrides:
#   FRAGO_INSTALL_SOURCE=auto|cn|official    Force installation source (default: auto)
#   FRAGO_NO_START=1                        Skip starting server & opening browser
#   UV_DEFAULT_INDEX                        Custom PyPI index URL
#   UV_PYTHON_INSTALL_MIRROR                Custom python-build-standalone mirror URL

set -e

# ═══════════════════════════════════════════════════════════════════════════════
# Constants & Mirror Definitions
# ═══════════════════════════════════════════════════════════════════════════════

TUNA_PYPI_BASE="https://pypi.tuna.tsinghua.edu.cn"
TUNA_SIMPLE_INDEX="${TUNA_PYPI_BASE}/simple"
NJU_PYTHON_MIRROR="https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone"
OFFICIAL_UV_INSTALL_SH="https://astral.sh/uv/install.sh"

INSTALL_SOURCE="${FRAGO_INSTALL_SOURCE:-auto}"
NO_START="${FRAGO_NO_START:-0}"

while [ $# -gt 0 ]; do
    case "$1" in
        --cn|--mirror)
            INSTALL_SOURCE="cn"
            ;;
        --official|--global)
            INSTALL_SOURCE="official"
            ;;
        --no-start|--skip-launch)
            NO_START="1"
            ;;
        -h|--help)
            echo "Usage: sh install.sh [--cn|--official] [--no-start]"
            echo ""
            echo "Options:"
            echo "  --cn, --mirror       Use China mainland mirrors (Tsinghua PyPI + NJU Python)"
            echo "  --official, --global Use official global sources (astral.sh + PyPI + GitHub)"
            echo "  --no-start           Install and verify only; do not launch server/browser"
            exit 0
            ;;
    esac
    shift
done

# ═══════════════════════════════════════════════════════════════════════════════
# Color and Style Definitions
# ═══════════════════════════════════════════════════════════════════════════════

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
# Utility & Platform Detection Functions
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

http_probe() {
    url="$1"
    timeout_sec="${2:-3}"
    if command_exists curl; then
        curl -fsSLI --connect-timeout "$timeout_sec" --max-time "$timeout_sec" "$url" >/dev/null 2>&1
        return $?
    elif command_exists wget; then
        wget -q --spider --timeout="$timeout_sec" --tries=1 "$url" >/dev/null 2>&1
        return $?
    fi
    return 1
}

http_download() {
    url="$1"
    dest="$2"
    label="${3:-}"
    if [ -n "$label" ]; then
        print_step "$label" >&2
    fi
    if command_exists curl; then
        curl -fL --progress-bar --connect-timeout 10 --retry 2 -o "$dest" "$url"
        return $?
    elif command_exists wget; then
        wget --show-progress -q --timeout=15 --tries=2 -O "$dest" "$url"
        return $?
    fi
    return 1
}

http_get_text() {
    url="$1"
    if command_exists curl; then
        curl -fsSL --compressed --connect-timeout 8 --max-time 20 "$url" 2>/dev/null
        return $?
    elif command_exists wget; then
        wget -qO- --timeout=15 --tries=2 "$url" 2>/dev/null
        return $?
    fi
    return 1
}

detect_libc() {
    if [ "$OS_FAMILY" != "linux" ]; then
        LIBC="native"
        return
    fi
    if ls /lib/ld-musl-*.so.1 >/dev/null 2>&1; then
        LIBC="musl"
    elif command_exists ldd && ldd --version 2>&1 | grep -qi musl; then
        LIBC="musl"
    else
        LIBC="glibc"
    fi
}

detect_platform() {
    OS="$(uname -s 2>/dev/null || echo Unknown)"
    ARCH="$(uname -m 2>/dev/null || echo unknown)"

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

    case "$ARCH" in
        x86_64|amd64|AMD64)
            NORM_ARCH="x86_64"
            ;;
        arm64|aarch64|ARM64)
            NORM_ARCH="aarch64"
            ;;
        armv7l|armv8l)
            NORM_ARCH="armv7l"
            ;;
        armv6l)
            NORM_ARCH="armv6l"
            ;;
        i386|i686|x86)
            NORM_ARCH="i686"
            ;;
        ppc64le)
            NORM_ARCH="ppc64le"
            ;;
        s390x)
            NORM_ARCH="s390x"
            ;;
        riscv64)
            NORM_ARCH="riscv64"
            ;;
        *)
            NORM_ARCH="$ARCH"
            ;;
    esac

    detect_libc
    resolve_uv_wheel_target
}

resolve_uv_wheel_target() {
    UV_WHEEL_TAG=""
    UV_WHEEL_PINNED_PATH=""

    case "${OS_FAMILY}:${NORM_ARCH}:${LIBC}" in
        macos:aarch64:*)
            UV_WHEEL_TAG="macosx_11_0_arm64.whl"
            UV_WHEEL_PINNED_PATH="packages/40/a5/8756c38ace102fa13fd4e653e8bc40e1f65924f1c0a0d23350339dac97e5/uv-0.13.7-py3-none-macosx_11_0_arm64.whl"
            ;;
        macos:x86_64:*)
            UV_WHEEL_TAG="macosx_10_12_x86_64.whl"
            UV_WHEEL_PINNED_PATH="packages/3d/5b/e0379e7b172659420b1ec99a8e8229830aa85ea59684847c80b1c959a056/uv-0.13.7-py3-none-macosx_10_12_x86_64.whl"
            ;;
        linux:x86_64:glibc)
            UV_WHEEL_TAG="manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
            UV_WHEEL_PINNED_PATH="packages/b9/93/0e053a2ca4523ee9825ccbedeb7121470d0a188933f11688b6d90d7f5c08/uv-0.13.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
            ;;
        linux:x86_64:musl)
            UV_WHEEL_TAG="musllinux_1_1_x86_64.whl"
            UV_WHEEL_PINNED_PATH="packages/2a/22/065e097ca6051ae7022d7c5c9d1591dcff97ed5609fb9eb450d8ee22fa17/uv-0.13.7-py3-none-musllinux_1_1_x86_64.whl"
            ;;
        linux:aarch64:*)
            UV_WHEEL_TAG="manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl"
            UV_WHEEL_PINNED_PATH="packages/96/72/da1119f94034d7173e6c8e2cd77a6299744458f0af3cb8e3a04d5cd419d1/uv-0.13.7-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl"
            ;;
        linux:armv7l:*)
            UV_WHEEL_TAG="manylinux_2_17_armv7l.manylinux2014_armv7l.musllinux_1_1_armv7l.whl"
            UV_WHEEL_PINNED_PATH="packages/f3/a8/d554d757e372d2dc8788e4c07601e440c09ce31535e3107180690233f4a2/uv-0.13.7-py3-none-manylinux_2_17_armv7l.manylinux2014_armv7l.musllinux_1_1_armv7l.whl"
            ;;
        linux:armv6l:*)
            UV_WHEEL_TAG="linux_armv6l.whl"
            UV_WHEEL_PINNED_PATH="packages/a6/e8/bda02e68c92b896e2c27581843c461e1007cb68c67c0b357d1e4849e6311/uv-0.13.7-py3-none-linux_armv6l.whl"
            ;;
        linux:i686:musl)
            UV_WHEEL_TAG="musllinux_1_1_i686.whl"
            UV_WHEEL_PINNED_PATH="packages/04/c3/0ca099ff442fb6a01a59b7582d8733f187183d491bc86e6f96c9203c3e1e/uv-0.13.7-py3-none-musllinux_1_1_i686.whl"
            ;;
        linux:i686:*)
            UV_WHEEL_TAG="manylinux_2_17_i686.manylinux2014_i686.whl"
            UV_WHEEL_PINNED_PATH="packages/78/55/fafeedc33a903456e7fd5fa442e7116331451c50e68e6fa985df47c06b3a/uv-0.13.7-py3-none-manylinux_2_17_i686.manylinux2014_i686.whl"
            ;;
        linux:ppc64le:*)
            UV_WHEEL_TAG="manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl"
            UV_WHEEL_PINNED_PATH="packages/d0/5e/50494a1cac0ff7030edc430c8ac86ee91ca43c54134d399b0f7a137930c7/uv-0.13.7-py3-none-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl"
            ;;
        linux:s390x:*)
            UV_WHEEL_TAG="manylinux_2_17_s390x.manylinux2014_s390x.whl"
            UV_WHEEL_PINNED_PATH="packages/28/b2/7fc68c91580168907f557c8824521973a3f63d1e3629ae3478aaeeebef7f/uv-0.13.7-py3-none-manylinux_2_17_s390x.manylinux2014_s390x.whl"
            ;;
        linux:riscv64:*)
            UV_WHEEL_TAG="manylinux_2_31_riscv64.musllinux_1_1_riscv64.whl"
            UV_WHEEL_PINNED_PATH="packages/28/3d/e7db43beff8b219ec392346f11b8aad325bc87bb282eea57e64cbe0aba56/uv-0.13.7-py3-none-manylinux_2_31_riscv64.musllinux_1_1_riscv64.whl"
            ;;
        windows:aarch64:*)
            UV_WHEEL_TAG="win_arm64.whl"
            UV_WHEEL_PINNED_PATH="packages/44/8d/1594dce4465d9699467a639b25aafd335ce1e5917f8bb60c9c0bed9e0859/uv-0.13.7-py3-none-win_arm64.whl"
            ;;
        windows:i686:*)
            UV_WHEEL_TAG="win32.whl"
            UV_WHEEL_PINNED_PATH="packages/c4/f2/3cfb8543acb8dc07b228d2517a0962b124ab97bd859690617d957248129c/uv-0.13.7-py3-none-win32.whl"
            ;;
        windows:x86_64:*)
            UV_WHEEL_TAG="win_amd64.whl"
            UV_WHEEL_PINNED_PATH="packages/8e/4f/041b59d2a38807a3e31ef41064cf3e45d2752fe0409d89040d52778049ae/uv-0.13.7-py3-none-win_amd64.whl"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# Network Detection & Mirror Configuration
# ═══════════════════════════════════════════════════════════════════════════════

ensure_http_client() {
    if command_exists curl || command_exists wget; then
        return 0
    fi
    print_step "Installing curl..."
    if command_exists apt-get; then
        (sudo apt-get update && sudo apt-get install -y curl ca-certificates) >/dev/null 2>&1 ||
            (apt-get update && apt-get install -y curl ca-certificates) >/dev/null 2>&1
    elif command_exists dnf; then
        sudo dnf install -y curl ca-certificates >/dev/null 2>&1 || dnf install -y curl ca-certificates >/dev/null 2>&1
    elif command_exists yum; then
        sudo yum install -y curl ca-certificates >/dev/null 2>&1 || yum install -y curl ca-certificates >/dev/null 2>&1
    elif command_exists pacman; then
        sudo pacman -Sy --noconfirm curl ca-certificates >/dev/null 2>&1 || pacman -Sy --noconfirm curl ca-certificates >/dev/null 2>&1
    elif command_exists apk; then
        sudo apk add --no-cache curl ca-certificates >/dev/null 2>&1 || apk add --no-cache curl ca-certificates >/dev/null 2>&1
    elif command_exists zypper; then
        sudo zypper install -y curl ca-certificates >/dev/null 2>&1 || zypper install -y curl ca-certificates >/dev/null 2>&1
    fi
    if command_exists curl || command_exists wget; then
        print_done "curl ready"
        return 0
    fi
    print_error "Neither curl nor wget found; please install curl first."
    exit 1
}

ensure_shell_path_persisted() {
    bin_dir="$HOME/.local/bin"

    # Run uv tool update-shell with ~/.local/bin stripped from PATH so uv does not
    # skip updating shell rc files just because this script exported PATH in-process.
    if [ -x "$bin_dir/uv" ]; then
        PATH="/usr/bin:/bin:/usr/sbin:/sbin" "$bin_dir/uv" tool update-shell >/dev/null 2>&1 || true
    else
        uv tool update-shell >/dev/null 2>&1 || true
    fi

    profile_target=""
    case "${SHELL:-}" in
        */zsh) profile_target="$HOME/.zshrc" ;;
        */bash)
            if [ -f "$HOME/.bashrc" ]; then
                profile_target="$HOME/.bashrc"
            else
                profile_target="$HOME/.bash_profile"
            fi
            ;;
        *) profile_target="$HOME/.profile" ;;
    esac

    if [ -n "$profile_target" ]; then
        touch "$profile_target" 2>/dev/null || true
        if ! grep -q '\.local/bin' "$profile_target" 2>/dev/null; then
            {
                echo ""
                echo '# frago & uv tool PATH'
                echo 'export PATH="$HOME/.local/bin:$PATH"'
            } >>"$profile_target" 2>/dev/null || true
        fi
    fi

    if [ "$OS_FAMILY" = "windows" ] && command_exists powershell.exe; then
        powershell.exe -NoProfile -Command '
            $bin = Join-Path $HOME ".local\bin"
            $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            $parts = ($userPath -split ";") | Where-Object { $_ }
            if ($bin -notin $parts) {
                $newPath = if ($userPath) { "$bin;$userPath" } else { $bin }
                [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
            }
        ' >/dev/null 2>&1 || true
    fi
}

persist_mirror_env() {
    idx_url="$1"
    py_mirror="$2"

    mkdir -p "$HOME/.local/bin"
    mirror_env_file="$HOME/.local/bin/env.frago-mirror"
    cat >"$mirror_env_file" <<EOF
#!/bin/sh
export UV_DEFAULT_INDEX="${idx_url}"
export UV_PYTHON_INSTALL_MIRROR="${py_mirror}"
EOF

    # Persist into user shell profile if not already present
    profile_target=""
    case "${SHELL:-}" in
        */zsh) profile_target="$HOME/.zshrc" ;;
        */bash)
            if [ -f "$HOME/.bashrc" ]; then
                profile_target="$HOME/.bashrc"
            else
                profile_target="$HOME/.bash_profile"
            fi
            ;;
        *) profile_target="$HOME/.profile" ;;
    esac

    if [ -n "$profile_target" ]; then
        touch "$profile_target" 2>/dev/null || true
        if ! grep -q "UV_DEFAULT_INDEX" "$profile_target" 2>/dev/null; then
            {
                echo ""
                echo "# frago uv domestic mirror configuration"
                echo "export UV_DEFAULT_INDEX=\"${idx_url}\""
                echo "export UV_PYTHON_INSTALL_MIRROR=\"${py_mirror}\""
            } >>"$profile_target" 2>/dev/null || true
        fi
    fi

    if [ "$OS_FAMILY" = "windows" ] && command_exists powershell.exe; then
        powershell.exe -NoProfile -Command "
            [System.Environment]::SetEnvironmentVariable('UV_DEFAULT_INDEX', '${idx_url}', 'User');
            [System.Environment]::SetEnvironmentVariable('UV_PYTHON_INSTALL_MIRROR', '${py_mirror}', 'User')
        " >/dev/null 2>&1 || true
    fi
}

enable_cn_mirror() {
    USE_CN_MIRROR=true
    export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-$TUNA_SIMPLE_INDEX}"
    export UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-$NJU_PYTHON_MIRROR}"
    persist_mirror_env "$UV_DEFAULT_INDEX" "$UV_PYTHON_INSTALL_MIRROR"
}

detect_network_profile() {
    ensure_http_client

    USE_CN_MIRROR=false

    case "$INSTALL_SOURCE" in
        cn|mirror|tuna)
            enable_cn_mirror
            print_success "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
            return 0
            ;;
        official|global)
            print_success "Network source: Official Global (astral.sh + PyPI + GitHub)"
            return 0
            ;;
    esac

    # If user already configured domestic mirror env vars, honor them
    case "${UV_DEFAULT_INDEX:-}${UV_PYTHON_INSTALL_MIRROR:-}" in
        *tuna.tsinghua.edu.cn*|*mirror.nju.edu.cn*|*aliyun.com*|*ustc.edu.cn*)
            enable_cn_mirror
            print_success "Network source: China Mainland Mirror (from existing env)"
            return 0
            ;;
    esac

    print_step "Probing network connectivity..."
    # Probe github.com (where uv & python-build-standalone binaries actually live) and pypi.org
    if http_probe "https://github.com/astral-sh/uv" 3 && http_probe "https://pypi.org/simple/" 3; then
        print_done "Network source: Official Global (GitHub + PyPI reachable)"
    else
        enable_cn_mirror
        print_done "Network source: China Mainland Mirror (Tsinghua PyPI + NJU Python)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Zero-Python uv Bootstrap (Official Script + PyPI Wheel Zip Extraction)
# ═══════════════════════════════════════════════════════════════════════════════

extract_zip_file() {
    zip_file="$1"
    dest_dir="$2"
    mkdir -p "$dest_dir"

    if command_exists unzip; then
        unzip -qo "$zip_file" -d "$dest_dir" >/dev/null 2>&1 && return 0
    fi
    if command_exists python3; then
        python3 -m zipfile -e "$zip_file" "$dest_dir" >/dev/null 2>&1 && return 0
    fi
    if command_exists python; then
        python -m zipfile -e "$zip_file" "$dest_dir" >/dev/null 2>&1 && return 0
    fi
    if command_exists bsdtar; then
        bsdtar -xf "$zip_file" -C "$dest_dir" >/dev/null 2>&1 && return 0
    fi
    if command_exists tar; then
        tar -xf "$zip_file" -C "$dest_dir" >/dev/null 2>&1 && return 0
    fi
    if command_exists busybox; then
        busybox unzip -qo "$zip_file" -d "$dest_dir" >/dev/null 2>&1 && return 0
    fi
    if [ "$OS_FAMILY" = "windows" ] && command_exists powershell.exe; then
        powershell.exe -NoProfile -Command "Expand-Archive -Path '$zip_file' -DestinationPath '$dest_dir' -Force" >/dev/null 2>&1 && return 0
    fi

    # Last resort on minimal Linux: install unzip via package manager
    if [ "$OS_FAMILY" = "linux" ]; then
        if command_exists apt-get; then
            (sudo apt-get update && sudo apt-get install -y unzip) >/dev/null 2>&1 ||
                (apt-get update && apt-get install -y unzip) >/dev/null 2>&1 || true
        elif command_exists dnf; then
            sudo dnf install -y unzip >/dev/null 2>&1 || dnf install -y unzip >/dev/null 2>&1 || true
        elif command_exists yum; then
            sudo yum install -y unzip >/dev/null 2>&1 || yum install -y unzip >/dev/null 2>&1 || true
        elif command_exists pacman; then
            sudo pacman -Sy --noconfirm unzip >/dev/null 2>&1 || pacman -Sy --noconfirm unzip >/dev/null 2>&1 || true
        elif command_exists apk; then
            sudo apk add --no-cache unzip >/dev/null 2>&1 || apk add --no-cache unzip >/dev/null 2>&1 || true
        elif command_exists zypper; then
            sudo zypper install -y unzip >/dev/null 2>&1 || zypper install -y unzip >/dev/null 2>&1 || true
        fi
        if command_exists unzip; then
            unzip -qo "$zip_file" -d "$dest_dir" >/dev/null 2>&1 && return 0
        fi
    fi

    return 1
}

resolve_latest_uv_wheel_from_tuna() {
    [ -z "$UV_WHEEL_TAG" ] && return 1
    index_html="$(http_get_text "${TUNA_SIMPLE_INDEX}/uv/")" || return 1
    [ -z "$index_html" ] && return 1

    # Extract relative hrefs matching uv-<ver>-py3-none-<UV_WHEEL_TAG>, sort by semantic version
    rel_path="$(printf '%s\n' "$index_html" |
        grep "py3-none-${UV_WHEEL_TAG}" |
        sed -n 's/.*href="\.\.\/\.\.\/\(packages\/[^"#]*\)".*/\1/p' |
        awk -F'/' '{
            fname = $NF
            ver = fname
            sub(/^uv-/, "", ver)
            sub(/-py3-none-.*$/, "", ver)
            split(ver, p, ".")
            printf "%05d.%05d.%05d %s\n", p[1], p[2], p[3], $0
        }' |
        sort |
        tail -n 1 |
        awk '{print $2}')"

    if [ -n "$rel_path" ]; then
        printf '%s/%s\n' "$TUNA_PYPI_BASE" "$rel_path"
        return 0
    fi
    return 1
}

install_uv_from_pypi_wheel() {
    [ -z "$UV_WHEEL_TAG" ] && return 1

    bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"

    tmp_base="${TMPDIR:-/tmp}"
    tmp_base="${tmp_base%/}"
    work_dir="$(mktemp -d "$tmp_base/frago-uv-XXXXXX" 2>/dev/null || echo "$tmp_base/frago-uv-$$")"
    mkdir -p "$work_dir"
    wheel_zip="$work_dir/uv.zip"
    extract_dir="$work_dir/uv-extracted"

    downloaded=false

    # 1. Try pinned verified 0.13.7 wheel URL first (single HTTP request, zero index overhead)
    if [ -n "$UV_WHEEL_PINNED_PATH" ]; then
        pinned_url="${TUNA_PYPI_BASE}/${UV_WHEEL_PINNED_PATH}"
        if http_download "$pinned_url" "$wheel_zip" "Downloading uv wheel from mirror ($pinned_url)..." && [ -s "$wheel_zip" ]; then
            downloaded=true
        fi
    fi

    # 2. Fallback: dynamically resolve latest wheel from Tsinghua Simple Index
    if [ "$downloaded" = false ]; then
        latest_url="$(resolve_latest_uv_wheel_from_tuna || true)"
        if [ -n "$latest_url" ] && http_download "$latest_url" "$wheel_zip" "Downloading latest uv wheel ($latest_url)..." && [ -s "$wheel_zip" ]; then
            downloaded=true
        fi
    fi

    if [ "$downloaded" = false ]; then
        rm -rf "$work_dir" >/dev/null 2>&1 || true
        return 1
    fi

    print_step "Extracting uv binaries from wheel..."
    if ! extract_zip_file "$wheel_zip" "$extract_dir"; then
        rm -rf "$work_dir" >/dev/null 2>&1 || true
        return 1
    fi

    moved=false
    for script_bin in "$extract_dir"/uv-*.data/scripts/*; do
        if [ -f "$script_bin" ]; then
            base_name="$(basename "$script_bin")"
            cp -f "$script_bin" "$bin_dir/$base_name"
            chmod +x "$bin_dir/$base_name" 2>/dev/null || true
            moved=true
        fi
    done

    rm -rf "$work_dir" >/dev/null 2>&1 || true

    export PATH="$bin_dir:$PATH"
    if [ "$moved" = true ] && command_exists uv; then
        return 0
    fi
    return 1
}

install_uv_from_official() {
    print_step "Downloading uv official installer ($OFFICIAL_UV_INSTALL_SH)..."
    tmp_sh="$(mktemp "${TMPDIR:-/tmp}/uv-install-XXXXXX.sh" 2>/dev/null || echo "${TMPDIR:-/tmp}/uv-install-$$.sh")"
    if ! http_download "$OFFICIAL_UV_INSTALL_SH" "$tmp_sh"; then
        rm -f "$tmp_sh"
        return 1
    fi
    print_step "Running official uv installer script..."
    if ! sh "$tmp_sh"; then
        rm -f "$tmp_sh"
        return 1
    fi
    rm -f "$tmp_sh"

    [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    command_exists uv
}

# ═══════════════════════════════════════════════════════════════════════════════
# System Dependencies Installation (git, tmux / arndawg.tmux-windows, ffmpeg)
# ═══════════════════════════════════════════════════════════════════════════════

APT_UPDATED=false
WINDOWS_TMUX_RELEASE_URL="https://github.com/arndawg/tmux-windows/releases/download/v3.6a-win32.7/tmux-windows-v3.6a-win32.7.zip"

run_linux_pkg_install() {
    pkg="$1"
    print_step "Installing $pkg via Linux package manager..."
    if command_exists apt-get; then
        if [ "$APT_UPDATED" = false ]; then
            print_step "Updating package lists (apt-get update)..."
            if [ "$(id -u)" = "0" ]; then
                apt-get update || true
            elif command_exists sudo; then
                sudo apt-get update || true
            fi
            APT_UPDATED=true
        fi
        if [ "$(id -u)" = "0" ]; then
            DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
        elif command_exists sudo; then
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
        else
            return 1
        fi
    elif command_exists dnf; then
        if [ "$(id -u)" = "0" ]; then
            dnf install -y "$pkg" ||
                ([ "$pkg" = "ffmpeg" ] && (dnf install -y --allowerasing ffmpeg || dnf install -y ffmpeg-free))
        elif command_exists sudo; then
            sudo dnf install -y "$pkg" ||
                ([ "$pkg" = "ffmpeg" ] && (sudo dnf install -y --allowerasing ffmpeg || sudo dnf install -y ffmpeg-free))
        else
            return 1
        fi
    elif command_exists yum; then
        if [ "$(id -u)" = "0" ]; then
            yum install -y "$pkg"
        elif command_exists sudo; then
            sudo yum install -y "$pkg"
        else
            return 1
        fi
    elif command_exists pacman; then
        if [ "$(id -u)" = "0" ]; then
            pacman -Sy --noconfirm --needed "$pkg"
        elif command_exists sudo; then
            sudo pacman -Sy --noconfirm --needed "$pkg"
        else
            return 1
        fi
    elif command_exists apk; then
        if [ "$(id -u)" = "0" ]; then
            apk add --no-cache "$pkg"
        elif command_exists sudo; then
            sudo apk add --no-cache "$pkg"
        else
            return 1
        fi
    elif command_exists zypper; then
        if [ "$(id -u)" = "0" ]; then
            zypper --non-interactive install -y "$pkg"
        elif command_exists sudo; then
            sudo zypper --non-interactive install -y "$pkg"
        else
            return 1
        fi
    else
        return 1
    fi
}

ensure_homebrew() {
    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    if [ "$USE_CN_MIRROR" = true ]; then
        export HOMEBREW_BREW_GIT_REMOTE="${HOMEBREW_BREW_GIT_REMOTE:-https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/brew.git}"
        export HOMEBREW_CORE_GIT_REMOTE="${HOMEBREW_CORE_GIT_REMOTE:-https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/homebrew-core.git}"
        export HOMEBREW_API_DOMAIN="${HOMEBREW_API_DOMAIN:-https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api}"
        export HOMEBREW_BOTTLE_DOMAIN="${HOMEBREW_BOTTLE_DOMAIN:-https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles}"
    fi
    if command_exists brew; then
        return 0
    fi

    print_step "Installing Homebrew (macOS package manager)..."
    if [ "$USE_CN_MIRROR" = true ]; then
        tmp_brew_dir="$(mktemp -d "${TMPDIR:-/tmp}/frago-brew-XXXXXX" 2>/dev/null || echo "/tmp/frago-brew-$$")"
        if command_exists git && git clone --depth=1 https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/install.git "$tmp_brew_dir/brew-install"; then
            NONINTERACTIVE=1 /bin/bash "$tmp_brew_dir/brew-install/install.sh" || true
        fi
        rm -rf "$tmp_brew_dir" >/dev/null 2>&1 || true
    fi

    if ! command_exists brew; then
        brew_installer="$(mktemp "${TMPDIR:-/tmp}/brew-install-XXXXXX.sh" 2>/dev/null || echo "/tmp/brew-install-$$.sh")"
        if http_download "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" "$brew_installer" "Downloading official Homebrew installer..."; then
            NONINTERACTIVE=1 /bin/bash "$brew_installer" || true
            rm -f "$brew_installer"
        fi
    fi

    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    command_exists brew
}

refresh_windows_posix_path() {
    export PATH="$HOME/.local/bin:/c/Program Files/Git/cmd:/c/Program Files/Git/bin:$PATH"
    if [ -n "${LOCALAPPDATA:-}" ] && command_exists cygpath; then
        winget_links="$(cygpath -u "$LOCALAPPDATA/Microsoft/WinGet/Links" 2>/dev/null || true)"
        [ -n "$winget_links" ] && [ -d "$winget_links" ] && export PATH="$winget_links:$PATH"
    fi
}

install_windows_tmux_zip_fallback() {
    bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
    tmp_base="${TMPDIR:-/tmp}"
    tmp_base="${tmp_base%/}"
    work_dir="$(mktemp -d "$tmp_base/frago-tmux-win-XXXXXX" 2>/dev/null || echo "$tmp_base/frago-tmux-win-$$")"
    mkdir -p "$work_dir"
    zip_path="$work_dir/tmux-windows.zip"
    extract_dir="$work_dir/extracted"

    downloaded=false
    if [ "$USE_CN_MIRROR" = true ]; then
        for proxy_prefix in "https://ghfast.top/" "https://mirror.ghproxy.com/" ""; do
            download_url="${proxy_prefix}${WINDOWS_TMUX_RELEASE_URL}"
            if http_download "$download_url" "$zip_path" "Downloading tmux zip ($download_url)..." && [ -s "$zip_path" ]; then
                downloaded=true
                break
            fi
        done
    else
        for proxy_prefix in "" "https://ghfast.top/" "https://mirror.ghproxy.com/"; do
            download_url="${proxy_prefix}${WINDOWS_TMUX_RELEASE_URL}"
            if http_download "$download_url" "$zip_path" "Downloading tmux zip ($download_url)..." && [ -s "$zip_path" ]; then
                downloaded=true
                break
            fi
        done
    fi

    if [ "$downloaded" = true ]; then
        print_step "Extracting tmux binary..."
        if extract_zip_file "$zip_path" "$extract_dir"; then
            if [ -f "$extract_dir/tmux.exe" ]; then
                cp -f "$extract_dir/tmux.exe" "$bin_dir/tmux.exe"
                chmod +x "$bin_dir/tmux.exe" 2>/dev/null || true
                rm -rf "$work_dir" >/dev/null 2>&1 || true
                export PATH="$bin_dir:$PATH"
                return 0
            fi
        fi
    fi

    rm -rf "$work_dir" >/dev/null 2>&1 || true
    return 1
}

install_git() {
    [ "$OS_FAMILY" = "macos" ] && export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    [ "$OS_FAMILY" = "windows" ] && refresh_windows_posix_path

    if command_exists git && git --version >/dev/null 2>&1; then
        version=$(get_version git)
        print_success "git ($version)"
        return 0
    fi

    print_step "Installing git..."
    case "$OS_FAMILY" in
        macos)
            if ensure_homebrew; then
                brew install git || true
            else
                xcode-select --install || true
            fi
            ;;
        linux)
            run_linux_pkg_install git || true
            ;;
        windows)
            if command_exists winget.exe; then
                winget.exe install --id Git.Git --exact --accept-package-agreements --accept-source-agreements --disable-interactivity || true
                refresh_windows_posix_path
            elif command_exists pacman; then
                pacman -Sy --noconfirm --needed git || true
            fi
            ;;
    esac

    if command_exists git && git --version >/dev/null 2>&1; then
        version=$(get_version git)
        print_done "git ($version)"
        return 0
    fi

    print_error "git installation failed"
    exit 1
}

install_tmux() {
    [ "$OS_FAMILY" = "macos" ] && export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    [ "$OS_FAMILY" = "windows" ] && refresh_windows_posix_path

    if command_exists tmux; then
        version=$(get_version tmux)
        print_success "tmux ($version)"
        return 0
    fi

    case "$OS_FAMILY" in
        macos)
            print_step "Installing tmux..."
            if ensure_homebrew; then
                brew install tmux || true
            fi
            ;;
        linux)
            print_step "Installing tmux..."
            run_linux_pkg_install tmux || true
            ;;
        windows)
            print_step "Installing tmux (Windows port: arndawg.tmux-windows)..."
            if command_exists winget.exe; then
                winget.exe install --id arndawg.tmux-windows --exact --accept-package-agreements --accept-source-agreements --disable-interactivity || true
                refresh_windows_posix_path
            fi
            if ! command_exists tmux; then
                install_windows_tmux_zip_fallback || true
            fi
            ;;
    esac

    if command_exists tmux; then
        version=$(get_version tmux)
        print_done "tmux ($version)"
        return 0
    fi

    print_error "tmux installation failed"
    exit 1
}

install_ffmpeg() {
    [ "$OS_FAMILY" = "macos" ] && export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    [ "$OS_FAMILY" = "windows" ] && refresh_windows_posix_path

    if command_exists ffmpeg; then
        version=$(get_version ffmpeg)
        print_success "ffmpeg ($version)"
        return 0
    fi

    print_step "Installing ffmpeg..."
    case "$OS_FAMILY" in
        macos)
            if ensure_homebrew; then
                brew install ffmpeg || true
            fi
            ;;
        linux)
            run_linux_pkg_install ffmpeg || true
            ;;
        windows)
            if command_exists winget.exe; then
                winget.exe install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements --disable-interactivity ||
                    winget.exe install --id Gyan.FFmpeg.Essentials --exact --accept-package-agreements --accept-source-agreements --disable-interactivity || true
                refresh_windows_posix_path
            elif command_exists pacman; then
                pacman -Sy --noconfirm --needed ffmpeg || true
            fi
            ;;
    esac

    if command_exists ffmpeg; then
        version=$(get_version ffmpeg)
        print_done "ffmpeg ($version)"
        return 0
    fi

    print_error "ffmpeg installation failed"
    exit 1
}

install_uv() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command_exists uv; then
        version=$(get_version uv)
        print_success "uv ($version)"
        return 0
    fi

    if [ "$USE_CN_MIRROR" = true ]; then
        print_step "Installing uv (via Tsinghua PyPI precompiled wheel)..."
        if install_uv_from_pypi_wheel; then
            version=$(get_version uv)
            print_done "uv ($version, via Tsinghua mirror)"
            return 0
        fi
        print_step "Mirror wheel install failed, trying official installer..."
        if install_uv_from_official; then
            version=$(get_version uv)
            print_done "uv ($version)"
            return 0
        fi
    else
        print_step "Installing uv..."
        if install_uv_from_official; then
            version=$(get_version uv)
            print_done "uv ($version)"
            return 0
        fi
        print_step "Official uv installer unreachable, switching to Tsinghua PyPI wheel..."
        enable_cn_mirror
        if install_uv_from_pypi_wheel; then
            version=$(get_version uv)
            print_done "uv ($version, via Tsinghua mirror)"
            return 0
        fi
    fi

    print_error "uv installation failed"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# frago-cli & Default CoreAgent Runtime Installation
# ═══════════════════════════════════════════════════════════════════════════════

run_uv_tool_install() {
    action="$1"
    if [ "$action" = "upgrade" ]; then
        uv tool upgrade --python 3.13 --refresh-package frago-cli frago-cli || uv tool install --python 3.13 --refresh-package frago-cli frago-cli --force
    else
        uv tool install --python 3.13 --refresh-package frago-cli frago-cli
    fi
}

install_frago() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    action="install"
    if command_exists frago; then
        action="upgrade"
        print_step "Upgrading frago-cli (Python 3.13 + built-in CoreAgent)..."
    else
        print_step "Installing frago-cli (Python 3.13 + built-in CoreAgent)..."
    fi

    if ! run_uv_tool_install "$action"; then
        if [ "$USE_CN_MIRROR" = false ] && [ "$INSTALL_SOURCE" != "official" ]; then
            print_step "Retrying with China Mainland Mirror (Tsinghua PyPI + NJU Python)..."
            enable_cn_mirror
            run_uv_tool_install "$action" || {
                print_error "frago-cli installation failed"
                exit 1
            }
        else
            print_error "frago-cli installation failed"
            exit 1
        fi
    fi

    # Persist ~/.local/bin into user's shell PATH
    ensure_shell_path_persisted

    if command_exists frago; then
        version_output="$(frago --version 2>&1 || true)"
        version="$(printf '%s' "$version_output" | head -n1 | tr -d '\r\n')"
        if [ -z "$version" ] || printf '%s' "$version_output" | grep -qi "error\|traceback"; then
            print_error "frago verification failed: ${version_output}"
            exit 1
        fi
        print_done "frago ($version)"
    else
        print_error "frago installation failed (binary not found in ~/.local/bin)"
        exit 1
    fi
}

print_next_steps() {
    print_section "Getting Started"

    printf "  ${DIM}Commands:${RESET}\n"
    printf "    ${BOLD}frago start${RESET}         Start frago server and open Web UI\n"
    printf "    ${BOLD}frago --version${RESET}     Verify installed frago version\n"
    printf "    ${BOLD}frago --help${RESET}        Show all available commands\n"
    echo ""
    printf "  ${DIM}Note: Open a new terminal or run 'export PATH=\"\$HOME/.local/bin:\$PATH\"' if 'frago' is not yet in your current shell PATH.${RESET}\n"
    echo ""
}

wait_for_server() {
    max_attempts=30
    attempt=1

    while [ $attempt -le $max_attempts ]; do
        connected=false
        if (echo >/dev/tcp/127.0.0.1/8093) 2>/dev/null; then
            connected=true
        elif command_exists nc && nc -z -w 1 127.0.0.1 8093 2>/dev/null; then
            connected=true
        elif command_exists curl && curl -s --connect-timeout 1 "http://127.0.0.1:8093/api/status" >/dev/null 2>&1; then
            connected=true
        fi

        if [ "$connected" = true ]; then
            printf "\n  ${GREEN}+ frago server is ready at http://127.0.0.1:8093${RESET}\n"
            return 0
        fi

        printf "\r  ${DIM}Waiting for frago server on http://127.0.0.1:8093 (%ds/%ds)...${RESET}" "$attempt" "$max_attempts"
        sleep 1
        attempt=$((attempt + 1))
    done

    printf "\n"
    log_file="$HOME/.frago/server.log"
    if [ -f "$log_file" ]; then
        printf "  ${DIM}Last 10 lines of %s:${RESET}\n" "$log_file"
        tail -n 10 "$log_file" | sed 's/^/    /' 2>/dev/null || true
    fi
    return 1
}

launch_frago() {
    if [ "$NO_START" = "1" ]; then
        return 0
    fi

    print_section "Launching"

    export PATH="$HOME/.local/bin:$PATH"
    printf "  ${DIM}Starting frago server...${RESET}\n"

    frago server stop >/dev/null 2>&1 || true
    sleep 0.5

    if ! frago server start; then
        print_warning "frago server start failed. Run 'frago server --debug' to inspect error."
        return 0
    fi

    if wait_for_server; then
        printf "  ${DIM}Opening browser...${RESET}\n"
        echo ""
        frago start --no-browser >/dev/null 2>&1 || true
        if command_exists xdg-open; then
            xdg-open "http://127.0.0.1:8093" >/dev/null 2>&1 &
        elif command_exists open; then
            open "http://127.0.0.1:8093" >/dev/null 2>&1 || true
        elif [ "$OS_FAMILY" = "windows" ] && command_exists cmd.exe; then
            cmd.exe /c start "" "http://127.0.0.1:8093" >/dev/null 2>&1 || true
        else
            printf "  ${CYAN}Open in browser: http://127.0.0.1:8093${RESET}\n"
        fi
    else
        print_warning "Server did not respond in time. Run 'frago start' manually."
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    print_banner

    print_section "Environment"
    detect_platform
    print_success "$PLATFORM ($NORM_ARCH)"
    detect_network_profile

    print_section "Dependencies"
    install_git
    install_tmux
    install_ffmpeg
    install_uv
    install_frago

    print_next_steps
    launch_frago
}

main "$@"
