# Installation Guide

[简体中文](installation.zh-CN.md)

> [!IMPORTANT]
> ## ⚠️ Before You Install
>
> **frago needs Python + Node.js + Chrome.** Each OS has different setup:
>
> - **Linux**: May not have Python pre-installed
> - **macOS**: Some dependencies need Xcode Command Line Tools
> - **Windows**: Nothing is pre-installed — Python, Node.js, Chrome all manual
>
> **2 minutes of prep now saves 20 minutes of debugging.**
>
> | Your OS | Go here first |
> |---------|---------------|
> | **Linux** | → [Linux Prerequisites](#linux-prerequisites) |
> | **macOS** | → [macOS Prerequisites](#macos-prerequisites) |
> | **Windows** | → [Windows Prerequisites](#windows-prerequisites) |

> [!WARNING]
> **Windows Users — This Will Break If You Skip It**
>
> On macOS/Linux, `frago init` can auto-install Node.js for you. **On Windows, it can't.**
>
> If you run `frago init` without Node.js installed, you'll get:
> ```
> Error: Windows 不支持自动安装 Node.js
> ```
>
> → [Install Node.js first](#install-nodejs-required-before-frago-init) (takes 2 minutes)

---

## Step 1: Install uv (Package Manager)

**Why uv?** It's faster, cleaner, and handles environments properly. Don't use pip directly.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installation, **restart your terminal** to make `uv` available.

Verify:
```bash
uv --version
```

---

## Step 2: Install frago

```bash
uv tool install frago-cli
```

That's it. One command.

> **Windows Users**: If you have Python 3.14+ installed, you must specify Python 3.13:
> ```powershell
> uv tool install frago-cli --python 3.13
> ```
> This is because the GUI backend (pywebview) uses pythonnet which doesn't support Python 3.14 yet.

<details>
<summary>Still want to use pip? (Not recommended)</summary>

```bash
# macOS
pip3 install frago-cli

# Linux / Windows
pip install frago-cli
```

You're on your own for virtual environment management.
</details>

---

## Step 3: Initialize Environment

After installing the package, run the init command to set up your environment:

```bash
frago init
```

### What `frago init` Does

The init command performs the following steps:

1. **Dependency Check**
   - Detects Node.js (required version ≥20.0.0) and its path
   - Detects Claude Code CLI and its version
   - Displays status with ✅/❌ indicators

2. **Automatic Installation** (if dependencies are missing)
   - Node.js: Installs via nvm (Node Version Manager)
   - Claude Code: Installs via `npm install -g @anthropic-ai/claude-code`

3. **Authentication Configuration**
   - **Default**: Uses Claude Code's built-in authentication (Anthropic account or existing settings)
   - **Custom Endpoint**: Configures third-party API providers that support Anthropic API compatibility:
     - DeepSeek (deepseek-chat)
     - Aliyun Bailian (qwen3-coder-plus)
     - Kimi K2 (kimi-k2-turbo-preview)
     - MiniMax M2
     - Custom URL/Key/Model

4. **Resource Installation**
   - Installs Claude Code slash commands to `~/.claude/commands/`
   - Installs example recipes to `~/.frago/recipes/`

### Init Command Options

```bash
# Show current configuration and installed resources
frago init --show-config

# Skip dependency checks (only update config)
frago init --skip-deps

# Reset configuration and re-initialize
frago init --reset

# Non-interactive mode (uses defaults, for CI/CD)
frago init --non-interactive

# Skip resource installation
frago init --skip-resources

# Force update all resources (overwrite existing recipes)
frago init --update-resources
```

### Configuration Files

| File | Purpose |
|------|---------|
| `~/.frago/config.json` | frago configuration (auth method, resource status) |
| `~/.claude/settings.json` | Claude Code settings (custom API endpoint config) |
| `~/.claude/commands/frago.*.md` | Installed slash commands |
| `~/.frago/recipes/` | User-level recipes |

### Multi-Device Resource Sync

**Why a private repository?** Your skills and recipes are personal assets—workflow patterns you've discovered, automation scripts you've built. They shouldn't be tied to a single machine or lost when you reinstall.

After initial setup, sync your resources across devices:

```bash
# First time: configure your private repository
frago sync --set-repo git@github.com:you/my-frago-resources.git

# Daily use: sync changes
frago sync              # Push local changes and pull remote updates
frago sync --dry-run    # Preview what will be synced
frago sync --no-push    # Only pull, don't push
```

---

## Web Service Mode

frago provides a browser-based GUI through a local web service. No extra installation needed—just Chrome browser.

**Launch Web Service**:
```bash
# Start background server (recommended)
frago server start      # Starts on port 8093

# Or start in foreground (for debugging)
frago server --debug    # Runs until Ctrl+C with logs
```

**Server Commands**:
```bash
frago server start      # Start background server
frago server stop       # Stop background server
frago server status     # Check if server is running
```

**Access the GUI**:
- Open `http://127.0.0.1:8093` in your browser after starting the server

**Platform Notes**:
- Works on any platform with Chrome/Edge/Firefox
- No platform-specific dependencies required
- Server runs on port 8093 by default

---

## Development Environment

For contributors:

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```

**Dev dependencies**: pytest, pytest-cov, ruff, mypy, black

---

## System Requirements

- **Python**: 3.9 - 3.13
- **Operating System**: macOS, Linux, Windows
- **Chrome Browser**: For CDP browser automation

---

## Linux Prerequisites

Before installing frago on Linux, ensure your system meets the following requirements.

### What You Need to Prepare

| Dependency | Purpose | Required |
|------------|---------|----------|
| **Python 3.9+** | frago runtime | Yes |
| **Node.js 20+** | Claude Code dependency | Yes (for Claude Code integration) |
| **Chrome Browser** | CDP browser automation | Yes (for CDP features) |
| **curl or wget** | Download installation scripts (nvm) | Yes (for auto-install) |
| **git** | Clone repositories | For development |

### What frago Does NOT Do For You

1. **Install system packages** - frago cannot run `sudo apt/dnf/pacman` commands
2. **Configure network proxy** - You need to set up proxy for npm/pip if needed
3. **Handle permission issues** - npm global directory permissions need manual setup
4. **Choose distro-specific commands** - You need to select commands for your distribution

### System Dependencies by Distribution

#### Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv curl git
```

#### Fedora/RHEL

```bash
sudo dnf install -y python3 python3-pip curl git
```

#### Arch Linux

```bash
sudo pacman -S python python-pip curl git
```

#### openSUSE

```bash
sudo zypper install -y python3 python3-pip curl git
```

### Chrome Browser Installation

Chrome is required for CDP (Chrome DevTools Protocol) features.

#### Ubuntu/Debian (64-bit)

```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt -f install  # Fix dependencies if needed
```

#### Fedora/RHEL

```bash
sudo dnf install https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
```

#### Arch Linux

```bash
# Using yay (AUR helper)
yay -S google-chrome

# Or using paru
paru -S google-chrome
```

### Pre-Installation Checklist

Before installing frago, verify:

```bash
# Python 3.9+ installed
python3 --version

# Chrome installed (for CDP features)
google-chrome --version

# Node.js 20+ installed (for Claude Code integration)
node --version
```

---

## macOS Prerequisites

Before installing frago on macOS, ensure your system meets the following requirements.

### System Requirements

- **macOS**: 10.15 (Catalina) or later
- **Architecture**: Apple Silicon (M1/M2/M3) and Intel both fully supported

### Install Xcode Command Line Tools

Required for compiling some Python packages:

```bash
xcode-select --install
```

### Install uv

```bash
# Option 1: Official installer
curl -LsSf https://astral.sh/uv/install.sh | sh

# Option 2: Homebrew
brew install uv
```

Then install frago as described in [Step 2](#step-2-install-frago).

### Chrome Browser

Chrome is typically pre-installed or available from [google.com/chrome](https://www.google.com/chrome/). Verify installation:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
```

### Pre-Installation Checklist

Before installing frago, verify:

```bash
# Python 3.9+ installed (macOS 12+ includes Python 3)
python3 --version

# Xcode Command Line Tools installed
xcode-select -p

# Chrome installed (for CDP features)
ls /Applications/Google\ Chrome.app

# Node.js 20+ installed (for Claude Code integration)
node --version
```

---

## Windows Prerequisites

Before installing frago on Windows, ensure your system meets the following requirements.

> **Important**: Unlike macOS/Linux, Windows does NOT support automatic Node.js installation via nvm. You must install Node.js manually before running `frago init`.

### System Requirements

- **Windows**: 10 (1809+) or Windows 11
- **Architecture**: x64 and ARM64 supported

### Install Python

Windows does not include Python by default:

```powershell
# Option 1: Microsoft Store (easiest)
# Search "Python 3.13" in Microsoft Store and install

# Option 2: winget (recommended)
winget install Python.Python.3.13

# Option 3: Official installer
# Download from https://www.python.org/downloads/
# IMPORTANT: Check "Add Python to PATH" during installation!
```

> **Important**: Use Python 3.9 - 3.13. Python 3.14+ is NOT supported on Windows due to pywebview/pythonnet compatibility issues.

### Install Node.js (Required Before frago init)

```powershell
# Using winget (recommended)
winget install OpenJS.NodeJS.LTS

# Or download from https://nodejs.org/
# Choose LTS version (20.x)
```

### Install Chrome Browser

```powershell
# Using winget
winget install Google.Chrome

# Or download from https://www.google.com/chrome/
```

### Install uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then install frago as described in [Step 2](#step-2-install-frago).

### GUI Support (WebView2)

For GUI features, WebView2 Runtime is required:

```powershell
# Windows 11 usually has it pre-installed
# For Windows 10, install manually:
winget install Microsoft.EdgeWebView2Runtime
```

> **Python Version Requirement**: GUI mode requires Python 3.13 or earlier. If using Python 3.14+, install with:
> ```powershell
> uv tool install frago-cli --python 3.13
> ```

### Pre-Installation Checklist

Before installing frago, verify in PowerShell:

```powershell
# Python 3.9+ installed
python --version

# Node.js 20+ installed (REQUIRED before frago init)
node --version

# Chrome installed (for CDP features)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --version
```

---

## Verify Installation

Verify after installation:

```bash
# Check version
frago --version

# List available Recipes
frago recipe list

# View help
frago --help
```

---

## Upgrade

```bash
uv tool upgrade frago-cli
```

---

## Uninstall

```bash
uv tool uninstall frago-cli
```
