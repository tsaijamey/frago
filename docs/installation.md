# Installation

[简体中文](installation.zh-CN.md)

## Requirements

| Dependency | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.13+ | Core runtime |
| **Node.js** | 20+ | Claude Code integration |
| **Chrome** | Latest | CDP browser automation |

## Install

```bash
# 1. Install uv (package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh      # macOS/Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows

# 2. Install frago
uv tool install frago-cli

# 3. Initialize
frago init

# 4. Start web service
frago server start
# Open http://127.0.0.1:8093
```

## Verify

```bash
frago --version
frago recipe list
```

## Upgrade / Uninstall

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
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb && sudo apt -f install

# Fedora/RHEL
sudo dnf install -y python3 python3-pip curl git
sudo dnf install https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm

# Arch Linux
sudo pacman -S python python-pip curl git
yay -S google-chrome
```

</details>

<details>
<summary><b>macOS Prerequisites</b></summary>

```bash
# Install Xcode Command Line Tools
xcode-select --install

# Chrome is typically pre-installed or download from google.com/chrome
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

# Install Chrome
winget install Google.Chrome
```

</details>

---

## What `frago init` Does

1. **Checks dependencies** — Node.js 20+, Claude Code CLI
2. **Auto-installs** — Node.js via nvm (macOS/Linux only), Claude Code via npm
3. **Configures auth** — Default or custom API endpoint
4. **Installs resources** — Slash commands to `~/.claude/commands/`, recipes to `~/.frago/recipes/`

### Init Options

```bash
frago init --show-config      # Show current config
frago init --reset            # Reset and re-initialize
frago init --skip-deps        # Skip dependency checks
frago init --update-resources # Force update resources
```

## Development Setup

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```
