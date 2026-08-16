# Installation

[简体中文](installation.zh-CN.md)

## Desktop App

Download, install, and open from your app menu. That's it.

| Platform | Download |
|----------|----------|
| **macOS (Apple Silicon)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **macOS (Intel)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **Windows** | [.msi](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (deb)** | [.deb](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (rpm)** | [.rpm](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (AppImage)** | [.AppImage](https://github.com/tsaijamey/frago/releases/latest) |

> All downloads: [Releases page](https://github.com/tsaijamey/frago/releases/latest)

---

## CLI

The command-line interface to frago — like a shell to an OS. Everything the desktop app can do, the CLI can do too, plus browser automation, Recipe development, and direct agent control. Requires Python 3.13+ to install.

### Requirements

| Dependency | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.13+ | Core runtime |
| **Node.js** | 20+ | Claude Code integration |
| **Microsoft Edge** | Latest | Default browser for automation (Chromium/Chrome non-Stable also work as fallbacks) |

### Quick Install

```bash
# macOS/Linux
curl -fsSL https://frago.ai/install.sh | sh

# Windows
powershell -c "irm https://frago.ai/install.ps1 | iex"
```

<details>
<summary><b>Manual Installation</b></summary>

```bash
# 1. Install uv (package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh      # macOS/Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows

# 2. Install frago
uv tool install frago-cli

# 3. Initialize
frago init

# 4. Start server
frago server start
```

</details>

### Verify

```bash
frago --version
frago recipe list
```

### Upgrade / Uninstall

```bash
uv tool upgrade frago-cli    # Upgrade
uv tool uninstall frago-cli  # Uninstall
```

---

<details>
<summary><b>Linux Prerequisites</b></summary>

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y python3 python3-pip curl git
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main" | sudo tee /etc/apt/sources.list.d/microsoft-edge.list
sudo apt update && sudo apt install -y microsoft-edge-stable

# Fedora/RHEL
sudo dnf install -y python3 python3-pip curl git
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo dnf config-manager --add-repo https://packages.microsoft.com/yumrepos/edge
sudo dnf install -y microsoft-edge-stable

# Arch Linux
sudo pacman -S python python-pip curl git
yay -S microsoft-edge-stable
```

</details>

<details>
<summary><b>macOS Prerequisites</b></summary>

```bash
# Install Xcode Command Line Tools
xcode-select --install

# Edge may need manual installation — microsoft.com/edge
```

</details>

<details>
<summary><b>Windows Prerequisites</b></summary>

> **Important**: Windows does NOT support automatic Node.js installation. Install Node.js manually before `frago init`.

```powershell
# Install Python
winget install Python.Python.3.13

# Install Node.js (REQUIRED before frago init)
winget install OpenJS.NodeJS.LTS

# Edge ships with Windows 10/11; install it explicitly if removed
winget install Microsoft.Edge
```

</details>

---

## What `frago init` Does

1. **Checks dependencies** — Python 3.13+, Node.js 20+, Claude Code CLI, browser
2. **Auto-installs** — Node.js via nvm (macOS/Linux only), Claude Code via npm
3. **Configures a model profile** — official endpoint or custom (DeepSeek, proxies, local models)
4. **Installs the prompting engine** — deploys `frago-core` and registers hooks
   (static rules + lightweight AI) for Claude Code and opencode
5. **Installs resources** — slash commands to `~/.claude/commands/`, recipes to
   `~/.frago/recipes/`

### Init Options

```bash
frago init --show-config      # Show current config
frago init --reset            # Reset and re-initialize
frago init --skip-deps        # Skip dependency checks
frago init --non-interactive  # Non-interactive mode (defaults, CI/CD friendly)
```

## Development Setup

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```
