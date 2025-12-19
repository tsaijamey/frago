# Installation Guide

[简体中文](installation.zh-CN.md)

> [!IMPORTANT]
> ## ⚠️ Read This First — Don't Skip!
>
> **Installation will FAIL if you skip the prerequisites for your OS.**
>
> | Your OS | What to do FIRST | Time |
> |---------|------------------|------|
> | **Linux** | → [Linux Prerequisites](#linux-prerequisites) | 2 min |
> | **macOS** | → [macOS Prerequisites](#macos-prerequisites) | 2 min |
> | **Windows** | → [Windows Prerequisites](#windows-prerequisites) | 5 min |

> [!WARNING]
> **Windows Users: You MUST install Node.js manually!**
>
> Unlike macOS/Linux, Windows cannot auto-install Node.js. If you skip this step, `frago init` will fail.
>
> → [Install Node.js NOW](#install-nodejs-required-before-frago-init)

---

## Basic Installation

Install core features (CDP operations + Recipe system core):

```bash
# Using pip
pip install frago-cli

# Using uv (recommended)
uv tool install frago-cli
```

**Core features include**:
- ✅ Chrome DevTools Protocol (CDP) operations
- ✅ Recipe system (list, execute, metadata management)
- ✅ Output to stdout and file
- ✅ Python/Shell Recipe execution
- ✅ Workflow orchestration

---

## Environment Initialization

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
| `~/.frago/config.json` | Frago configuration (auth method, resource status) |
| `~/.claude/settings.json` | Claude Code settings (custom API endpoint config) |
| `~/.claude/commands/frago.*.md` | Installed slash commands |
| `~/.frago/recipes/` | User-level recipes |

### Multi-Device Resource Sync

After initial setup, you can sync your personalized resources (skills, recipes, commands) across devices using your own Git repository:

```bash
# Configure your private repository (first time only)
frago sync --set-repo git@github.com:you/my-frago-resources.git

# Deploy resources from your repository
frago deploy

# After making changes, sync back to repository
frago publish && frago sync
```

See [User Guide - Resource Management](user-guide.md#resource-management) for detailed workflows.

---

## Optional Features

### GUI Support

If you want to use the desktop GUI interface:

```bash
# Using pip
pip install frago-cli[gui]

# Using uv
uv tool install "frago-cli[gui]"
```

**Platform-specific requirements**:

| Platform | Backend | System Dependencies |
|----------|---------|---------------------|
| **Linux** | WebKit2GTK | `sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1` |
| **macOS** | WKWebView | None (built-in) |
| **Windows** | WebView2 | Edge WebView2 Runtime (recommended) |

**Linux Installation Example (Ubuntu/Debian)**:
```bash
# Install system dependencies first
sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1

# Then install frago with GUI support
pip install frago-cli[gui]

# Or one-liner with PyGObject compilation support
sudo apt install -y libcairo2-dev libgirepository1.0-dev gir1.2-webkit2-4.1
pip install frago-cli[gui] PyGObject
```

**Launch GUI**:
```bash
frago gui
frago gui --debug  # With developer tools
```

---

### Clipboard Support

If you need to output Recipe results to clipboard:

```bash
# Using pip
pip install frago-cli[clipboard]

# Using uv
uv tool install "frago-cli[clipboard]"
```

**Additional features provided**:
- ✅ `--output-clipboard` option
- ✅ `clipboard_read` Recipe (system clipboard read)

---

### Full Installation (All Optional Features)

Install all features:

```bash
# Using pip
pip install frago-cli[all]

# Using uv
uv tool install "frago-cli[all]"
```

---

## Development Environment Installation

If you want to contribute to development or run tests:

```bash
# Clone repository
git clone https://github.com/frago/frago.git
cd frago

# Install development dependencies using uv (recommended)
uv sync --all-extras --dev

# Or using pip
pip install -e ".[dev,all]"
```

**Development dependencies include**:
- pytest (test framework)
- pytest-cov (coverage)
- ruff (code linting)
- mypy (type checking)
- black (code formatting)

---

## Dependency Details

### Required Dependencies (installed for all users)

```toml
dependencies = [
    "websocket-client>=1.9.0",  # CDP WebSocket connection
    "click>=8.1.0",             # CLI framework
    "pydantic>=2.0.0",          # Data validation
    "python-dotenv>=1.0.0",     # Environment variables
    "pyyaml>=6.0.0",            # Recipe metadata parsing
]
```

### Optional Dependencies (install as needed)

```toml
[project.optional-dependencies]
clipboard = ["pyperclip>=1.8.0"]   # Clipboard functionality
gui = ["pywebview>=5.0.0"]         # Desktop GUI interface
all = ["pyperclip>=1.8.0", "pywebview>=5.0.0"]  # All optional features
dev = ["pytest>=7.4.0", ...]       # Development tools
```

---

## System Requirements

- **Python**: 3.9+
- **Operating System**: macOS, Linux, Windows
- **Chrome Browser**: For chrome-js Recipe execution

---

## Linux Prerequisites

Before installing frago on Linux, ensure your system meets the following requirements.

### What You Need to Prepare

| Dependency | Purpose | Required |
|------------|---------|----------|
| **Python 3.9+** | Frago runtime | Yes |
| **Node.js 20+** | Claude Code dependency | Yes (for Claude Code integration) |
| **Chrome Browser** | CDP browser automation | Yes (for CDP features) |
| **curl or wget** | Download installation scripts (nvm) | Yes (for auto-install) |
| **git** | Clone repositories | For development |

### What Frago Does NOT Do For You

1. **Install system packages** - Frago cannot run `sudo apt/dnf/pacman` commands
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

Before running `pip install frago-cli`, verify:

```bash
# Python 3.9+ installed
python3 --version

# pip available
pip --version  # or: python3 -m pip --version

# Network can access PyPI
pip index versions frago-cli

# Chrome installed (if using CDP features)
google-chrome --version

# Node.js 20+ installed (if using Claude Code integration)
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

### Package Managers

**Using pip (built-in)**:
```bash
# macOS uses pip3, not pip
pip3 install frago-cli

# Or use python3 -m pip (more reliable)
python3 -m pip install frago-cli
```

**Using uv (recommended)**:
```bash
# Install uv first
curl -LsSf https://astral.sh/uv/install.sh | sh
# or via Homebrew
brew install uv

# Then install frago
uv tool install frago-cli
```

### Chrome Browser

Chrome is typically pre-installed or available from [google.com/chrome](https://www.google.com/chrome/). Verify installation:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
```

### Pre-Installation Checklist

Before running `pip3 install frago-cli`, verify:

```bash
# Python 3.9+ installed (macOS 12+ includes Python 3)
python3 --version

# pip3 available
pip3 --version

# Xcode Command Line Tools installed
xcode-select -p

# Chrome installed (if using CDP features)
ls /Applications/Google\ Chrome.app

# Node.js 20+ installed (if using Claude Code integration)
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
# Search "Python 3.11" in Microsoft Store and install

# Option 2: winget
winget install Python.Python.3.11

# Option 3: Official installer
# Download from https://www.python.org/downloads/
# IMPORTANT: Check "Add Python to PATH" during installation!
```

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

### Package Managers

**Using pip**:
```powershell
# After Python installation, pip should be available
pip install frago-cli

# If pip not found, use:
python -m pip install frago-cli
```

**Using uv (recommended)**:
```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Then install frago
uv tool install frago-cli
```

### GUI Support (WebView2)

For GUI features, WebView2 Runtime is required:

```powershell
# Windows 11 usually has it pre-installed
# For Windows 10, install manually:
winget install Microsoft.EdgeWebView2Runtime
```

### Pre-Installation Checklist

Before running `pip install frago-cli`, verify in PowerShell:

```powershell
# Python 3.9+ installed
python --version

# pip available
pip --version

# Node.js 20+ installed (REQUIRED before frago init)
node --version

# Chrome installed (if using CDP features)
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
# Using pip
pip install --upgrade frago-cli

# Using uv
uv tool upgrade frago-cli
```

---

## Uninstall

```bash
# Using pip
pip uninstall frago-cli

# Using uv
uv tool uninstall frago-cli
```
